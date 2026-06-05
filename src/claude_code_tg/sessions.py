"""Chat session, queue, and runtime status helpers."""

import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from claude_code_tg.executor import (
    RunEvent,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.file_security import (
    open_rejecting_symlink_read,
    rejectable_symlink_path_component,
    replace_owner_only_text,
)

CLI_DEFAULT_LABEL = "Claude Code 默认"


class QueuedPrompt(NamedTuple):
    """A queued message plus the settings in effect when it was queued.

    The settings are snapshotted at enqueue time so a queued message runs
    under the settings the user had when they sent it, matching the
    "takes effect on the next message" wording rather than silently adopting a
    later /permissions, /model, or /effort change.
    """

    user_id: int
    prompt: str
    permission_mode: str | None
    model: str | None
    effort: str | None


ReplyCallback = Callable[[str], Awaitable[object]]


@dataclass
class ClaudeRuntimeStatus:
    """Last runtime metadata reported by Claude Code's stream-json output."""

    model: str = ""
    permission_mode: str = ""
    claude_code_version: str = ""
    cwd: str = ""
    mcp_servers: tuple[tuple[str, str], ...] = ()
    context_window: int | None = None
    max_output_tokens: int | None = None
    speed: str = ""
    fast_mode_state: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "permission_mode": self.permission_mode,
            "claude_code_version": self.claude_code_version,
            "cwd": self.cwd,
            "mcp_servers": [
                {"name": name, "status": status} for name, status in self.mcp_servers
            ],
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "speed": self.speed,
            "fast_mode_state": self.fast_mode_state,
            "updated_at": self.updated_at,
        }


def _runtime_text(value: object, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    return text[:limit]


def _runtime_int(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _runtime_mcp_servers(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    servers: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _runtime_text(item.get("name"), limit=80)
        if not name:
            continue
        status = _runtime_text(item.get("status"), limit=80) or "unknown"
        servers.append((name, status))
    return tuple(servers)


def _runtime_status_from_dict(value: object) -> ClaudeRuntimeStatus | None:
    if not isinstance(value, dict):
        return None
    updated_at = value.get("updated_at")
    return ClaudeRuntimeStatus(
        model=_runtime_text(value.get("model"), limit=160),
        permission_mode=_runtime_text(value.get("permission_mode"), limit=80),
        claude_code_version=_runtime_text(value.get("claude_code_version"), limit=80),
        cwd=_runtime_text(value.get("cwd"), limit=500),
        mcp_servers=_runtime_mcp_servers(value.get("mcp_servers")),
        context_window=_runtime_int(value.get("context_window")),
        max_output_tokens=_runtime_int(value.get("max_output_tokens")),
        speed=_runtime_text(value.get("speed"), limit=80),
        fast_mode_state=_runtime_text(value.get("fast_mode_state"), limit=80),
        updated_at=updated_at if isinstance(updated_at, (int, float)) else time.time(),
    )


class ChatSessionStore:
    """In-memory chat state plus small JSON status-file persistence."""

    def __init__(
        self,
        *,
        queue_max_size: int,
        permission_mode: str | None,
        model: str | None,
        effort: str | None,
        status_file: Path | None,
    ) -> None:
        self.queue_max_size = max(queue_max_size, 1)
        self.default_permission_mode = normalize_permission_mode(permission_mode)
        self.default_model = normalize_model(model)
        self.default_effort = normalize_effort(effort)
        self.status_file = status_file

        self.sessions: dict[int, str] = {}
        self.permission_modes: dict[int, str] = {}
        self.model_overrides: dict[int, str] = {}
        self.effort_overrides: dict[int, str] = {}
        self.runtime_statuses: dict[int, ClaudeRuntimeStatus] = {}
        self.session_versions: dict[int, int] = {}
        self.busy: set[int] = set()
        self.queues: dict[int, deque[QueuedPrompt]] = {}
        self.start_time: float = time.time()
        self.heartbeat_counter: int = 0

    def queue_total(self) -> int:
        return sum(len(queue) for queue in self.queues.values())

    def write_status(self) -> OSError | None:
        if not self.status_file:
            return None
        status = {
            "sessions": len(self.sessions),
            "sessions_full": {str(k): v for k, v in self.sessions.items()},
            "default_permission_mode": self.default_permission_mode or "claude-default",
            "permission_modes_full": {
                str(k): v for k, v in self.permission_modes.items()
            },
            "default_model": self.default_model or "claude-default",
            "model_overrides_full": {
                str(k): v for k, v in self.model_overrides.items()
            },
            "default_effort": self.default_effort or "claude-default",
            "effort_overrides_full": {
                str(k): v for k, v in self.effort_overrides.items()
            },
            "runtime_statuses_full": {
                str(k): v.to_dict() for k, v in self.runtime_statuses.items()
            },
            "busy_chats": list(self.busy),
            "queue_total": self.queue_total(),
            "uptime_seconds": int(time.time() - self.start_time),
            "timestamp": time.time(),
        }
        try:
            replace_owner_only_text(
                self.status_file, json.dumps(status, ensure_ascii=False)
            )
        except OSError as exc:
            return exc
        return None

    def restore_sessions(self) -> int:
        if (
            not self.status_file
            or rejectable_symlink_path_component(self.status_file)
            or not self.status_file.exists()
        ):
            return 0
        try:
            with open_rejecting_symlink_read(self.status_file) as f:
                data = json.load(f)
            saved = data.get("sessions_full", {})
            if not isinstance(saved, dict):
                return 0
            for chat_id_str, session_id in saved.items():
                if not isinstance(session_id, str):
                    continue
                self.sessions[int(chat_id_str)] = session_id
            saved_modes = data.get("permission_modes_full", {})
            if isinstance(saved_modes, dict):
                for chat_id_str, mode in saved_modes.items():
                    try:
                        normalized = normalize_permission_mode(mode)
                    except (TypeError, ValueError):
                        continue
                    if normalized:
                        self.permission_modes[int(chat_id_str)] = normalized
            saved_models = data.get("model_overrides_full", {})
            if isinstance(saved_models, dict):
                for chat_id_str, model in saved_models.items():
                    try:
                        normalized_model = normalize_model(model)
                    except (TypeError, ValueError):
                        continue
                    if normalized_model:
                        self.model_overrides[int(chat_id_str)] = normalized_model
            saved_efforts = data.get("effort_overrides_full", {})
            if isinstance(saved_efforts, dict):
                for chat_id_str, effort in saved_efforts.items():
                    try:
                        normalized_effort = normalize_effort(effort)
                    except (TypeError, ValueError):
                        continue
                    if normalized_effort:
                        self.effort_overrides[int(chat_id_str)] = normalized_effort
            saved_runtime_statuses = data.get("runtime_statuses_full", {})
            if isinstance(saved_runtime_statuses, dict):
                for chat_id_str, runtime_payload in saved_runtime_statuses.items():
                    try:
                        chat_id = int(chat_id_str)
                    except ValueError:
                        continue
                    runtime_status = _runtime_status_from_dict(runtime_payload)
                    if runtime_status:
                        self.runtime_statuses[chat_id] = runtime_status
            return len(self.sessions)
        except (json.JSONDecodeError, OSError, ValueError):
            return 0

    def get_or_create_session(self, chat_id: int) -> tuple[str | None, bool]:
        session_id = self.sessions.get(chat_id)
        if session_id:
            return session_id, True
        return None, False

    def effective_permission_mode(self, chat_id: int) -> str | None:
        return self.permission_modes.get(chat_id, self.default_permission_mode)

    def permission_mode_label(self, chat_id: int) -> str:
        return self.effective_permission_mode(chat_id) or CLI_DEFAULT_LABEL

    def effective_model(self, chat_id: int) -> str | None:
        return self.model_overrides.get(chat_id, self.default_model)

    def model_label(self, chat_id: int) -> str:
        return self.effective_model(chat_id) or CLI_DEFAULT_LABEL

    def effective_effort(self, chat_id: int) -> str | None:
        return self.effort_overrides.get(chat_id, self.default_effort)

    def effort_label(self, chat_id: int) -> str:
        return self.effective_effort(chat_id) or CLI_DEFAULT_LABEL

    def runtime_status(self, chat_id: int) -> ClaudeRuntimeStatus | None:
        return self.runtime_statuses.get(chat_id)

    def record_runtime_event(self, chat_id: int, event: RunEvent) -> bool:
        if not (
            event.runtime_model
            or event.runtime_permission_mode
            or event.runtime_claude_code_version
            or event.runtime_cwd
            or event.runtime_mcp_servers
            or event.runtime_speed
            or event.runtime_fast_mode_state
            or event.context_window is not None
            or event.max_output_tokens is not None
        ):
            return False
        runtime = self.runtime_statuses.setdefault(chat_id, ClaudeRuntimeStatus())
        changed = False

        def set_text(attr: str, value: str) -> None:
            nonlocal changed
            if value and getattr(runtime, attr) != value:
                setattr(runtime, attr, value)
                changed = True

        def set_int(attr: str, value: int | None) -> None:
            nonlocal changed
            if value is not None and getattr(runtime, attr) != value:
                setattr(runtime, attr, value)
                changed = True

        set_text("model", event.runtime_model)
        set_text("permission_mode", event.runtime_permission_mode)
        set_text("claude_code_version", event.runtime_claude_code_version)
        set_text("cwd", event.runtime_cwd)
        set_text("speed", event.runtime_speed)
        set_text("fast_mode_state", event.runtime_fast_mode_state)
        set_int("context_window", event.context_window)
        set_int("max_output_tokens", event.max_output_tokens)
        if (
            event.runtime_mcp_servers
            and runtime.mcp_servers != event.runtime_mcp_servers
        ):
            runtime.mcp_servers = event.runtime_mcp_servers
            changed = True
        if changed:
            runtime.updated_at = time.time()
        return changed

    def bump_session_version(self, chat_id: int) -> int:
        version = self.session_versions.get(chat_id, 0) + 1
        self.session_versions[chat_id] = version
        return version

    def session_version(self, chat_id: int) -> int:
        return self.session_versions.get(chat_id, 0)

    def set_session_if_current(
        self, chat_id: int, session_id: str, expected_version: int
    ) -> bool:
        if self.session_versions.get(chat_id, 0) != expected_version:
            return False
        self.sessions[chat_id] = session_id
        return True

    def reset_chat(self, chat_id: int) -> int:
        """Reset a chat to a clean slate; return how many queued items were dropped."""
        self.bump_session_version(chat_id)
        self.sessions.pop(chat_id, None)
        dropped = self.queues.pop(chat_id, None)
        # /new is a full reset: drop per-chat overrides so a
        # new session never silently inherits a stale (and possibly unsafe,
        # e.g. bypassPermissions) override. All pops run unconditionally.
        self.permission_modes.pop(chat_id, None)
        self.model_overrides.pop(chat_id, None)
        self.effort_overrides.pop(chat_id, None)
        self.runtime_statuses.pop(chat_id, None)
        return len(dropped) if dropped else 0

    def attach_session(self, chat_id: int, session_id: str) -> None:
        self.bump_session_version(chat_id)
        self.sessions[chat_id] = session_id
        self.runtime_statuses.pop(chat_id, None)
        self.queues.pop(chat_id, None)

    async def try_enqueue(
        self,
        chat_id: int,
        user_id: int,
        prompt: str,
        reply_fn: ReplyCallback,
    ) -> bool:
        """Try to enqueue a message.

        False means the caller should process immediately, and the chat has
        already been marked busy to reserve that runner under concurrent update
        handling.
        """
        if chat_id not in self.busy:
            self.busy.add(chat_id)
            return False
        queue = self.queues.get(chat_id)
        if queue is None or queue.maxlen != self.queue_max_size:
            queue = deque(maxlen=self.queue_max_size)
            self.queues[chat_id] = queue
        if len(queue) >= self.queue_max_size:
            await reply_fn("⚠️ 队列已满，请稍后再试。")
            return True
        # Snapshot settings now so later changes do not retroactively apply to
        # this already-queued message.
        queue.append(
            QueuedPrompt(
                user_id=user_id,
                prompt=prompt,
                permission_mode=self.effective_permission_mode(chat_id),
                model=self.effective_model(chat_id),
                effort=self.effective_effort(chat_id),
            )
        )
        await reply_fn(f"📋 已排队 ({len(queue)}/{self.queue_max_size})")
        return True

    def popleft_queue(self, chat_id: int) -> QueuedPrompt | None:
        queue = self.queues.get(chat_id)
        if not queue:
            return None
        item = queue.popleft()
        if not queue:
            del self.queues[chat_id]
        return item
