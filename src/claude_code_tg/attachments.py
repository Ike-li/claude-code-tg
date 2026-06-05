"""Attachment storage helpers."""

import os
import re
import stat
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from claude_code_tg.file_security import (
    _raise_if_path_replaced,
    _unlink_created_file,
    ensure_owner_only_dir,
    open_rejecting_symlink_read_bytes,
    rejectable_symlink_path_component,
)

DEFAULT_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_ATTACHMENT_MODE = "path"
DEFAULT_ATTACHMENT_PROMPT = "请分析这个附件。"
PROJECT_ATTACHMENT_DIRNAME = ".tgcc-attachments"
VALID_ATTACHMENT_MODES = {"path", "copy-to-project", "reject"}
_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class AttachmentInfo:
    kind: str
    path: Path
    original_name: str
    size: int | None = None
    mode: str = DEFAULT_ATTACHMENT_MODE


@dataclass(frozen=True)
class AttachmentPruneResult:
    root: Path
    root_exists: bool
    files: int
    byte_count: int
    dirs_removed: int
    errors: tuple[str, ...] = ()
    dry_run: bool = False


def normalize_attachment_mode(value: str | None) -> str:
    """Return a canonical attachment handling mode."""
    if value is None:
        return DEFAULT_ATTACHMENT_MODE
    mode = value.strip().lower().replace("_", "-")
    if not mode:
        return DEFAULT_ATTACHMENT_MODE
    if mode not in VALID_ATTACHMENT_MODES:
        raise ValueError(f"invalid attachment mode: {value}")
    return mode


def normalize_attachment_retention_days(value: str | None) -> float | None:
    """Return an optional attachment retention window in days.

    Empty values and zero disable automatic cleanup. Negative values are invalid.
    """
    if value is None:
        return None
    raw_value = value.strip().lower()
    if not raw_value or raw_value in {"0", "false", "off", "none", "disabled"}:
        return None
    try:
        days = float(raw_value)
    except ValueError:
        raise ValueError(f"invalid attachment retention days: {value}") from None
    if not isfinite(days) or days < 0:
        raise ValueError(f"invalid attachment retention days: {value}")
    if days == 0:
        return None
    return days


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "attachment"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name[:120] or "attachment"


def unique_attachment_path(base_dir: Path, chat_id: int, filename: str) -> Path:
    ensure_owner_only_dir(base_dir)
    chat_dir = base_dir / str(chat_id)
    ensure_owner_only_dir(chat_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return chat_dir / f"{stamp}-{uuid.uuid4().hex[:8]}-{safe_filename(filename)}"


def copy_attachment_to_project(
    source: Path, project_dir: str | Path, chat_id: int
) -> Path:
    """Copy a downloaded attachment into the project workspace with 0600 mode."""
    symlink = rejectable_symlink_path_component(source)
    if symlink:
        raise OSError(f"{symlink} is a symlink")
    target = unique_attachment_path(
        Path(project_dir) / PROJECT_ATTACHMENT_DIRNAME,
        chat_id,
        source.name,
    )
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW_FLAG, 0o600)
    created_stat = os.fstat(fd)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with (
            open_rejecting_symlink_read_bytes(source) as src,
            os.fdopen(fd, "wb") as dst,
        ):
            fd = -1
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
            _raise_if_path_replaced(target, dst.fileno())
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        _unlink_created_file(target, created_stat)
        raise
    return target


def prune_attachment_tree(
    root: Path,
    *,
    older_than_seconds: float | None,
    dry_run: bool = False,
    now: float | None = None,
) -> AttachmentPruneResult:
    """Delete attachment files below root that are older than the retention window."""
    root = root.expanduser()
    symlink = rejectable_symlink_path_component(root)
    if symlink:
        return AttachmentPruneResult(
            root=root,
            root_exists=root.exists() or root.is_symlink(),
            files=0,
            byte_count=0,
            dirs_removed=0,
            errors=(f"{symlink}: symlink root skipped",),
            dry_run=dry_run,
        )

    errors: list[str] = []
    if not root.exists():
        return AttachmentPruneResult(
            root=root,
            root_exists=False,
            files=0,
            byte_count=0,
            dirs_removed=0,
            dry_run=dry_run,
        )

    try:
        root_info = root.lstat()
    except OSError as exc:
        return AttachmentPruneResult(
            root=root,
            root_exists=True,
            files=0,
            byte_count=0,
            dirs_removed=0,
            errors=(f"{root}: {exc}",),
            dry_run=dry_run,
        )
    if not stat.S_ISDIR(root_info.st_mode):
        return AttachmentPruneResult(
            root=root,
            root_exists=True,
            files=0,
            byte_count=0,
            dirs_removed=0,
            errors=(f"{root}: not a directory",),
            dry_run=dry_run,
        )

    cutoff = None
    if older_than_seconds is not None:
        cutoff = (time.time() if now is None else now) - older_than_seconds

    files = 0
    byte_count = 0
    for path in root.rglob("*"):
        try:
            info = path.lstat()
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"{path}: symlink skipped")
            continue
        if stat.S_ISDIR(info.st_mode):
            continue
        if cutoff is not None and info.st_mtime > cutoff:
            continue

        if dry_run:
            files += 1
            byte_count += info.st_size
            continue
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"{path}: {exc}")
        else:
            files += 1
            byte_count += info.st_size

    dirs_removed = 0
    if not dry_run:
        dirs = []
        for path in root.rglob("*"):
            try:
                info = path.lstat()
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                dirs.append(path)
        for directory in sorted(dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                continue
            dirs_removed += 1

    return AttachmentPruneResult(
        root=root,
        root_exists=True,
        files=files,
        byte_count=byte_count,
        dirs_removed=dirs_removed,
        errors=tuple(errors),
        dry_run=dry_run,
    )
