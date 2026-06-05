"""Tests for local diagnostic helpers."""

import os
import stat
from pathlib import Path

import pytest

from claude_code_tg import diagnostics
from claude_code_tg.utils import parse_positive_ids


def test_parse_positive_ids_ignores_empty_items_and_reports_non_positive_values():
    ids, invalid = parse_positive_ids(" 123, ,0,-5,abc,456 ")

    assert ids == [123, 456]
    assert invalid == ["0", "-5", "abc"]


def test_env_permissions_windows_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.os, "name", "nt")

    result = diagnostics._check_env_permissions(tmp_path / "bot.env")

    assert result.status == "warn"
    assert "Windows" in result.detail


def test_env_permissions_reports_stat_errors(monkeypatch, tmp_path):
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=x\n", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics, "rejectable_symlink_path_component", lambda _: None
    )

    original_stat = Path.stat

    def stat_with_error(path: Path, *args, **kwargs):
        if path == env_file:
            raise OSError("permission denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_error)

    result = diagnostics._check_env_permissions(env_file)

    assert result.status == "warn"
    assert "could not inspect mode" in result.detail


def test_owner_only_problem_reports_stat_errors(tmp_path):
    result = diagnostics._owner_only_problem(tmp_path / "missing", 0o600)

    assert result is not None
    assert "could not inspect mode" in result


def test_owner_only_problem_reports_file_type_mismatch(tmp_path):
    runtime_file = tmp_path / "tgcc.log"
    runtime_file.mkdir()

    result = diagnostics._owner_only_problem(runtime_file, 0o600)

    assert result is not None
    assert "expected regular file" in result


def test_owner_only_problem_reports_directory_type_mismatch(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.write_text("not a directory\n", encoding="utf-8")

    result = diagnostics._owner_only_problem(runtime_dir, 0o700)

    assert result is not None
    assert "expected directory" in result


def test_owner_only_tree_targets_stops_at_symlinked_root(monkeypatch, tmp_path):
    root = tmp_path / "attachments"
    root.mkdir()
    (root / "secret.txt").write_text("secret\n", encoding="utf-8")
    monkeypatch.setattr(
        diagnostics, "rejectable_symlink_path_component", lambda path: path
    )

    assert diagnostics._owner_only_tree_targets(root) == [(root, 0o700)]


def test_owner_only_tree_targets_treats_uninspectable_child_as_file(
    monkeypatch, tmp_path
):
    root = tmp_path / "attachments"
    root.mkdir()
    child = root / "secret.txt"
    child.write_text("secret\n", encoding="utf-8")
    original_lstat = Path.lstat

    def lstat_with_error(path: Path):
        if path == child:
            raise OSError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat_with_error)

    assert (child, 0o600) in diagnostics._owner_only_tree_targets(root)


def test_project_attachment_root_handles_empty_absolute_and_relative_values(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    assert diagnostics._project_attachment_root({}) is None
    assert diagnostics._project_attachment_root(
        {"CLAUDE_PROJECT_DIR": str(project)}
    ) == (project / ".tgcc-attachments")
    assert diagnostics._project_attachment_root({"CLAUDE_PROJECT_DIR": "project"}) == (
        project / ".tgcc-attachments"
    )


def test_runtime_permission_targets_deduplicates_primary_and_legacy_dirs(
    monkeypatch, tmp_path
):
    root = tmp_path / "instance"
    root.mkdir()
    monkeypatch.setattr(diagnostics, "instance_dir", lambda _env, *, legacy=False: root)

    assert diagnostics._runtime_permission_targets(tmp_path / "bot.env") == [
        (root, 0o700)
    ]


def test_runtime_permission_targets_accepts_config_without_project_attachment_root(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        diagnostics,
        "instance_dir",
        lambda _env, *, legacy=False: tmp_path / f"missing-{legacy}",
    )

    assert (
        diagnostics._runtime_permission_targets(
            tmp_path / "bot.env", {"CLAUDE_PROJECT_DIR": "  "}
        )
        == []
    )


def test_runtime_permissions_windows_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.os, "name", "nt")

    result = diagnostics._check_runtime_permissions(tmp_path / "bot.env")

    assert result.status == "warn"
    assert "Windows" in result.detail


def test_runtime_permissions_reports_no_local_files(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.os, "name", "posix")
    monkeypatch.setattr(diagnostics, "_runtime_permission_targets", lambda *_args: [])

    result = diagnostics._check_runtime_permissions(tmp_path / "bot.env")

    assert result.status == "ok"
    assert result.detail == "no local runtime files yet"


def test_fix_local_permissions_windows_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.os, "name", "nt")

    result = diagnostics.fix_local_permissions(tmp_path / "bot.env")

    assert result.status == "warn"
    assert "Windows" in result.detail


def test_fix_local_permissions_missing_env_file_fails(tmp_path):
    result = diagnostics.fix_local_permissions(tmp_path / "missing.env")

    assert result.status == "fail"
    assert "env file missing" in result.detail


def test_fix_local_permissions_reports_chmod_errors(monkeypatch, tmp_path):
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=x\n", encoding="utf-8")
    env_file.chmod(0o600)
    runtime_file = tmp_path / "tgcc.log"
    runtime_file.write_text("log\n", encoding="utf-8")
    runtime_file.chmod(0o644)
    monkeypatch.setattr(diagnostics, "parse_env_file", lambda _path: {})
    monkeypatch.setattr(
        diagnostics,
        "_runtime_permission_targets",
        lambda *_args: [(runtime_file, 0o600)],
    )
    original_set_file = diagnostics.set_owner_only_file

    def set_file_with_error(path: Path):
        if path == runtime_file:
            return False
        return original_set_file(path)

    monkeypatch.setattr(diagnostics, "set_owner_only_file", set_file_with_error)

    result = diagnostics.fix_local_permissions(env_file)

    assert result.status == "warn"
    assert "errors:" in result.detail
    assert "could not set owner-only mode" in result.detail
    assert stat.S_IMODE(runtime_file.stat().st_mode) == 0o644


@pytest.mark.skipif(
    not hasattr(os, "fchmod"),
    reason="fd-level chmod is unavailable on this platform",
)
def test_fix_local_permissions_uses_fd_helpers_for_files(monkeypatch, tmp_path):
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=x\n", encoding="utf-8")
    env_file.chmod(0o644)
    runtime_file = tmp_path / "tgcc.log"
    runtime_file.write_text("log\n", encoding="utf-8")
    runtime_file.chmod(0o644)
    monkeypatch.setattr(diagnostics, "parse_env_file", lambda _path: {})
    monkeypatch.setattr(
        diagnostics,
        "_runtime_permission_targets",
        lambda *_args: [(runtime_file, 0o600)],
    )

    def fail_path_chmod(_path: Path, _mode: int):
        raise AssertionError("permission repair should tighten files by fd")

    monkeypatch.setattr(Path, "chmod", fail_path_chmod)

    result = diagnostics.fix_local_permissions(env_file)

    assert result.status == "ok"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(runtime_file.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are required")
def test_fix_local_permissions_reports_type_mismatch_without_chmod(
    monkeypatch, tmp_path
):
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=x\n", encoding="utf-8")
    env_file.chmod(0o600)
    runtime_file = tmp_path / "tgcc.log"
    runtime_file.mkdir()
    runtime_file.chmod(0o700)
    monkeypatch.setattr(diagnostics, "parse_env_file", lambda _path: {})
    monkeypatch.setattr(
        diagnostics,
        "_runtime_permission_targets",
        lambda *_args: [(runtime_file, 0o600)],
    )

    result = diagnostics.fix_local_permissions(env_file)

    assert result.status == "warn"
    assert "expected regular file" in result.detail
    assert runtime_file.is_dir()
    assert stat.S_IMODE(runtime_file.stat().st_mode) == 0o700


def test_config_checks_cover_warning_and_failure_edges(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    assert (
        diagnostics._check_id_list(
            {"ADMIN_USER_IDS": ","}, "ADMIN_USER_IDS", required=True
        ).status
        == "fail"
    )
    assert (
        diagnostics._check_project_dir(
            {"CLAUDE_PROJECT_DIR": "project"}, tmp_path / "bot.env"
        ).status
        == "ok"
    )
    assert (
        diagnostics._check_int(
            {"QUEUE_MAX_SIZE": "0"}, "QUEUE_MAX_SIZE", default="3", minimum=1
        ).status
        == "warn"
    )
    assert (
        diagnostics._check_permission_mode({"CLAUDE_PERMISSION_MODE": "wild"}).status
        == "fail"
    )
    assert diagnostics._check_effort({"CLAUDE_EFFORT": "ultracode"}).status == "ok"
    assert diagnostics._check_effort({"CLAUDE_EFFORT": "extreme"}).status == "fail"
    assert (
        diagnostics._check_skip_permissions({"CLAUDE_SKIP_PERMISSIONS": "true"}).status
        == "warn"
    )


def test_claude_cli_missing_is_failure(monkeypatch):
    # FAIL, not WARN: tgcc start hard-fails without the CLI, so doctor agrees.
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _cmd: None)

    result = diagnostics._check_claude_cli()

    assert result.status == "fail"
    assert "not found" in result.detail


def test_run_doctor_missing_env_reports_env_failure_and_cli_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _cmd: None)

    results = diagnostics.run_doctor(tmp_path / "missing.env")

    assert [(item.name, item.status) for item in results] == [
        ("Env file", "fail"),
        ("Claude Code CLI", "fail"),
    ]
    assert diagnostics.doctor_exit_code(results) == 1
    report = diagnostics.render_doctor_report(results)
    assert "Summary: 0 ok, 0 warning(s), 2 failure(s)." in report


def test_doctor_exit_code_can_treat_warnings_as_strict_failures() -> None:
    results = [
        diagnostics.Diagnostic("Env permissions", "warn", "mode is 644"),
        diagnostics.Diagnostic("TELEGRAM_BOT_TOKEN", "ok", "configured"),
    ]

    assert diagnostics.doctor_exit_code(results) == 0
    assert diagnostics.doctor_exit_code(results, strict=True) == 1


def test_render_doctor_json_includes_summary_and_diagnostics() -> None:
    results = [
        diagnostics.Diagnostic("Env permissions", "warn", "mode is 644"),
        diagnostics.Diagnostic("TELEGRAM_BOT_TOKEN", "ok", "configured"),
    ]

    rendered = diagnostics.render_doctor_json(results)

    assert '"warnings": 1' in rendered
    assert '"name": "Env permissions"' in rendered
    assert '"detail": "configured"' in rendered
