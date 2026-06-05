"""Tests for the tgcc status command."""

import os
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import cmd_status
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_status_running(monkeypatch, tmp_path, capsys):
    """Valid PID -> 'Running'."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    pidfile, _ = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))

    args = MagicMock()
    args.env = str(env_file)
    cmd_status(args)

    captured = capsys.readouterr()
    assert "Running" in captured.out


def test_cmd_status_not_running(monkeypatch, tmp_path, capsys):
    """No PID -> 'Not running'."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    args = MagicMock()
    args.env = str(env_file)
    cmd_status(args)

    captured = capsys.readouterr()
    assert "Not running" in captured.out
    assert not (tmp_path / _instance_name(str(env_file))).exists()


def test_cmd_status_without_env_lists_project_instances(monkeypatch, tmp_path, capsys):
    """Bare status in a multi-env directory should summarize every instance."""
    tgcc_dir = tmp_path / "tgcc"
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tgcc_dir)
    monkeypatch.chdir(tmp_path)
    running_env = tmp_path / "cctg.env"
    stopped_env = tmp_path / "gmgn.env"
    running_env.write_text("TOKEN=test")
    stopped_env.write_text("TOKEN=test")
    pidfile, _ = _instance_paths(str(running_env))
    pidfile.write_text(str(os.getpid()))

    args = MagicMock()
    args.env = None
    args.all = False
    cmd_status(args)

    captured = capsys.readouterr()
    assert "Instances:" in captured.out
    assert "cctg.env" in captured.out
    assert "gmgn.env" in captured.out
    assert "Running" in captured.out
    assert "Not running" in captured.out
    assert "tgcc logs --env <file>" in captured.out


def test_cmd_status_all_reports_no_env_files(monkeypatch, capsys):
    """Explicit --all should be friendly in directories without env files."""
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", list)

    args = MagicMock()
    args.env = None
    args.all = True
    cmd_status(args)

    assert "No .env files found" in capsys.readouterr().out


def test_cmd_status_all_conflicts_with_env(capsys):
    """--all and --env should not silently pick one meaning."""
    args = MagicMock()
    args.env = "prod.env"
    args.all = True

    with pytest.raises(SystemExit) as exc:
        cmd_status(args)

    assert exc.value.code == 1
    assert "either --all or --env" in capsys.readouterr().out
