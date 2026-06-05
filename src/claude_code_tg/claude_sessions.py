"""Discover local Claude Code session ids for a project."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from claude_code_tg.file_security import (
    open_rejecting_symlink_read,
    rejectable_symlink_path_component,
)

_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")


@dataclass(frozen=True)
class ClaudeSessionInfo:
    session_id: str
    updated_at: float
    path: Path
    title: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    entrypoint: str | None = None
    size_bytes: int = 0


def encoded_project_path(project_dir: str) -> str:
    """Return Claude Code's project-history directory name for a project path."""
    resolved = Path(project_dir).expanduser().resolve(strict=False)
    return _NON_ALNUM_RE.sub("-", str(resolved))


def _legacy_slash_encoded_project_path(project_dir: str) -> str:
    resolved = Path(project_dir).expanduser().resolve(strict=False)
    return str(resolved).replace("/", "-").replace("\\", "-")


def project_sessions_dir(
    project_dir: str,
    *,
    claude_home: Path | None = None,
) -> Path:
    root = claude_home or Path.home() / ".claude"
    return root / "projects" / encoded_project_path(project_dir)


def rewrite_session_entrypoint_for_cli_resume(
    project_dir: str,
    session_id: str,
    *,
    claude_home: Path | None = None,
) -> bool:
    """Rewrite a tgcc ``sdk-cli`` transcript so Claude CLI's picker may show it."""
    try:
        parsed_session_id = str(uuid.UUID(session_id))
    except ValueError:
        return False

    session_path = (
        project_sessions_dir(project_dir, claude_home=claude_home)
        / f"{parsed_session_id}.jsonl"
    )
    if rejectable_symlink_path_component(session_path.parent):
        return False
    if session_path.is_symlink():
        return False
    try:
        info = session_path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False

    temp_path = session_path.with_name(f".{session_path.name}.{uuid.uuid4().hex}.tmp")
    changed = False
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            temp_path.chmod(0o600)
        with (
            open_rejecting_symlink_read(session_path) as source,
            os.fdopen(fd, "w", encoding="utf-8") as target,
        ):
            fd = -1
            for line in source:
                rewritten_line = line
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    record = None
                if isinstance(record, dict) and record.get("entrypoint") == "sdk-cli":
                    record["entrypoint"] = "cli"
                    rewritten_line = (
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                    changed = True
                target.write(rewritten_line)
            target.flush()
            os.fsync(target.fileno())
        if not changed:
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)
            return False
        current_info = session_path.lstat()
        if (
            current_info.st_dev != info.st_dev
            or current_info.st_ino != info.st_ino
            or current_info.st_size != info.st_size
            or current_info.st_mtime_ns != info.st_mtime_ns
        ):
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)
            return False
        temp_path.replace(session_path)
    except (OSError, UnicodeError):
        with suppress(OSError):
            if "fd" in locals() and fd != -1:
                os.close(fd)
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        return False
    return True


def related_project_session_dirs(
    project_dir: str,
    *,
    claude_home: Path | None = None,
) -> list[Path]:
    """Return Claude history dirs that may contain sessions for ``project_dir``.

    Claude Code stores project history using a sanitized absolute path where
    every non-alphanumeric character becomes ``-``. The legacy slash-only form
    is kept as a fallback for older tgcc builds that used the wrong encoding.
    """
    resolved = Path(project_dir).expanduser().resolve(strict=False)
    candidate_paths = [resolved]
    if "_" in resolved.name:
        candidate_paths.append(resolved.with_name(resolved.name.replace("_", "-")))
    if "-" in resolved.name:
        candidate_paths.append(resolved.with_name(resolved.name.replace("-", "_")))

    root = claude_home or Path.home() / ".claude"
    dirs: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidate_paths:
        directory = project_sessions_dir(str(candidate), claude_home=claude_home)
        if directory not in seen:
            seen.add(directory)
            dirs.append(directory)

        legacy_directory = (
            root / "projects" / _legacy_slash_encoded_project_path(str(candidate))
        )
        if legacy_directory not in seen:
            seen.add(legacy_directory)
            dirs.append(legacy_directory)
    return dirs


def _discover_sessions_in_dir(
    history_dir: Path,
    *,
    resume_only: bool,
    include_headless: bool,
) -> list[ClaudeSessionInfo]:
    """List local Claude Code session files under one history directory.

    For ``resume_only=True``, metadata is inspected to match Claude Code's local
    ``/resume`` history more closely: one-shot commands without a response are
    ignored, and headless ``claude -p`` sessions are included only when
    ``include_headless`` is true.
    """
    if rejectable_symlink_path_component(history_dir):
        return []
    try:
        candidates = list(history_dir.iterdir())
    except OSError:
        return []

    sessions: list[ClaudeSessionInfo] = []
    for candidate in candidates:
        if candidate.suffix != ".jsonl" or candidate.is_symlink():
            continue
        try:
            session_id = str(uuid.UUID(candidate.stem))
            info = candidate.stat()
        except (OSError, ValueError):
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        metadata = _read_session_metadata(candidate, session_id)
        if resume_only and not _is_resume_history(
            metadata, include_headless=include_headless
        ):
            continue
        sessions.append(
            ClaudeSessionInfo(
                session_id=session_id,
                updated_at=info.st_mtime,
                path=candidate,
                title=_session_title(metadata),
                cwd=metadata.cwd,
                git_branch=metadata.git_branch,
                entrypoint=metadata.entrypoint,
                size_bytes=info.st_size,
            )
        )

    sessions.sort(key=lambda item: item.updated_at, reverse=True)
    return sessions


@dataclass
class _SessionMetadata:
    session_id: str
    ai_title: str | None = None
    last_prompt: str | None = None
    first_user_message: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    entrypoint: str | None = None
    entrypoints: set[str] | None = None
    user_count: int = 0
    assistant_count: int = 0


def _read_session_metadata(path: Path, session_id: str) -> _SessionMetadata:
    metadata = _SessionMetadata(session_id=session_id, entrypoints=set())
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                _update_session_metadata(metadata, record)
    except OSError:
        return metadata
    return metadata


def _update_session_metadata(
    metadata: _SessionMetadata,
    record: dict[object, object],
) -> None:
    record_type = _string_value(record.get("type"))
    if record_type == "ai-title":
        metadata.ai_title = _string_value(record.get("aiTitle")) or metadata.ai_title
    elif record_type == "last-prompt":
        metadata.last_prompt = (
            _string_value(record.get("lastPrompt")) or metadata.last_prompt
        )
    elif record_type == "user":
        metadata.user_count += 1
        if metadata.first_user_message is None:
            metadata.first_user_message = _message_text(record.get("message"))
    elif record_type == "assistant":
        metadata.assistant_count += 1

    cwd = _string_value(record.get("cwd"))
    if cwd:
        metadata.cwd = cwd

    git_branch = _string_value(record.get("gitBranch"))
    if git_branch:
        metadata.git_branch = git_branch

    entrypoint = _string_value(record.get("entrypoint"))
    if entrypoint:
        metadata.entrypoint = entrypoint
        if metadata.entrypoints is not None:
            metadata.entrypoints.add(entrypoint)


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _message_text(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return _string_value(content)
    return None


def _is_resume_history(
    metadata: _SessionMetadata, *, include_headless: bool = False
) -> bool:
    entrypoints = metadata.entrypoints or set()
    allowed_entrypoints = {"cli"}
    if include_headless:
        allowed_entrypoints.add("sdk-cli")
    if entrypoints and not entrypoints.issubset(allowed_entrypoints):
        return False
    return metadata.assistant_count > 0 or metadata.user_count > 1


def _session_title(metadata: _SessionMetadata) -> str | None:
    return (
        _clean_title(metadata.ai_title)
        or _clean_title(metadata.last_prompt)
        or _clean_title(metadata.first_user_message)
    )


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(
        r"<local-command-caveat>.*?</local-command-caveat>",
        "",
        value,
        flags=re.DOTALL,
    )
    value = re.sub(r"<[^>]+>", "", value)
    value = " ".join(value.split())
    if not value:
        return None
    return value[:120]


def discover_project_sessions(
    project_dir: str,
    *,
    claude_home: Path | None = None,
    include_renamed_siblings: bool = True,
    resume_only: bool = True,
    include_headless: bool = False,
) -> list[ClaudeSessionInfo]:
    """List local Claude Code sessions for ``project_dir``.

    By default, the result follows the local Claude Code ``/resume`` history
    surface: only interactive CLI-created, resumeable conversations are
    returned. Set ``include_headless`` to include tgcc/``claude -p`` sessions.
    """
    if include_renamed_siblings:
        history_dirs = related_project_session_dirs(
            project_dir, claude_home=claude_home
        )
    else:
        history_dirs = [project_sessions_dir(project_dir, claude_home=claude_home)]

    sessions: list[ClaudeSessionInfo] = []
    seen_ids: set[str] = set()
    for history_dir in history_dirs:
        for item in _discover_sessions_in_dir(
            history_dir,
            resume_only=resume_only,
            include_headless=include_headless,
        ):
            if item.session_id in seen_ids:
                continue
            seen_ids.add(item.session_id)
            sessions.append(item)

    sessions.sort(key=lambda item: item.updated_at, reverse=True)
    return sessions
