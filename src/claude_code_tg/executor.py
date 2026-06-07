"""CLI subprocess executor - manages Claude Code CLI invocations."""

import asyncio
import json
import logging
import os
import re
import signal
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

from claude_code_tg.claude_sessions import rewrite_session_entrypoint_for_cli_resume
from claude_code_tg.interaction_log import claude_recv, claude_send
from claude_code_tg.process_control import send_signal_to_process_tree
from claude_code_tg.sanitizer import sanitize
from claude_code_tg.utils import parse_env_bool

logger = logging.getLogger(__name__)

MAX_PROMPT_LENGTH = 50000
DEFAULT_TIMEOUT_SECONDS = 300
INVALID_TIMEOUT_FALLBACK_SECONDS = 600
VALID_PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "plan",
    "auto",
    "dontAsk",
    "bypassPermissions",
}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max", "ultracode")
VALID_EFFORT_LEVELS = set(EFFORT_LEVELS)
_PERMISSION_MODE_ALIASES = {
    "default": "default",
    "ask": "default",
    "acceptedits": "acceptEdits",
    "accept-edits": "acceptEdits",
    "accept_edits": "acceptEdits",
    "edit": "acceptEdits",
    "plan": "plan",
    "auto": "auto",
    "dontask": "dontAsk",
    "dont-ask": "dontAsk",
    "dont_ask": "dontAsk",
    "deny": "dontAsk",
    "bypasspermissions": "bypassPermissions",
    "bypass-permissions": "bypassPermissions",
    "bypass_permissions": "bypassPermissions",
    "bypass": "bypassPermissions",
    "skip": "bypassPermissions",
}
_EFFORT_ALIASES = {
    "low": "low",
    "medium": "medium",
    "med": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "x-high": "xhigh",
    "x_high": "xhigh",
    "max": "max",
    "ultracode": "ultracode",
    "ultra-code": "ultracode",
    "ultra_code": "ultracode",
}
MODEL_VALUE_RE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,120}$")
SENSITIVE_COMMAND_ARG_RE = re.compile(
    r"(?i)(\B--?(?:api[-_]?key|token|access[-_]?token|secret|password|passwd|"
    r"credential|credentials|auth|authorization)(?:[-_][A-Za-z0-9]+)?)(=|\s+)"
    r"([\"']?)([^\"'\s;]+)\3"
)
TOOL_INPUT_SUMMARY_LIMIT = 300
TOOL_RESULT_TAIL_LINES = 8
TOOL_RESULT_TAIL_CHARS = 1200


STDERR_RETAIN_CHARS = 64 * 1024


async def _drain_stderr(stream: asyncio.StreamReader | None) -> str:
    """Consume stderr to prevent pipe deadlock, retaining a bounded prefix.

    A long-lived or noisy subprocess can emit unbounded stderr; we keep only
    the first ``STDERR_RETAIN_CHARS`` (the root error is usually there) while
    still reading the stream to completion so the pipe never blocks.
    """
    if not stream:
        return ""
    chunks: list[str] = []
    total = 0
    truncated = False
    async for line in stream:
        if truncated:
            continue
        text = line.decode(errors="replace")
        chunks.append(text)
        total += len(text)
        if total >= STDERR_RETAIN_CHARS:
            truncated = True
    result = "".join(chunks)
    if truncated:
        result = result[:STDERR_RETAIN_CHARS] + "\n...(stderr truncated)"
    return result


async def _await_stderr(task: asyncio.Task) -> str:
    """Await a stderr drain task, swallowing CancelledError."""
    try:
        return await task
    except asyncio.CancelledError:
        return ""


async def _discard_oversized_line(stream: asyncio.StreamReader) -> None:
    """Consume and drop bytes up to the next newline after a LimitOverrunError.

    On ``LimitOverrunError`` the offending data stays in the reader's buffer, so
    a naive ``continue`` would loop forever. We drain chunk by chunk until the
    newline is reached (or EOF), landing the reader exactly at the next line.
    """
    while True:
        try:
            await stream.readuntil(b"\n")
            return
        except asyncio.LimitOverrunError as exc:
            try:
                await stream.readexactly(exc.consumed)
            except asyncio.IncompleteReadError:
                return
        except asyncio.IncompleteReadError:
            return


async def _write_prompt_stdin(stream: asyncio.StreamWriter | None, prompt: str) -> None:
    """Send the prompt through stdin so it is not exposed in argv."""
    if stream is None:
        return
    try:
        stream.write(prompt.encode())
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        return
    finally:
        stream.close()
    with suppress(BrokenPipeError, ConnectionResetError, RuntimeError):
        await stream.wait_closed()


def _coerce_timeout_seconds(timeout: int) -> int | None:
    """Return stdout idle-check seconds; negative means unlimited."""
    if timeout < 0:
        return None
    if timeout == 0:
        logger.warning(
            "timeout=0 is invalid; using %ss fallback",
            INVALID_TIMEOUT_FALLBACK_SECONDS,
        )
        return INVALID_TIMEOUT_FALLBACK_SECONDS
    return timeout


def normalize_permission_mode(value: str | None) -> str | None:
    """Return a canonical Claude Code permission mode."""
    if value is None:
        return None
    key = value.strip()
    if not key:
        return None
    mode = _PERMISSION_MODE_ALIASES.get(key.lower())
    if not mode:
        raise ValueError(f"invalid permission mode: {value}")
    return mode


def normalize_model(value: str | None) -> str | None:
    """Return an optional Claude Code model selector."""
    if value is None:
        return None
    model = value.strip()
    if not model:
        return None
    if model.lower() in {"default", "claude-default", "none", "off"}:
        return None
    if model.startswith("-") or not MODEL_VALUE_RE.fullmatch(model):
        raise ValueError(f"invalid model: {value}")
    return model


def normalize_effort(value: str | None) -> str | None:
    """Return a canonical Claude Code effort level."""
    if value is None:
        return None
    key = value.strip()
    if not key:
        return None
    if key.lower() in {"default", "claude-default", "none", "off"}:
        return None
    effort = _EFFORT_ALIASES.get(key.lower())
    if not effort:
        raise ValueError(f"invalid effort: {value}")
    return effort


def build_cli_setting_args(
    *,
    permission_mode: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[str, ...]:
    """Return Claude CLI setting flags for the supplied runtime choices."""
    args: list[str] = []
    mode = normalize_permission_mode(permission_mode)
    if mode:
        args.extend(["--permission-mode", mode])
    elif parse_env_bool(os.environ.get("CLAUDE_SKIP_PERMISSIONS")):
        args.append("--dangerously-skip-permissions")

    normalized_model = normalize_model(model)
    if normalized_model:
        args.extend(["--model", normalized_model])

    normalized_effort = normalize_effort(effort)
    if normalized_effort:
        args.extend(["--effort", normalized_effort])

    return tuple(args)


@dataclass
class ExecutionResult:
    text: str
    session_id: str = ""
    is_error: bool = False
    was_stopped: bool = False
    duration_ms: int = 0
    num_turns: int = 0
    tool_count: int = 0


@dataclass(frozen=True)
class UsageSnapshot:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    @property
    def has_values(self) -> bool:
        return any(
            value is not None
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.cache_creation_input_tokens,
                self.cache_read_input_tokens,
            )
        )


@dataclass(frozen=True)
class RunEvent:
    kind: Literal[
        "runtime",
        "tool_started",
        "tool_result",
        "assistant_text",
        "usage",
        "run_completed",
        "run_error",
    ]
    tool_index: int | None = None
    tool_name: str = ""
    tool_id: str = ""
    summary: str = ""
    output: str = ""
    text: str = ""
    is_error: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    runtime_model: str = ""
    runtime_permission_mode: str = ""
    runtime_fast_mode_state: str = ""
    runtime_claude_code_version: str = ""
    runtime_cwd: str = ""
    runtime_mcp_servers: tuple[tuple[str, str], ...] = ()
    runtime_speed: str = ""
    context_window: int | None = None
    max_output_tokens: int | None = None


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _tail_text(text: str, *, max_lines: int, max_chars: int) -> str:
    if max_lines <= 0 or max_chars <= 0:
        return ""
    stripped = text.strip()
    if not stripped:
        return ""
    lines = stripped.splitlines()
    tailed = "\n".join(lines[-max_lines:])
    if len(tailed) > max_chars:
        tailed = tailed[-max_chars:].lstrip()
    return tailed


def _usage_int(usage: object, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _usage_int_any(usage: object, *keys: str) -> int | None:
    for key in keys:
        value = _usage_int(usage, key)
        if value is not None:
            return value
    return None


def _usage_snapshot(usage: object) -> UsageSnapshot:
    return UsageSnapshot(
        input_tokens=_usage_int_any(usage, "input_tokens", "inputTokens"),
        output_tokens=_usage_int_any(usage, "output_tokens", "outputTokens"),
        cache_creation_input_tokens=_usage_int_any(
            usage,
            "cache_creation_input_tokens",
            "cacheCreationInputTokens",
        ),
        cache_read_input_tokens=_usage_int_any(
            usage,
            "cache_read_input_tokens",
            "cacheReadInputTokens",
        ),
    )


def _runtime_str(value: object, *, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or text == "<synthetic>":
        return ""
    return _truncate_text(sanitize(text), limit)


def _context_window_value(data: object) -> int | None:
    return _usage_int_any(data, "contextWindow", "context_window")


def _max_output_tokens_value(data: object) -> int | None:
    return _usage_int_any(data, "maxOutputTokens", "max_output_tokens")


def _runtime_field_str(data: object, key: str, *, limit: int = 160) -> str:
    if not isinstance(data, dict):
        return ""
    return _runtime_str(data.get(key), limit=limit)


def _mcp_server_statuses(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    servers: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _runtime_str(item.get("name"), limit=80)
        if not name:
            continue
        status = _runtime_str(item.get("status"), limit=80) or "unknown"
        servers.append((name, status))
    return tuple(servers)


def _model_usage_runtime(model_usage: object) -> tuple[str, int | None, int | None]:
    if not isinstance(model_usage, dict):
        return "", None, None
    for raw_model, usage in model_usage.items():
        model = _runtime_str(raw_model)
        if model:
            return model, _context_window_value(usage), _max_output_tokens_value(usage)
    return "", None, None


def _json_summary(value: object, limit: int = TOOL_INPUT_SUMMARY_LIMIT) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return _truncate_text(sanitize(text), limit)


def _first_str(data: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return sanitize(value.strip())
    return ""


def sanitize_command(command: str) -> str:
    """Redact common secret-bearing CLI flag values before display."""
    sanitized = sanitize(command)

    def replace(match: re.Match[str]) -> str:
        flag = match.group(1)
        sep = "=" if match.group(2) == "=" else " "
        quote = match.group(3)
        return f"{flag}{sep}{quote}***{quote}"

    return SENSITIVE_COMMAND_ARG_RE.sub(replace, sanitized)


def summarize_tool_input(tool_name: str, raw_input: object) -> str:
    """Return a compact, safe summary for a Claude tool input payload."""
    if not isinstance(raw_input, dict):
        return _json_summary(raw_input)

    name = tool_name.lower()
    if name == "bash":
        raw_command = _first_str(raw_input, ("command", "cmd"))
        command = sanitize_command(raw_command) if raw_command else ""
        description = _first_str(raw_input, ("description",))
        if command and description:
            return _truncate_text(f"{description}\n{command}", TOOL_INPUT_SUMMARY_LIMIT)
        if command:
            return _truncate_text(command, TOOL_INPUT_SUMMARY_LIMIT)
        if description:
            return _truncate_text(description, TOOL_INPUT_SUMMARY_LIMIT)

    if name in {"read", "edit", "multiedit", "write", "notebookread", "notebookedit"}:
        path = _first_str(raw_input, ("file_path", "path", "notebook_path"))
        if path:
            return _truncate_text(path, TOOL_INPUT_SUMMARY_LIMIT)

    if name in {"grep", "glob"}:
        parts = []
        pattern = _first_str(raw_input, ("pattern",))
        path = _first_str(raw_input, ("path",))
        glob = _first_str(raw_input, ("glob",))
        if pattern:
            parts.append(f"pattern: {pattern}")
        if glob:
            parts.append(f"glob: {glob}")
        if path:
            parts.append(f"path: {path}")
        if parts:
            return _truncate_text("\n".join(parts), TOOL_INPUT_SUMMARY_LIMIT)

    return _json_summary(raw_input)


def summarize_tool_result_content(raw_content: object) -> str:
    """Return a safe tail summary for a Claude tool_result content payload."""
    if isinstance(raw_content, str):
        text = raw_content
    elif isinstance(raw_content, list):
        chunks: list[str] = []
        for item in raw_content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    chunks.append(value)
            elif isinstance(item, str):
                chunks.append(item)
        text = "\n".join(chunks)
    else:
        text = _json_summary(raw_content, limit=TOOL_RESULT_TAIL_CHARS)
    return sanitize(
        _tail_text(
            text, max_lines=TOOL_RESULT_TAIL_LINES, max_chars=TOOL_RESULT_TAIL_CHARS
        )
    )


class Executor:
    def __init__(self) -> None:
        self._processes: dict[int, asyncio.subprocess.Process] = {}
        self._stopped: set[int] = set()

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

    async def run(
        self,
        prompt: str,
        chat_id: int,
        session_id: str | None = None,
        project_dir: str = ".",
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        permission_mode: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        cli_resume_compat: bool = False,
        on_tool_use: Callable[[int], Awaitable[None]] | None = None,
        on_event: Callable[[RunEvent], Awaitable[None]] | None = None,
    ) -> ExecutionResult:
        is_new = session_id is None
        active_session_id = session_id or self.new_session_id()

        if len(prompt) > MAX_PROMPT_LENGTH:
            prompt = prompt[:MAX_PROMPT_LENGTH] + "\n...(truncated)"

        cmd = [
            "claude",
            "-p",
            "--input-format",
            "text",
            "--output-format",
            "stream-json",
            "--verbose",
        ]

        cmd.extend(
            build_cli_setting_args(
                permission_mode=permission_mode,
                model=model,
                effort=effort,
            )
        )

        if is_new:
            cmd.extend(["--session-id", active_session_id])
        else:
            cmd.extend(["--resume", active_session_id])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,  # 1MB buffer for large CLI output
            cwd=project_dir,
            start_new_session=True,
        )
        self._processes[chat_id] = process

        tool_count = 0
        result_data: dict[str, object] | None = None
        pending_tool_ids: list[str] = []
        tool_names_by_id: dict[str, str] = {}
        tool_indices_by_id: dict[str, int] = {}

        async def emit(event: RunEvent) -> None:
            if on_event:
                await on_event(event)

        stderr_task = asyncio.create_task(_drain_stderr(process.stderr))
        await _write_prompt_stdin(process.stdin, prompt)
        claude_send(chat_id, prompt)

        try:
            assert process.stdout is not None
            idle_timeout = _coerce_timeout_seconds(timeout)
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(), timeout=idle_timeout
                    )
                except TimeoutError:
                    if process.returncode is None:
                        logger.debug(
                            "Claude process still running after %ss without stdout",
                            idle_timeout,
                        )
                        continue
                    break
                except (asyncio.LimitOverrunError, ValueError):
                    # A single stream-json line exceeded the 1MB buffer (e.g. a
                    # huge tool result). Drain and discard that line instead of
                    # letting the exception crash the whole run.
                    logger.warning(
                        "Discarding oversized stdout line (>%d bytes)",
                        1024 * 1024,
                    )
                    await _discard_oversized_line(process.stdout)
                    continue
                if not line:
                    break

                decoded = line.decode(errors="replace").strip()
                if not decoded:
                    continue
                try:
                    event = json.loads(decoded)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "system":
                    runtime_model = _runtime_str(event.get("model"))
                    runtime_permission_mode = _runtime_str(
                        event.get("permissionMode"), limit=80
                    )
                    runtime_fast_mode_state = _runtime_str(
                        event.get("fast_mode_state"), limit=40
                    )
                    runtime_claude_code_version = _runtime_str(
                        event.get("claude_code_version"), limit=80
                    )
                    runtime_cwd = _runtime_str(event.get("cwd"), limit=500)
                    runtime_mcp_servers = _mcp_server_statuses(event.get("mcp_servers"))
                    if (
                        runtime_model
                        or runtime_permission_mode
                        or runtime_fast_mode_state
                        or runtime_claude_code_version
                        or runtime_cwd
                        or runtime_mcp_servers
                    ):
                        await emit(
                            RunEvent(
                                kind="runtime",
                                runtime_model=runtime_model,
                                runtime_permission_mode=runtime_permission_mode,
                                runtime_fast_mode_state=runtime_fast_mode_state,
                                runtime_claude_code_version=(
                                    runtime_claude_code_version
                                ),
                                runtime_cwd=runtime_cwd,
                                runtime_mcp_servers=runtime_mcp_servers,
                            )
                        )

                elif event_type == "assistant":
                    message = event.get("message", {})
                    if not isinstance(message, dict):
                        continue
                    runtime_model = _runtime_str(message.get("model"))
                    if runtime_model:
                        await emit(
                            RunEvent(kind="runtime", runtime_model=runtime_model)
                        )
                    usage = _usage_snapshot(message.get("usage"))
                    content = message.get("content", [])
                    emitted_content_event = False
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            block_type = block.get("type")
                            if block_type == "tool_use":
                                tool_count += 1
                                tool_name = block.get("name")
                                if not isinstance(tool_name, str):
                                    tool_name = "tool"
                                tool_id = block.get("id")
                                if not isinstance(tool_id, str) or not tool_id:
                                    tool_id = f"tool-{tool_count}"
                                pending_tool_ids.append(tool_id)
                                tool_names_by_id[tool_id] = tool_name
                                tool_indices_by_id[tool_id] = tool_count
                                await emit(
                                    RunEvent(
                                        kind="tool_started",
                                        tool_index=tool_count,
                                        tool_name=tool_name,
                                        tool_id=tool_id,
                                        summary=summarize_tool_input(
                                            tool_name, block.get("input")
                                        ),
                                        input_tokens=usage.input_tokens,
                                        output_tokens=usage.output_tokens,
                                        cache_creation_input_tokens=(
                                            usage.cache_creation_input_tokens
                                        ),
                                        cache_read_input_tokens=(
                                            usage.cache_read_input_tokens
                                        ),
                                    )
                                )
                                emitted_content_event = True
                                if on_tool_use:
                                    await on_tool_use(tool_count)
                            elif block_type == "text":
                                text = block.get("text")
                                if isinstance(text, str) and text.strip():
                                    await emit(
                                        RunEvent(
                                            kind="assistant_text",
                                            text=_truncate_text(
                                                sanitize(text.strip()), 300
                                            ),
                                            input_tokens=usage.input_tokens,
                                            output_tokens=usage.output_tokens,
                                            cache_creation_input_tokens=(
                                                usage.cache_creation_input_tokens
                                            ),
                                            cache_read_input_tokens=(
                                                usage.cache_read_input_tokens
                                            ),
                                        )
                                    )
                                    emitted_content_event = True
                    if usage.has_values and not emitted_content_event:
                        await emit(
                            RunEvent(
                                kind="usage",
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                cache_creation_input_tokens=(
                                    usage.cache_creation_input_tokens
                                ),
                                cache_read_input_tokens=usage.cache_read_input_tokens,
                            )
                        )

                elif event_type == "user":
                    content = event.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if (
                                not isinstance(block, dict)
                                or block.get("type") != "tool_result"
                            ):
                                continue
                            tool_id = block.get("tool_use_id")
                            if not isinstance(tool_id, str) or not tool_id:
                                tool_id = (
                                    pending_tool_ids[0] if pending_tool_ids else ""
                                )
                            if tool_id in pending_tool_ids:
                                pending_tool_ids.remove(tool_id)
                            await emit(
                                RunEvent(
                                    kind="tool_result",
                                    tool_index=tool_indices_by_id.get(tool_id),
                                    tool_name=tool_names_by_id.get(tool_id, ""),
                                    tool_id=tool_id,
                                    output=summarize_tool_result_content(
                                        block.get("content")
                                    ),
                                    is_error=bool(block.get("is_error", False)),
                                )
                            )

                elif event_type == "result":
                    result_data = event

            await process.wait()
        except BaseException:
            # Includes asyncio.CancelledError (handler torn down / bot
            # shutting down): never leak the subprocess or the stderr drain
            # task. Signal synchronously — awaiting during cancellation could
            # re-raise before cleanup completes.
            if process.returncode is None:
                self._terminate_process_tree(process)
            stderr_task.cancel()
            raise
        finally:
            # Guard by identity: a queued follow-up run for the same chat may
            # have already replaced this entry; don't evict a newer process.
            if self._processes.get(chat_id) is process:
                self._processes.pop(chat_id, None)

        was_stopped = chat_id in self._stopped
        self._stopped.discard(chat_id)

        def apply_cli_resume_compat(session_id_to_rewrite: str) -> None:
            if not cli_resume_compat:
                return
            if rewrite_session_entrypoint_for_cli_resume(
                project_dir, session_id_to_rewrite
            ):
                logger.info(
                    "Rewrote Claude transcript entrypoint for CLI resume picker | session_id=%s",
                    session_id_to_rewrite,
                )

        if was_stopped:
            await _await_stderr(stderr_task)
            apply_cli_resume_compat(active_session_id)
            await emit(RunEvent(kind="run_error", text="已被用户停止。", is_error=True))
            return ExecutionResult(
                text="⏹ 已被用户停止。",
                session_id=active_session_id,
                was_stopped=True,
                tool_count=tool_count,
            )

        if result_data:
            await _await_stderr(stderr_task)
            raw_text = result_data.get("result", "")
            text = raw_text if isinstance(raw_text, str) else ""
            is_error = bool(result_data.get("is_error", False))
            if is_error and not text:
                text = "执行出错，无输出。"
            claude_recv(chat_id, text)
            raw_session_id = result_data.get("session_id")
            result_session_id = (
                raw_session_id if isinstance(raw_session_id, str) else active_session_id
            )
            apply_cli_resume_compat(result_session_id)
            raw_duration_ms = result_data.get("duration_ms", 0)
            duration_ms = raw_duration_ms if isinstance(raw_duration_ms, int) else 0
            raw_num_turns = result_data.get("num_turns", 0)
            num_turns = raw_num_turns if isinstance(raw_num_turns, int) else 0
            runtime_model, context_window, max_output_tokens = _model_usage_runtime(
                result_data.get("modelUsage")
            )
            if not runtime_model:
                runtime_model = _runtime_str(result_data.get("model"))
            usage = _usage_snapshot(result_data.get("usage"))
            runtime_speed = _runtime_field_str(result_data.get("usage"), "speed")
            await emit(
                RunEvent(
                    kind="run_error" if is_error else "run_completed",
                    text=sanitize(text) if text else "",
                    is_error=is_error,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens,
                    cache_read_input_tokens=usage.cache_read_input_tokens,
                    runtime_model=runtime_model,
                    runtime_speed=runtime_speed,
                    context_window=context_window,
                    max_output_tokens=max_output_tokens,
                )
            )
            return ExecutionResult(
                text=sanitize(text) if text else "执行完成，无文本输出。",
                session_id=result_session_id,
                is_error=is_error,
                duration_ms=duration_ms,
                num_turns=num_turns,
                tool_count=tool_count,
            )

        stderr_output = (await stderr_task).strip()

        if process.returncode != 0:
            apply_cli_resume_compat(active_session_id)
            err_msg = sanitize(stderr_output) if stderr_output else "进程异常退出。"
            claude_recv(chat_id, f"(exit {process.returncode}) {err_msg}")
            await emit(RunEvent(kind="run_error", text=err_msg, is_error=True))
            return ExecutionResult(
                text=f"❌ {err_msg}",
                session_id=active_session_id,
                is_error=True,
                tool_count=tool_count,
            )

        apply_cli_resume_compat(active_session_id)
        await emit(RunEvent(kind="run_completed", text="执行完成，无输出。"))
        return ExecutionResult(
            text="执行完成，无输出。",
            session_id=active_session_id,
            tool_count=tool_count,
        )

    async def stop(self, chat_id: int) -> bool:
        process = self._processes.get(chat_id)
        if not process or process.returncode is not None:
            return False
        self._stopped.add(chat_id)
        await self._kill(process)
        return True

    async def shutdown(self) -> None:
        """Terminate every live subprocess. Called on application shutdown."""
        processes = list(self._processes.values())
        await asyncio.gather(
            *(self._kill(process) for process in processes),
            return_exceptions=True,
        )

    async def _kill(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        self._terminate_process_tree(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            self._kill_process_tree(process)
            await process.wait()

    def _terminate_process_tree(self, process: asyncio.subprocess.Process) -> None:
        self._signal_process_tree(process, signal.SIGTERM)

    def _kill_process_tree(self, process: asyncio.subprocess.Process) -> None:
        self._signal_process_tree(process, signal.SIGKILL)

    def _signal_process_tree(
        self, process: asyncio.subprocess.Process, sig: signal.Signals
    ) -> None:
        pid = getattr(process, "pid", None)
        if pid:
            try:
                send_signal_to_process_tree(pid, sig)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass
        if sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
