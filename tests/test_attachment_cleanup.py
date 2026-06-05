"""Tests for CLI-facing attachment cleanup helpers."""

from argparse import Namespace
from pathlib import Path

import pytest

from claude_code_tg import attachment_cleanup
from claude_code_tg.attachments import AttachmentPruneResult


def test_format_bytes_uses_binary_units():
    assert attachment_cleanup.format_bytes(0) == "0 B"
    assert attachment_cleanup.format_bytes(1023) == "1023 B"
    assert attachment_cleanup.format_bytes(1024) == "1.0 KiB"
    assert attachment_cleanup.format_bytes(1024 * 1024) == "1.0 MiB"
    assert attachment_cleanup.format_bytes(1024**3) == "1.0 GiB"


def test_project_attachment_root_prefers_explicit_project_dir(tmp_path):
    env_file = tmp_path / "bot.env"
    project = tmp_path / "project"

    result = attachment_cleanup.project_attachment_root(env_file, str(project))

    assert result == project.resolve(strict=False) / ".tgcc-attachments"


def test_project_attachment_root_reads_env_project_dir(tmp_path):
    project = tmp_path / "from-env"
    env_file = tmp_path / "bot.env"
    env_file.write_text(f"CLAUDE_PROJECT_DIR={project}\n", encoding="utf-8")

    result = attachment_cleanup.project_attachment_root(env_file, None)

    assert result == project.resolve(strict=False) / ".tgcc-attachments"


@pytest.mark.skipif(
    not hasattr(Path, "symlink_to"),
    reason="symlink creation is unavailable",
)
def test_project_attachment_root_preserves_symlink_project_dir(tmp_path):
    real_project = tmp_path / "real-project"
    real_project.mkdir()
    linked_project = tmp_path / "linked-project"
    try:
        linked_project.symlink_to(real_project, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    env_file = tmp_path / "bot.env"
    env_file.write_text(f"CLAUDE_PROJECT_DIR={linked_project}\n", encoding="utf-8")

    result = attachment_cleanup.project_attachment_root(env_file, None)

    assert result == linked_project / ".tgcc-attachments"


def test_attachment_roots_for_env_respects_scope(monkeypatch, tmp_path):
    env_file = tmp_path / "bot.env"
    instance_log = tmp_path / ".tgcc" / "bot" / "tgcc.log"

    monkeypatch.setattr(
        attachment_cleanup,
        "instance_paths",
        lambda _env, create=False: (instance_log.parent / "tgcc.pid", instance_log),
    )
    monkeypatch.setattr(
        attachment_cleanup,
        "project_attachment_root",
        lambda _env_file, _project_dir: tmp_path / "project" / ".tgcc-attachments",
    )

    assert attachment_cleanup.attachment_roots_for_env(
        env_file, scope="instance", project_dir=None
    ) == [("bot.env instance attachments", instance_log.parent / "attachments")]
    assert attachment_cleanup.attachment_roots_for_env(
        env_file, scope="project", project_dir=None
    ) == [("bot.env project attachments", tmp_path / "project" / ".tgcc-attachments")]
    assert attachment_cleanup.attachment_roots_for_env(
        env_file, scope="all", project_dir=None
    ) == [
        ("bot.env instance attachments", instance_log.parent / "attachments"),
        ("bot.env project attachments", tmp_path / "project" / ".tgcc-attachments"),
    ]


def test_print_prune_result_reports_missing_root_warnings(capsys, tmp_path):
    result = AttachmentPruneResult(
        root=tmp_path / "missing",
        root_exists=False,
        files=0,
        byte_count=0,
        dirs_removed=0,
        errors=("skipped",),
    )

    attachment_cleanup.print_prune_result("bot.env instance attachments", result)

    output = capsys.readouterr().out
    assert "no attachment directory" in output
    assert "warning: skipped" in output


def test_print_prune_result_reports_dry_run_and_removed_dirs(capsys, tmp_path):
    result = AttachmentPruneResult(
        root=tmp_path / "attachments",
        root_exists=True,
        files=2,
        byte_count=2048,
        dirs_removed=1,
        dry_run=True,
    )

    attachment_cleanup.print_prune_result("bot.env project attachments", result)

    output = capsys.readouterr().out
    assert "Would delete 2 files (2.0 KiB)" in output
    assert "removed 1 empty directories" in output


def test_run_attachment_prune_reports_no_env_files(monkeypatch, capsys):
    monkeypatch.setattr(attachment_cleanup, "discover_env_files", list)
    args = Namespace(
        all_envs=True,
        env=None,
        all_files=False,
        older_than_days=30,
        scope="all",
        project_dir=None,
        dry_run=True,
    )

    attachment_cleanup.run_attachment_prune(
        args,
        resolve_single_env=lambda _env: Path("unused.env"),
    )

    assert "No .env files found" in capsys.readouterr().out


def test_run_attachment_prune_deduplicates_roots_and_sums_results(
    monkeypatch, capsys, tmp_path
):
    env_files = [tmp_path / "one.env", tmp_path / "two.env"]
    shared_root = tmp_path / "attachments"
    seen_calls: list[tuple[Path, float | None, bool]] = []

    monkeypatch.setattr(attachment_cleanup, "discover_env_files", lambda: env_files)
    monkeypatch.setattr(
        attachment_cleanup,
        "attachment_roots_for_env",
        lambda env_file, *, scope, project_dir: [
            (f"{env_file.name} attachments", shared_root)
        ],
    )

    def fake_prune(root, *, older_than_seconds, dry_run):
        seen_calls.append((root, older_than_seconds, dry_run))
        return AttachmentPruneResult(
            root=root,
            root_exists=True,
            files=2,
            byte_count=5,
            dirs_removed=0,
            errors=("warn",),
            dry_run=dry_run,
        )

    monkeypatch.setattr(attachment_cleanup, "prune_attachment_tree", fake_prune)
    args = Namespace(
        all_envs=True,
        env=None,
        all_files=False,
        older_than_days=2,
        scope="all",
        project_dir="/project",
        dry_run=True,
    )

    attachment_cleanup.run_attachment_prune(
        args,
        resolve_single_env=lambda _env: Path("unused.env"),
    )

    assert seen_calls == [(shared_root, 2 * 86400, True)]
    output = capsys.readouterr().out
    assert "Summary: would delete 2 files (5 B)" in output
    assert "Summary: 1 warnings" in output


def test_run_attachment_prune_all_files_disables_age_cutoff(monkeypatch, tmp_path):
    env_file = tmp_path / "bot.env"
    root = tmp_path / "attachments"
    seen_cutoffs: list[float | None] = []

    monkeypatch.setattr(
        attachment_cleanup,
        "attachment_roots_for_env",
        lambda _env_file, *, scope, project_dir: [("bot.env attachments", root)],
    )

    def fake_prune(_root, *, older_than_seconds, dry_run):
        seen_cutoffs.append(older_than_seconds)
        return AttachmentPruneResult(
            root=root,
            root_exists=True,
            files=0,
            byte_count=0,
            dirs_removed=0,
            dry_run=dry_run,
        )

    monkeypatch.setattr(attachment_cleanup, "prune_attachment_tree", fake_prune)
    args = Namespace(
        all_envs=False,
        env=str(env_file),
        all_files=True,
        older_than_days=30,
        scope="instance",
        project_dir=None,
        dry_run=False,
    )

    attachment_cleanup.run_attachment_prune(
        args,
        resolve_single_env=lambda env: Path(env),
    )

    assert seen_cutoffs == [None]


def test_run_attachment_prune_preserves_project_symlink_for_prune_guard(
    tmp_path, capsys
):
    real_project = tmp_path / "real-project"
    cache_root = real_project / ".tgcc-attachments"
    cache_root.mkdir(parents=True)
    old_file = cache_root / "old.txt"
    old_file.write_text("keep", encoding="utf-8")
    linked_project = tmp_path / "linked-project"
    try:
        linked_project.symlink_to(real_project, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    env_file = tmp_path / "bot.env"
    env_file.write_text(f"CLAUDE_PROJECT_DIR={linked_project}\n", encoding="utf-8")
    args = Namespace(
        all_envs=False,
        env=str(env_file),
        all_files=True,
        older_than_days=30,
        scope="project",
        project_dir=None,
        dry_run=False,
    )

    attachment_cleanup.run_attachment_prune(
        args,
        resolve_single_env=lambda env: Path(env),
    )

    output = capsys.readouterr().out
    assert "symlink root skipped" in output
    assert old_file.exists()


def test_run_attachment_prune_rejects_env_with_all_envs(capsys):
    args = Namespace(all_envs=True, env="bot.env")

    with pytest.raises(SystemExit) as exc:
        attachment_cleanup.run_attachment_prune(
            args,
            resolve_single_env=lambda _env: Path("unused.env"),
        )

    assert exc.value.code == 1
    assert "either --all-envs or --env" in capsys.readouterr().out
