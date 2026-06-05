"""Owner-only local file helpers."""

import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, TextIO

_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK_FLAG = getattr(os, "O_NONBLOCK", 0)


def rejectable_symlink_path_component(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if not candidate.is_symlink():
            continue
        try:
            is_user_owned = candidate.lstat().st_uid == os.getuid()
            is_in_user_writable_parent = os.access(candidate.parent, os.W_OK)
        except OSError:
            return candidate
        if is_user_owned or is_in_user_writable_parent:
            return candidate
    return None


def _rejectable_symlink_path_component(path: Path) -> Path | None:
    return rejectable_symlink_path_component(path)


def _raise_if_symlink_path(path: Path) -> None:
    symlink = rejectable_symlink_path_component(path)
    if symlink:
        raise OSError(f"{symlink} is a symlink")


def _missing_directory_chain(path: Path) -> list[Path]:
    missing: list[Path] = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return list(reversed(missing))


def _create_owner_only_dir(path: Path) -> None:
    _raise_if_symlink_path(path)
    with suppress(FileExistsError):
        os.mkdir(path, 0o700)
    _raise_if_symlink_path(path)
    if not path.is_dir():
        raise FileExistsError(f"{path} exists and is not a directory")
    with suppress(OSError):
        path.chmod(0o700)


def ensure_owner_only_dir(path: Path) -> None:
    _raise_if_symlink_path(path)
    for directory in _missing_directory_chain(path):
        _create_owner_only_dir(directory)
    _raise_if_symlink_path(path)
    if not path.is_dir():
        raise FileExistsError(f"{path} exists and is not a directory")
    with suppress(OSError):
        path.chmod(0o700)


def ensure_safe_dir(path: Path) -> None:
    _raise_if_symlink_path(path)
    path.mkdir(parents=True, exist_ok=True)
    _raise_if_symlink_path(path)


def _prepare_parent_dir(path: Path, *, owner_only_parent: bool) -> None:
    if owner_only_parent:
        ensure_owner_only_dir(path.parent)
        return
    ensure_safe_dir(path.parent)


def _raise_if_unexpected_path_type(
    path: Path, path_info: os.stat_result, *, expected: str
) -> None:
    if expected == "file" and not stat.S_ISREG(path_info.st_mode):
        raise OSError(f"{path} is not a regular file")
    if expected == "dir" and not stat.S_ISDIR(path_info.st_mode):
        raise OSError(f"{path} is not a directory")


def _set_owner_only_path(path: Path, mode: int, *, expected: str) -> bool:
    fd: int | None = None
    try:
        fd = _open_rejecting_symlink_fd(path, expected=expected)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        else:
            path.chmod(mode)
        _raise_if_path_replaced(path, fd)
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)


def set_owner_only_file(path: Path) -> bool:
    return _set_owner_only_path(path, 0o600, expected="file")


def set_owner_only_dir(path: Path) -> bool:
    return _set_owner_only_path(path, 0o700, expected="dir")


def _exclusive_owner_only_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    return flags | _NOFOLLOW_FLAG


def _set_owner_only_fd(fd: int) -> bool:
    if not hasattr(os, "fchmod"):
        return True
    try:
        os.fchmod(fd, 0o600)
        return True
    except OSError:
        return False


def _unlink_created_file(path: Path, created_stat: os.stat_result) -> None:
    try:
        current_stat = path.lstat()
    except OSError:
        return
    if (
        current_stat.st_dev == created_stat.st_dev
        and current_stat.st_ino == created_stat.st_ino
    ):
        path.unlink(missing_ok=True)


def _raise_if_path_replaced(path: Path, fd: int) -> None:
    path_info = path.lstat()
    opened_info = os.fstat(fd)
    if opened_info.st_dev != path_info.st_dev or opened_info.st_ino != path_info.st_ino:
        raise OSError(f"{path} changed while opening")


def write_owner_only_text(
    path: Path,
    content: str,
    *,
    exclusive: bool = False,
    owner_only_parent: bool = True,
) -> bool:
    _prepare_parent_dir(path, owner_only_parent=owner_only_parent)
    _raise_if_symlink_path(path)
    if not exclusive:
        return replace_owner_only_text(
            path, content, owner_only_parent=owner_only_parent
        )
    fd = os.open(path, _exclusive_owner_only_flags(), 0o600)
    created_stat = os.fstat(fd)
    permissions_ok = _set_owner_only_fd(fd)
    try:
        _raise_if_path_replaced(path, fd)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            _raise_if_path_replaced(path, f.fileno())
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        _unlink_created_file(path, created_stat)
        raise
    return permissions_ok


def write_owner_only_bytes(
    path: Path,
    content: bytes,
    *,
    exclusive: bool = False,
    owner_only_parent: bool = True,
) -> bool:
    _prepare_parent_dir(path, owner_only_parent=owner_only_parent)
    _raise_if_symlink_path(path)
    if not exclusive:
        return replace_owner_only_bytes(
            path, content, owner_only_parent=owner_only_parent
        )
    fd = os.open(path, _exclusive_owner_only_flags(), 0o600)
    created_stat = os.fstat(fd)
    permissions_ok = _set_owner_only_fd(fd)
    try:
        _raise_if_path_replaced(path, fd)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            _raise_if_path_replaced(path, f.fileno())
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        _unlink_created_file(path, created_stat)
        raise
    return permissions_ok


def replace_owner_only_text(
    path: Path, content: str, *, owner_only_parent: bool = True
) -> bool:
    _prepare_parent_dir(path, owner_only_parent=owner_only_parent)
    _raise_if_symlink_path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    permissions_ok = _set_owner_only_fd(fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            _raise_if_path_replaced(tmp, f.fileno())
        os.replace(tmp, path)
        return permissions_ok
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


def replace_owner_only_bytes(
    path: Path, content: bytes, *, owner_only_parent: bool = True
) -> bool:
    _prepare_parent_dir(path, owner_only_parent=owner_only_parent)
    _raise_if_symlink_path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    permissions_ok = _set_owner_only_fd(fd)
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            _raise_if_path_replaced(tmp, f.fileno())
        os.replace(tmp, path)
        return permissions_ok
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


def _open_rejecting_symlink_fd(path: Path, *, expected: str = "file") -> int:
    _raise_if_symlink_path(path)
    path_info = path.lstat()
    _raise_if_unexpected_path_type(path, path_info, expected=expected)
    flags = os.O_RDONLY | _NOFOLLOW_FLAG | _NONBLOCK_FLAG
    fd = os.open(path, flags)
    try:
        opened_info = os.fstat(fd)
        _raise_if_unexpected_path_type(path, opened_info, expected=expected)
        if (
            opened_info.st_dev != path_info.st_dev
            or opened_info.st_ino != path_info.st_ino
        ):
            raise OSError(f"{path} changed while opening")
        _raise_if_symlink_path(path)
        return fd
    except Exception:
        with suppress(OSError):
            os.close(fd)
        raise


def open_rejecting_symlink_read(
    path: Path,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
) -> TextIO:
    fd = _open_rejecting_symlink_fd(path)
    try:
        return os.fdopen(fd, "r", encoding=encoding, errors=errors)
    except Exception:
        with suppress(OSError):
            os.close(fd)
        raise


def open_rejecting_symlink_read_bytes(path: Path) -> BinaryIO:
    fd = _open_rejecting_symlink_fd(path)
    try:
        return os.fdopen(fd, "rb")
    except Exception:
        with suppress(OSError):
            os.close(fd)
        raise


def open_owner_only_append(path: Path) -> TextIO:
    ensure_owner_only_dir(path.parent)
    _raise_if_symlink_path(path)
    try:
        existing_path_info = path.lstat()
    except FileNotFoundError:
        path_info = None
    else:
        _raise_if_unexpected_path_type(path, existing_path_info, expected="file")
        path_info = existing_path_info
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _NOFOLLOW_FLAG | _NONBLOCK_FLAG
    fd = os.open(path, flags, 0o600)
    try:
        opened_info = os.fstat(fd)
        _raise_if_unexpected_path_type(path, opened_info, expected="file")
        if path_info is not None and (
            opened_info.st_dev != path_info.st_dev
            or opened_info.st_ino != path_info.st_ino
        ):
            raise OSError(f"{path} changed while opening")
        _raise_if_path_replaced(path, fd)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            path.chmod(0o600)
        _raise_if_path_replaced(path, fd)
        return os.fdopen(fd, "a", encoding="utf-8")
    except Exception:
        with suppress(OSError):
            os.close(fd)
        raise
