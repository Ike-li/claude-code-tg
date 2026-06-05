import os
from pathlib import Path

import pytest

import claude_code_tg.attachments as attachments_module
from claude_code_tg.attachments import (
    PROJECT_ATTACHMENT_DIRNAME,
    copy_attachment_to_project,
    normalize_attachment_mode,
    normalize_attachment_retention_days,
    prune_attachment_tree,
    safe_filename,
    unique_attachment_path,
)


def test_normalize_attachment_mode_accepts_defaults_and_aliases():
    assert normalize_attachment_mode(None) == "path"
    assert normalize_attachment_mode("") == "path"
    assert normalize_attachment_mode(" COPY_TO_PROJECT ") == "copy-to-project"
    assert normalize_attachment_mode("reject") == "reject"


def test_normalize_attachment_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        normalize_attachment_mode("download")


def test_normalize_attachment_retention_days_accepts_disabled_values():
    assert normalize_attachment_retention_days(None) is None
    assert normalize_attachment_retention_days("") is None
    assert normalize_attachment_retention_days("0") is None
    assert normalize_attachment_retention_days("off") is None


def test_normalize_attachment_retention_days_accepts_positive_values():
    assert normalize_attachment_retention_days("30") == 30
    assert normalize_attachment_retention_days("0.5") == 0.5
    assert normalize_attachment_retention_days("0.0") is None


def test_safe_filename_strips_paths_and_unsafe_characters():
    assert safe_filename("../weird report?.txt") == "weird-report-.txt"
    assert safe_filename("...") == "attachment"
    assert safe_filename("x" * 200) == "x" * 120


def test_normalize_attachment_retention_days_rejects_invalid_values():
    with pytest.raises(ValueError):
        normalize_attachment_retention_days("soon")
    with pytest.raises(ValueError):
        normalize_attachment_retention_days("-1")
    with pytest.raises(ValueError):
        normalize_attachment_retention_days("nan")
    with pytest.raises(ValueError):
        normalize_attachment_retention_days("inf")


@pytest.mark.skipif(os.name == "nt", reason="owner-only modes are POSIX-only")
def test_unique_attachment_path_sets_root_and_chat_dir_owner_only(tmp_path):
    root = tmp_path / "attachments"

    target = unique_attachment_path(root, 111, "sample.txt")

    assert target.parent == root / "111"
    assert stat_mode(root) == 0o700
    assert stat_mode(target.parent) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_unique_attachment_path_rejects_symlink_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = tmp_path / "attachments"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        unique_attachment_path(link_dir, 111, "secret.txt")

    assert not (outside / "111").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_copy_attachment_to_project_rejects_symlink_cache_root(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("secret", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link_dir = project / PROJECT_ATTACHMENT_DIRNAME
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(OSError):
        copy_attachment_to_project(source, project, 111)

    assert not (outside / "111").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_copy_attachment_to_project_rejects_symlink_source(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    source = tmp_path / "source.txt"
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(OSError):
        copy_attachment_to_project(source, project, 111)

    assert not (project / PROJECT_ATTACHMENT_DIRNAME / "111").exists()
    assert outside.read_text(encoding="utf-8") == "secret"


@pytest.mark.skipif(os.name == "nt", reason="owner-only modes are POSIX-only")
def test_copy_attachment_to_project_copies_with_owner_only_mode(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("secret", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()

    target = copy_attachment_to_project(source, project, 111)

    assert target.read_text(encoding="utf-8") == "secret"
    assert target.parent.parent == project / PROJECT_ATTACHMENT_DIRNAME
    assert stat_mode(target.parent.parent) == 0o700
    assert stat_mode(target.parent) == 0o700
    assert stat_mode(target) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="fd-level chmod is POSIX-only")
def test_copy_attachment_to_project_sets_owner_only_mode_on_fd(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("secret", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    calls: list[tuple[int, int]] = []

    def fake_fchmod(fd: int, mode: int) -> None:
        calls.append((fd, mode))

    monkeypatch.setattr(attachments_module.os, "fchmod", fake_fchmod)

    target = copy_attachment_to_project(source, project, 111)

    assert target.read_text(encoding="utf-8") == "secret"
    assert calls
    assert calls[0][1] == 0o600


@pytest.mark.skipif(os.name == "nt", reason="inode replacement checks are POSIX-only")
def test_copy_attachment_to_project_rejects_target_replaced_after_open(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.txt"
    source.write_text("secret", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    target = project / PROJECT_ATTACHMENT_DIRNAME / "111" / "copied.txt"
    target.parent.mkdir(parents=True)
    target.parent.chmod(0o700)
    original_reader = attachments_module.open_rejecting_symlink_read_bytes

    def fixed_attachment_path(_base_dir: Path, _chat_id: int, _filename: str) -> Path:
        return target

    class ReplacingReader:
        def __init__(self, path: Path) -> None:
            self.path = path
            self.file = None

        def __enter__(self):
            target.unlink()
            target.write_text("replacement", encoding="utf-8")
            self.file = original_reader(self.path)
            return self.file.__enter__()

        def __exit__(self, exc_type, exc, tb):
            assert self.file is not None
            return self.file.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        attachments_module, "unique_attachment_path", fixed_attachment_path
    )
    monkeypatch.setattr(
        attachments_module, "open_rejecting_symlink_read_bytes", ReplacingReader
    )

    with pytest.raises(OSError, match="changed while opening"):
        copy_attachment_to_project(source, project, 111)

    assert target.read_text(encoding="utf-8") == "replacement"


def test_copy_attachment_to_project_removes_partial_file_when_source_read_fails(
    tmp_path,
):
    source = tmp_path / "missing.txt"
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(FileNotFoundError):
        copy_attachment_to_project(source, project, 111)

    cache_root = project / PROJECT_ATTACHMENT_DIRNAME
    assert list(cache_root.rglob("*")) == [cache_root / "111"]


@pytest.mark.skipif(os.name == "nt", reason="symlink directory checks are POSIX-only")
def test_prune_attachment_tree_skips_symlink_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    root = tmp_path / "attachments"
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    result = prune_attachment_tree(
        root,
        older_than_seconds=None,
    )

    assert result.files == 0
    assert result.errors
    assert "symlink root skipped" in result.errors[0]
    assert outside_file.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
def test_prune_attachment_tree_skips_symlink_entries(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    result = prune_attachment_tree(
        root,
        older_than_seconds=None,
    )

    assert result.files == 0
    assert result.errors
    assert "symlink skipped" in result.errors[0]
    assert link.is_symlink()
    assert outside.exists()


def test_prune_attachment_tree_deletes_old_files_and_empty_dirs(tmp_path):
    root = tmp_path / "attachments"
    old_dir = root / "111"
    new_dir = root / "222"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_file = old_dir / "old.txt"
    new_file = new_dir / "new.txt"
    old_file.write_text("old", encoding="utf-8")
    new_file.write_text("new", encoding="utf-8")
    os.utime(old_file, (100, 100))
    os.utime(new_file, (1_000, 1_000))

    result = prune_attachment_tree(
        root,
        older_than_seconds=100,
        now=1_000,
    )

    assert result.files == 1
    assert result.byte_count == 3
    assert result.dirs_removed == 1
    assert not old_file.exists()
    assert not old_dir.exists()
    assert new_file.exists()


def test_prune_attachment_tree_dry_run_preserves_files(tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    target = root / "old.txt"
    target.write_text("old", encoding="utf-8")
    os.utime(target, (100, 100))

    result = prune_attachment_tree(
        root,
        older_than_seconds=100,
        dry_run=True,
        now=1_000,
    )

    assert result.dry_run is True
    assert result.files == 1
    assert result.byte_count == 3
    assert target.exists()


def test_prune_attachment_tree_missing_root_is_noop(tmp_path):
    result = prune_attachment_tree(
        tmp_path / "missing",
        older_than_seconds=None,
    )

    assert result.root_exists is False
    assert result.files == 0
    assert result.errors == ()


def test_prune_attachment_tree_reports_root_lstat_errors(monkeypatch, tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    monkeypatch.setattr(
        "claude_code_tg.attachments.rejectable_symlink_path_component", lambda _: None
    )
    original_lstat = Path.lstat

    def lstat_with_error(path: Path):
        if path == root:
            raise OSError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat_with_error)

    result = prune_attachment_tree(root, older_than_seconds=None)

    assert result.root_exists is True
    assert result.files == 0
    assert "permission denied" in result.errors[0]


def test_prune_attachment_tree_reports_non_directory_root(tmp_path):
    root = tmp_path / "attachments.txt"
    root.write_text("not a directory", encoding="utf-8")

    result = prune_attachment_tree(root, older_than_seconds=None)

    assert result.root_exists is True
    assert result.files == 0
    assert "not a directory" in result.errors[0]


def test_prune_attachment_tree_records_child_lstat_errors(monkeypatch, tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    child = root / "old.txt"
    child.write_text("old", encoding="utf-8")
    original_lstat = Path.lstat

    def lstat_with_error(path: Path):
        if path == child:
            raise OSError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat_with_error)

    result = prune_attachment_tree(root, older_than_seconds=None)

    assert result.files == 0
    assert child.exists()
    assert "permission denied" in result.errors[0]


def test_prune_attachment_tree_records_unlink_errors(monkeypatch, tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    child = root / "old.txt"
    child.write_text("old", encoding="utf-8")

    def unlink_with_error(path: Path, *args, **kwargs):
        if path == child:
            raise OSError("read-only")
        return Path.unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_error)

    result = prune_attachment_tree(root, older_than_seconds=None)

    assert result.files == 0
    assert child.exists()
    assert "read-only" in result.errors[0]


def test_prune_attachment_tree_ignores_rmdir_errors(monkeypatch, tmp_path):
    root = tmp_path / "attachments"
    chat_dir = root / "111"
    chat_dir.mkdir(parents=True)
    child = chat_dir / "old.txt"
    child.write_text("old", encoding="utf-8")

    def rmdir_with_error(path: Path):
        if path == chat_dir:
            raise OSError("still busy")
        return Path.rmdir(path)

    monkeypatch.setattr(Path, "rmdir", rmdir_with_error)

    result = prune_attachment_tree(root, older_than_seconds=None)

    assert result.files == 1
    assert result.dirs_removed == 0
    assert chat_dir.exists()


def stat_mode(path):
    return path.stat().st_mode & 0o777
