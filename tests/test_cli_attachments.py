"""Tests for CLI attachment commands."""

import argparse
import os
from unittest.mock import MagicMock

import pytest

from claude_code_tg.attachment_cleanup import positive_float as _positive_float
from claude_code_tg.cli import cmd_attachments, cmd_attachments_prune
from claude_code_tg.instance_store import instance_paths as _instance_paths


def test_cmd_attachments_prune_cleans_instance_and_project(
    monkeypatch, tmp_path, capsys
):
    """Attachment pruning should cover both instance cache and project copies."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    env_file = tmp_path / "bot.env"
    project_dir = tmp_path / "project"
    env_file.write_text(f"CLAUDE_PROJECT_DIR={project_dir}\n", encoding="utf-8")

    _, logfile = _instance_paths(str(env_file))
    instance_file = logfile.parent / "attachments" / "111" / "old-instance.txt"
    project_file = project_dir / ".tgcc-attachments" / "111" / "old-project.txt"
    fresh_file = logfile.parent / "attachments" / "222" / "fresh.txt"
    for path in (instance_file, project_file, fresh_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("attachment", encoding="utf-8")
    os.utime(instance_file, (100, 100))
    os.utime(project_file, (100, 100))

    args = MagicMock()
    args.env = str(env_file)
    args.all_envs = False
    args.scope = "all"
    args.project_dir = None
    args.all_files = False
    args.older_than_days = 1
    args.dry_run = False

    cmd_attachments_prune(args)

    assert not instance_file.exists()
    assert not project_file.exists()
    assert fresh_file.exists()
    captured = capsys.readouterr()
    assert "bot.env instance attachments" in captured.out
    assert "bot.env project attachments" in captured.out
    assert "Summary: deleted 2 files" in captured.out


def test_cmd_attachments_prune_dry_run_preserves_files(monkeypatch, tmp_path):
    """Dry-run reports candidates without unlinking files."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("CLAUDE_PROJECT_DIR=.\n", encoding="utf-8")
    _, logfile = _instance_paths(str(env_file))
    target = logfile.parent / "attachments" / "111" / "old.txt"
    target.parent.mkdir(parents=True)
    target.write_text("attachment", encoding="utf-8")
    os.utime(target, (100, 100))

    args = MagicMock()
    args.env = str(env_file)
    args.all_envs = False
    args.scope = "instance"
    args.project_dir = None
    args.all_files = False
    args.older_than_days = 1
    args.dry_run = True

    cmd_attachments_prune(args)

    assert target.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink prune checks are POSIX-only")
def test_cmd_attachments_prune_warns_on_symlink_root(monkeypatch, tmp_path, capsys):
    """Attachment pruning should warn and skip symlinked cache roots."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("CLAUDE_PROJECT_DIR=.\n", encoding="utf-8")
    _, logfile = _instance_paths(str(env_file))
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    root = logfile.parent / "attachments"
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.env = str(env_file)
    args.all_envs = False
    args.scope = "instance"
    args.project_dir = None
    args.all_files = True
    args.older_than_days = 1
    args.dry_run = False

    cmd_attachments_prune(args)

    assert outside_file.exists()
    captured = capsys.readouterr()
    assert "warning:" in captured.out
    assert "symlink root skipped" in captured.out
    assert "Summary: deleted 0 files" in captured.out


def test_cmd_attachments_prune_rejects_env_with_all_envs(capsys):
    """Env selection should stay explicit for destructive cleanup commands."""
    args = MagicMock()
    args.env = "prod.env"
    args.all_envs = True

    with pytest.raises(SystemExit) as exc:
        cmd_attachments_prune(args)

    assert exc.value.code == 1
    assert "either --all-envs or --env" in capsys.readouterr().out


def test_cmd_attachments_requires_subcommand(capsys):
    """The attachments command should not silently choose a destructive action."""
    args = MagicMock()
    args.attachments_command = None

    with pytest.raises(SystemExit) as exc:
        cmd_attachments(args)

    assert exc.value.code == 1
    assert "missing attachments command" in capsys.readouterr().out


def test_cmd_attachments_dispatches_prune(monkeypatch):
    """The parent attachments command should route prune to the prune handler."""
    calls = []
    monkeypatch.setattr(
        "claude_code_tg.cli.cmd_attachments_prune", lambda args: calls.append(args)
    )

    args = MagicMock()
    args.attachments_command = "prune"
    cmd_attachments(args)

    assert calls == [args]


@pytest.mark.parametrize("value", ["0", "0.5", "30"])
def test_positive_float_accepts_finite_non_negative_values(value):
    """Attachment cleanup retention values should accept finite day counts."""
    assert _positive_float(value) == float(value)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("soon", "must be a number"),
        ("-1", "must be greater than or equal to 0"),
        ("nan", "must be a finite number"),
        ("inf", "must be a finite number"),
        ("-inf", "must be a finite number"),
    ],
)
def test_positive_float_rejects_invalid_or_non_finite_values(value, message):
    """Attachment cleanup should not accept unpredictable retention windows."""
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        _positive_float(value)
