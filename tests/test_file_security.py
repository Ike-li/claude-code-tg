"""Direct tests for owner-only local file helpers."""

import os
from pathlib import Path

import pytest

from claude_code_tg import file_security


def _patch_fdopen_to_fail_write(monkeypatch, expected_mode: str) -> list[int]:
    close_calls: list[int] = []
    original_fdopen = os.fdopen
    original_close = os.close

    class FailingWriter:
        def __init__(self, fd):
            self.fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            close_calls.append(self.fd)
            original_close(self.fd)

        def write(self, _content):
            raise OSError("write failed")

    def fail_write(fd, mode="r", *args, **kwargs):
        if mode == expected_mode:
            return FailingWriter(fd)
        return original_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(file_security.os, "fdopen", fail_write)
    return close_calls


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_ensure_owner_only_dir_creates_private_directory(tmp_path):
    target = tmp_path / "runtime" / "instance"

    file_security.ensure_owner_only_dir(target)

    assert target.is_dir()
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_ensure_owner_only_dir_creates_missing_chain_private(tmp_path):
    old_umask = os.umask(0o022)
    try:
        target = tmp_path / "runtime" / "nested" / "instance"

        file_security.ensure_owner_only_dir(target)
    finally:
        os.umask(old_umask)

    assert (tmp_path / "runtime").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "runtime" / "nested").stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_ensure_owner_only_dir_does_not_chmod_existing_parent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project.chmod(0o755)
    target = project / ".tgcc-attachments" / "chat"

    file_security.ensure_owner_only_dir(target)

    assert project.stat().st_mode & 0o777 == 0o755
    assert (project / ".tgcc-attachments").stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o700


def test_rejectable_symlink_path_component_treats_lstat_error_as_rejectable(
    monkeypatch, tmp_path
):
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    original_is_symlink = Path.is_symlink
    original_lstat = Path.lstat

    def fake_is_symlink(path):
        if path == link:
            return True
        return original_is_symlink(path)

    def flaky_lstat(path):
        if path == link:
            raise OSError("race")
        return original_lstat(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    monkeypatch.setattr(Path, "lstat", flaky_lstat)

    assert file_security.rejectable_symlink_path_component(link) == link


def test_rejectable_symlink_alias_delegates(tmp_path):
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert file_security._rejectable_symlink_path_component(link) == link


def test_set_owner_only_file_returns_false_for_symlink(tmp_path):
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert file_security.set_owner_only_file(link) is False
    assert target.read_text(encoding="utf-8") == "secret"


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_set_owner_only_file_uses_fd_chmod(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    chmod_calls: list[int] = []
    original_fchmod = os.fchmod

    def record_fchmod(fd, mode):
        chmod_calls.append(mode)
        original_fchmod(fd, mode)

    def fail_path_chmod(_path, _mode):
        raise AssertionError("owner-only file updates should chmod by fd")

    monkeypatch.setattr(file_security.os, "fchmod", record_fchmod)
    monkeypatch.setattr(Path, "chmod", fail_path_chmod)

    assert file_security.set_owner_only_file(target) is True

    assert chmod_calls == [0o600]
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_set_owner_only_dir_uses_fd_chmod(monkeypatch, tmp_path):
    target = tmp_path / "runtime"
    target.mkdir()
    target.chmod(0o755)
    chmod_calls: list[int] = []
    original_fchmod = os.fchmod

    def record_fchmod(fd, mode):
        chmod_calls.append(mode)
        original_fchmod(fd, mode)

    def fail_path_chmod(_path, _mode):
        raise AssertionError("owner-only directory updates should chmod by fd")

    monkeypatch.setattr(file_security.os, "fchmod", record_fchmod)
    monkeypatch.setattr(Path, "chmod", fail_path_chmod)

    assert file_security.set_owner_only_dir(target) is True

    assert chmod_calls == [0o700]
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_set_owner_only_file_rejects_directory_without_chmod(tmp_path):
    target = tmp_path / "tgcc.log"
    target.mkdir()
    target.chmod(0o700)

    assert file_security.set_owner_only_file(target) is False

    assert target.is_dir()
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_set_owner_only_dir_rejects_regular_file_without_chmod(tmp_path):
    target = tmp_path / "runtime"
    target.write_text("not a directory\n", encoding="utf-8")
    target.chmod(0o644)

    assert file_security.set_owner_only_dir(target) is False

    assert target.is_file()
    assert target.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_set_owner_only_file_rejects_path_replaced_after_open(monkeypatch, tmp_path):
    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    target.write_text("secret", encoding="utf-8")
    replacement.write_text("replacement", encoding="utf-8")
    replacement.chmod(0o644)
    original_fchmod = os.fchmod
    swapped = False

    def swap_path_during_fchmod(fd, mode):
        nonlocal swapped
        if not swapped:
            replacement.replace(target)
            swapped = True
        original_fchmod(fd, mode)

    monkeypatch.setattr(file_security.os, "fchmod", swap_path_during_fchmod)

    assert file_security.set_owner_only_file(target) is False

    assert swapped
    assert target.read_text(encoding="utf-8") == "replacement"
    assert target.stat().st_mode & 0o777 == 0o644


def test_set_owner_only_file_returns_false_on_chmod_error(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")

    def fail_chmod(self, mode):
        raise OSError("chmod failed")

    monkeypatch.delattr(file_security.os, "fchmod", raising=False)
    monkeypatch.setattr(Path, "chmod", fail_chmod)

    assert file_security.set_owner_only_file(target) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_write_owner_only_bytes_exclusive_creates_private_file(tmp_path):
    target = tmp_path / "attachments" / "doc.bin"

    assert file_security.write_owner_only_bytes(target, b"payload", exclusive=True)

    assert target.read_bytes() == b"payload"
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_write_owner_only_text_exclusive_uses_fd_chmod(monkeypatch, tmp_path):
    target = tmp_path / "bot.env"
    chmod_calls: list[int] = []
    original_fchmod = os.fchmod

    def record_fchmod(fd, mode):
        chmod_calls.append(mode)
        original_fchmod(fd, mode)

    def fail_path_chmod(_path):
        raise AssertionError("exclusive writes should not chmod by path")

    monkeypatch.setattr(file_security.os, "fchmod", record_fchmod)
    monkeypatch.setattr(file_security, "set_owner_only_file", fail_path_chmod)

    assert file_security.write_owner_only_text(target, "TOKEN=value\n", exclusive=True)

    assert chmod_calls == [0o600]
    assert target.read_text(encoding="utf-8") == "TOKEN=value\n"
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_write_owner_only_text_exclusive_rejects_path_replaced_after_open(
    monkeypatch, tmp_path
):
    target = tmp_path / "bot.env"
    replacement = tmp_path / "replacement.env"
    replacement.write_text("REPLACEMENT=1\n", encoding="utf-8")
    close_calls: list[int] = []
    original_fchmod = os.fchmod
    original_close = os.close
    swapped = False

    def swap_path_during_fchmod(fd, mode):
        nonlocal swapped
        if not swapped:
            replacement.replace(target)
            swapped = True
        original_fchmod(fd, mode)

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security.os, "fchmod", swap_path_during_fchmod)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="changed while opening"):
        file_security.write_owner_only_text(target, "TOKEN=value\n", exclusive=True)

    assert swapped
    assert close_calls
    assert target.read_text(encoding="utf-8") == "REPLACEMENT=1\n"


def test_write_owner_only_text_exclusive_rejects_existing(tmp_path):
    """Exclusive writes preserve an existing file instead of racing overwrite."""
    target = tmp_path / "bot.env"
    target.write_text("ORIGINAL=1", encoding="utf-8")

    with pytest.raises(FileExistsError):
        file_security.write_owner_only_text(target, "NEW=1", exclusive=True)

    assert target.read_text(encoding="utf-8") == "ORIGINAL=1"


@pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"),
    reason="symlink no-follow is unavailable on this platform",
)
def test_write_owner_only_text_force_rejects_symlink(tmp_path):
    """Forced env writes should not follow a symlink to another local file."""
    target = tmp_path / "outside.env"
    target.write_text("ORIGINAL=1", encoding="utf-8")
    link = tmp_path / "bot.env"
    link.symlink_to(target)

    with pytest.raises(OSError):
        file_security.write_owner_only_text(
            link, "TELEGRAM_BOT_TOKEN=secret\n", exclusive=False
        )

    assert target.read_text(encoding="utf-8") == "ORIGINAL=1"


def test_write_owner_only_text_force_replaces_atomically(monkeypatch, tmp_path):
    """Forced env writes should leave the old file intact until replace succeeds."""
    target = tmp_path / "bot.env"
    target.write_text("ORIGINAL=1", encoding="utf-8")
    target.chmod(0o644)

    def fail_replace(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(file_security.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        file_security.write_owner_only_text(
            target,
            "TELEGRAM_BOT_TOKEN=secret\n",
            exclusive=False,
        )

    assert target.read_text(encoding="utf-8") == "ORIGINAL=1"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_write_owner_only_text_rejects_symlink_parent(tmp_path):
    """Env writes should not create files through a symlinked parent directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.write_owner_only_text(
            link_dir / "bot.env", "TELEGRAM_BOT_TOKEN=secret\n"
        )

    assert not (outside / "bot.env").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_write_owner_only_text_rejects_symlink_ancestor(tmp_path):
    """Env writes should not create nested files through a symlinked ancestor."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.write_owner_only_text(
            link_dir / "nested" / "bot.env",
            "TELEGRAM_BOT_TOKEN=secret\n",
        )

    assert not (outside / "nested").exists()


def test_write_owner_only_bytes_exclusive_rejects_existing(tmp_path):
    target = tmp_path / "doc.bin"
    target.write_bytes(b"original")

    with pytest.raises(FileExistsError):
        file_security.write_owner_only_bytes(target, b"new", exclusive=True)

    assert target.read_bytes() == b"original"


@pytest.mark.parametrize(
    ("target_name", "writer", "content", "mode"),
    [
        ("bot.env", file_security.write_owner_only_text, "TOKEN=secret\n", "w"),
        ("doc.bin", file_security.write_owner_only_bytes, b"payload", "wb"),
    ],
)
def test_write_owner_only_exclusive_removes_new_file_on_write_error(
    monkeypatch, tmp_path, target_name, writer, content, mode
):
    target = tmp_path / target_name
    close_calls = _patch_fdopen_to_fail_write(monkeypatch, mode)

    with pytest.raises(OSError, match="write failed"):
        writer(target, content, exclusive=True)

    assert close_calls
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="open-file replacement semantics differ")
def test_write_owner_only_exclusive_does_not_remove_replaced_path_on_error(
    monkeypatch, tmp_path
):
    target = tmp_path / "bot.env"
    original_fdopen = os.fdopen
    original_close = os.close

    class ReplacingWriter:
        def __init__(self, fd):
            self.fd = fd

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            original_close(self.fd)

        def write(self, _content):
            target.unlink()
            target.write_text("REPLACEMENT=1\n", encoding="utf-8")
            raise OSError("write failed")

    def replace_path_before_failing(fd, mode="r", *args, **kwargs):
        if mode == "w":
            return ReplacingWriter(fd)
        return original_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(file_security.os, "fdopen", replace_path_before_failing)

    with pytest.raises(OSError, match="write failed"):
        file_security.write_owner_only_text(target, "TOKEN=secret\n", exclusive=True)

    assert target.read_text(encoding="utf-8") == "REPLACEMENT=1\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_write_owner_only_bytes_replace_creates_private_file(tmp_path):
    target = tmp_path / "attachments" / "doc.bin"

    assert file_security.write_owner_only_bytes(target, b"payload")

    assert target.read_bytes() == b"payload"
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
@pytest.mark.parametrize(
    ("target_name", "writer", "content", "reader"),
    [
        (
            "status.json",
            file_security.replace_owner_only_text,
            "{}",
            lambda path: path.read_text(encoding="utf-8"),
        ),
        (
            "doc.bin",
            file_security.replace_owner_only_bytes,
            b"payload",
            lambda path: path.read_bytes(),
        ),
    ],
)
def test_replace_owner_only_uses_fd_chmod_before_replace(
    monkeypatch, tmp_path, target_name, writer, content, reader
):
    target = tmp_path / target_name
    chmod_calls: list[int] = []
    original_fchmod = os.fchmod

    def record_fchmod(fd, mode):
        chmod_calls.append(mode)
        original_fchmod(fd, mode)

    def fail_path_chmod(_path):
        raise AssertionError("replacement writes should not chmod by path")

    monkeypatch.setattr(file_security.os, "fchmod", record_fchmod)
    monkeypatch.setattr(file_security, "set_owner_only_file", fail_path_chmod)

    assert writer(target, content) is True

    assert chmod_calls == [0o600]
    assert reader(target) == content
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="owner-only modes are POSIX-only")
def test_replace_owner_only_text_creates_owner_only_status_file(tmp_path):
    status_file = tmp_path / "nested" / "status.json"

    file_security.replace_owner_only_text(status_file, '{"sessions": 1}')

    assert status_file.read_text(encoding="utf-8") == '{"sessions": 1}'
    assert status_file.parent.stat().st_mode & 0o777 == 0o700
    assert status_file.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "nested" / "status.tmp").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_replace_owner_only_text_rejects_symlink_parent(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.replace_owner_only_text(
            link_dir / "status.json", '{"sessions": 1}'
        )

    assert not (outside / "status.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="open-file replacement semantics differ")
@pytest.mark.parametrize(
    ("target_name", "writer", "original", "content", "read_current"),
    [
        (
            "status.json",
            file_security.replace_owner_only_text,
            "OLD\n",
            "{}",
            lambda path: path.read_text(encoding="utf-8"),
        ),
        (
            "doc.bin",
            file_security.replace_owner_only_bytes,
            b"original",
            b"new",
            lambda path: path.read_bytes(),
        ),
    ],
)
def test_replace_owner_only_rejects_tmp_path_replaced_before_rename(
    monkeypatch, tmp_path, target_name, writer, original, content, read_current
):
    target = tmp_path / target_name
    if isinstance(original, bytes):
        target.write_bytes(original)
    else:
        target.write_text(original, encoding="utf-8")
    swapped = False

    def swap_tmp_before_replace(_fd):
        nonlocal swapped
        if swapped:
            return
        matches = list(tmp_path.glob(f".{target.name}.*.tmp"))
        assert len(matches) == 1
        tmp_file = matches[0]
        tmp_file.unlink()
        if isinstance(original, bytes):
            tmp_file.write_bytes(b"replacement")
        else:
            tmp_file.write_text("REPLACEMENT\n", encoding="utf-8")
        swapped = True

    monkeypatch.setattr(file_security.os, "fsync", swap_tmp_before_replace)

    with pytest.raises(OSError, match="changed while opening"):
        writer(target, content)

    assert swapped
    assert read_current(target) == original
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_replace_owner_only_bytes_leaves_original_when_replace_fails(
    monkeypatch, tmp_path
):
    target = tmp_path / "doc.bin"
    target.write_bytes(b"original")

    def fail_replace(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(file_security.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        file_security.replace_owner_only_bytes(target, b"new")

    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_replace_owner_only_text_closes_fd_and_removes_tmp_on_fdopen_error(
    monkeypatch, tmp_path
):
    target = tmp_path / "status.json"
    close_calls: list[int] = []
    original_close = os.close

    def fail_fdopen(_fd, *_args, **_kwargs):
        raise OSError("fdopen failed")

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security.os, "fdopen", fail_fdopen)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="fdopen failed"):
        file_security.replace_owner_only_text(target, "{}")

    assert close_calls
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_replace_owner_only_bytes_closes_fd_and_removes_tmp_on_fdopen_error(
    monkeypatch, tmp_path
):
    target = tmp_path / "doc.bin"
    close_calls: list[int] = []
    original_close = os.close

    def fail_fdopen(_fd, *_args, **_kwargs):
        raise OSError("fdopen failed")

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security.os, "fdopen", fail_fdopen)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="fdopen failed"):
        file_security.replace_owner_only_bytes(target, b"payload")

    assert close_calls
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_open_rejecting_symlink_read_closes_fd_if_post_open_check_fails(
    monkeypatch, tmp_path
):
    target = tmp_path / "runtime.log"
    target.write_text("line\n", encoding="utf-8")
    close_calls: list[int] = []
    original_close = os.close
    calls = 0

    def fail_after_open(_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("post-open check failed")

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security, "_raise_if_symlink_path", fail_after_open)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="post-open check failed"):
        file_security.open_rejecting_symlink_read(target)

    assert close_calls


def test_open_rejecting_symlink_read_reads_regular_file(tmp_path):
    """Runtime readers should share the hardened text-open helper."""
    target = tmp_path / "tgcc.log"
    target.write_text("line\n", encoding="utf-8")

    with file_security.open_rejecting_symlink_read(target) as f:
        assert f.read() == "line\n"


def test_open_rejecting_symlink_read_rejects_directory(tmp_path):
    target = tmp_path / "tgcc.log"
    target.mkdir()

    with pytest.raises(OSError, match="not a regular file"):
        file_security.open_rejecting_symlink_read(target)


@pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"),
    reason="symlink no-follow is unavailable on this platform",
)
def test_open_rejecting_symlink_read_rejects_symlink(tmp_path):
    """Runtime reads should not follow a symlinked file path."""
    target = tmp_path / "outside.log"
    target.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "tgcc.log"
    link.symlink_to(target)

    with pytest.raises(OSError):
        file_security.open_rejecting_symlink_read(link)

    assert target.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_open_rejecting_symlink_read_rejects_symlink_parent(tmp_path):
    """Runtime reads should reject symlinked parent directories too."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tgcc.log").write_text("outside\n", encoding="utf-8")
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.open_rejecting_symlink_read(link_dir / "tgcc.log")


def test_open_rejecting_symlink_read_rejects_path_replaced_before_open(
    monkeypatch, tmp_path
):
    target = tmp_path / "runtime.log"
    target.write_text("old\n", encoding="utf-8")
    replacement = tmp_path / "replacement.log"
    replacement.write_text("new\n", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swapping_open(path, flags, mode=0o777):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            replacement.replace(target)
        return original_open(path, flags, mode)

    monkeypatch.setattr(file_security.os, "open", swapping_open)

    with pytest.raises(OSError, match="changed while opening"):
        file_security.open_rejecting_symlink_read(target)

    assert swapped
    assert target.read_text(encoding="utf-8") == "new\n"


def test_open_rejecting_symlink_read_bytes_reads_binary_content(tmp_path):
    target = tmp_path / "attachment.bin"
    target.write_bytes(b"\x00payload")

    with file_security.open_rejecting_symlink_read_bytes(target) as f:
        assert f.read() == b"\x00payload"


def test_open_rejecting_symlink_read_bytes_closes_fd_if_post_open_check_fails(
    monkeypatch, tmp_path
):
    target = tmp_path / "attachment.bin"
    target.write_bytes(b"payload")
    close_calls: list[int] = []
    original_close = os.close
    calls = 0

    def fail_after_open(_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("post-open check failed")

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security, "_raise_if_symlink_path", fail_after_open)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="post-open check failed"):
        file_security.open_rejecting_symlink_read_bytes(target)

    assert close_calls


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_open_owner_only_append_creates_parent_and_private_file(tmp_path):
    logfile = tmp_path / "runtime" / "tgcc.log"

    with file_security.open_owner_only_append(logfile) as f:
        f.write("line\n")

    assert logfile.read_text(encoding="utf-8") == "line\n"
    assert logfile.parent.stat().st_mode & 0o777 == 0o700
    assert logfile.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_open_owner_only_append_rejects_existing_directory(tmp_path):
    logfile = tmp_path / "runtime" / "tgcc.log"
    logfile.mkdir(parents=True)
    logfile.chmod(0o700)

    with pytest.raises(OSError, match="not a regular file"):
        file_security.open_owner_only_append(logfile)

    assert logfile.is_dir()
    assert logfile.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"),
    reason="symlink no-follow is unavailable on this platform",
)
def test_open_owner_only_append_rejects_symlink(tmp_path):
    """Runtime logs should not append through a symlinked log path."""
    target = tmp_path / "outside.log"
    target.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "tgcc.log"
    link.symlink_to(target)

    with pytest.raises(OSError):
        file_security.open_owner_only_append(link)

    assert target.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_open_owner_only_append_rejects_symlink_without_nofollow(
    monkeypatch,
    tmp_path,
):
    """Runtime log appends should reject symlinks even without O_NOFOLLOW."""
    target = tmp_path / "outside.log"
    target.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "tgcc.log"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(file_security, "_NOFOLLOW_FLAG", 0)

    with pytest.raises(OSError):
        file_security.open_owner_only_append(link)

    assert target.read_text(encoding="utf-8") == "outside\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_open_owner_only_append_rejects_symlink_parent(tmp_path):
    """Runtime logs should not be created through a symlinked instance directory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.open_owner_only_append(link_dir / "tgcc.log")

    assert not (outside / "tgcc.log").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_open_owner_only_append_rejects_symlink_ancestor(tmp_path):
    """Runtime logs should not create nested files through a symlinked ancestor."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "linked"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        file_security.open_owner_only_append(link_dir / "nested" / "tgcc.log")

    assert not (outside / "nested").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_open_owner_only_append_tightens_existing_public_file(tmp_path):
    logfile = tmp_path / "runtime" / "tgcc.log"
    logfile.parent.mkdir()
    logfile.write_text("old\n", encoding="utf-8")
    logfile.chmod(0o644)

    with file_security.open_owner_only_append(logfile) as f:
        assert logfile.stat().st_mode & 0o777 == 0o600
        f.write("new\n")

    assert logfile.read_text(encoding="utf-8") == "old\nnew\n"
    assert logfile.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_open_owner_only_append_closes_fd_when_owner_only_mode_fails(
    monkeypatch,
    tmp_path,
):
    logfile = tmp_path / "runtime" / "tgcc.log"
    close_calls: list[int] = []
    original_close = os.close

    def fail_fchmod(_fd, _mode):
        raise OSError("fchmod failed")

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security.os, "fchmod", fail_fchmod)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="fchmod failed"):
        file_security.open_owner_only_append(logfile)

    assert close_calls


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_open_owner_only_append_rejects_path_replaced_after_open(
    monkeypatch,
    tmp_path,
):
    logfile = tmp_path / "runtime" / "tgcc.log"
    logfile.parent.mkdir()
    logfile.write_text("old\n", encoding="utf-8")
    replacement = tmp_path / "replacement.log"
    replacement.write_text("replacement\n", encoding="utf-8")
    close_calls: list[int] = []
    original_fchmod = os.fchmod
    original_close = os.close
    swapped = False

    def swap_path_during_fchmod(fd, mode):
        nonlocal swapped
        if not swapped:
            replacement.replace(logfile)
            swapped = True
        original_fchmod(fd, mode)

    def record_close(fd):
        close_calls.append(fd)
        original_close(fd)

    monkeypatch.setattr(file_security.os, "fchmod", swap_path_during_fchmod)
    monkeypatch.setattr(file_security.os, "close", record_close)

    with pytest.raises(OSError, match="changed while opening"):
        file_security.open_owner_only_append(logfile)

    assert swapped
    assert close_calls
    assert logfile.read_text(encoding="utf-8") == "replacement\n"
