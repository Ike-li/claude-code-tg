"""Tests for bulk tgcc lifecycle commands."""

import os
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import cmd_restart_all, cmd_start_all, cmd_stop_all
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_start_all_detects_legacy_running_instance(monkeypatch, tmp_path, capsys):
    """start-all should report legacy running pids instead of trying to start."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / "prod.env"
    env_file.write_text("TOKEN=test")
    legacy_dir = tmp_path / "tgcc" / "prod"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "tgcc.pid").write_text(str(os.getpid()))

    args = MagicMock()
    cmd_start_all(args)

    captured = capsys.readouterr()
    assert "prod.env: already running" in captured.out
    assert str(os.getpid()) in captured.out
    assert "Logs:" in captured.out


def test_cmd_start_all_reports_no_env_files(monkeypatch, capsys):
    """start-all should be a no-op in directories without env files."""
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", list)

    args = MagicMock()
    cmd_start_all(args)

    assert "No .env files found" in capsys.readouterr().out


def test_cmd_start_all_can_print_prefixed_logs(monkeypatch, tmp_path, capsys):
    """start-all --logs should show recent logs for every discovered env."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "cctg.env"
    second = tmp_path / "gmgn.env"
    first.write_text("TOKEN=test")
    second.write_text("TOKEN=test")

    first_pidfile, first_logfile = _instance_paths(str(first))
    second_pidfile, second_logfile = _instance_paths(str(second))
    first_pidfile.write_text(str(os.getpid()))
    second_pidfile.write_text(str(os.getpid()))
    first_logfile.write_text("old cctg\nnew cctg\n")
    second_logfile.write_text("old gmgn\nnew gmgn\n")

    args = MagicMock()
    args.logs = True
    args.follow = False
    args.lines = 1
    cmd_start_all(args)

    captured = capsys.readouterr()
    assert "== cctg.env |" in captured.out
    assert "== gmgn.env |" in captured.out
    assert "[cctg.env] new cctg" in captured.out
    assert "[gmgn.env] new gmgn" in captured.out
    assert "old cctg" not in captured.out
    assert "old gmgn" not in captured.out


@pytest.mark.skipif(os.name == "nt", reason="symlink log checks are POSIX-only")
def test_cmd_start_all_logs_rejects_symlinked_logfile(monkeypatch, tmp_path, capsys):
    """start-all --logs should skip symlinked log files instead of printing targets."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / "tgcc")
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / "cctg.env"
    env_file.write_text("TOKEN=test")
    pidfile, logfile = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))
    outside = tmp_path / "outside.log"
    outside.write_text("outside secret\n", encoding="utf-8")
    try:
        logfile.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.logs = True
    args.follow = False
    args.lines = 1
    cmd_start_all(args)

    captured = capsys.readouterr()
    assert "Log path contains a symlink" in captured.out
    assert "outside secret" not in captured.out


@pytest.mark.skipif(os.name == "nt", reason="symlink log checks are POSIX-only")
def test_cmd_start_all_logs_rejects_symlinked_instance_dir(
    monkeypatch, tmp_path, capsys
):
    """start-all --logs should skip logs under symlinked instance directories."""
    tgcc_dir = tmp_path / "tgcc"
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tgcc_dir)
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / "cctg.env"
    env_file.write_text("TOKEN=test")
    real_dir = tmp_path / "real-instance"
    real_dir.mkdir()
    (real_dir / "tgcc.pid").write_text(str(os.getpid()))
    (real_dir / "tgcc.log").write_text("outside secret\n", encoding="utf-8")
    instance_dir = tgcc_dir / _instance_name(str(env_file))
    instance_dir.parent.mkdir()
    try:
        instance_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.logs = True
    args.follow = False
    args.lines = 1
    cmd_start_all(args)

    captured = capsys.readouterr()
    assert "Log path contains a symlink" in captured.out
    assert "outside secret" not in captured.out


def test_cmd_stop_all_reports_no_env_files(monkeypatch, capsys):
    """stop-all should be friendly in directories without env files."""
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", list)

    args = MagicMock()
    cmd_stop_all(args)

    assert "No .env files found" in capsys.readouterr().out


def test_cmd_stop_all_dispatches_each_env(monkeypatch, tmp_path):
    """stop-all should run stop once per discovered env file."""
    env_files = [tmp_path / "a.env", tmp_path / "b.env"]
    calls: list[str] = []
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", lambda: env_files)
    monkeypatch.setattr(
        "claude_code_tg.cli.cmd_stop", lambda args: calls.append(args.env)
    )

    args = MagicMock()
    cmd_stop_all(args)

    assert calls == [str(env_files[0]), str(env_files[1])]


def test_cmd_restart_all_reports_no_env_files(monkeypatch, capsys):
    """restart-all should be a no-op in directories without env files."""
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", list)

    args = MagicMock()
    cmd_restart_all(args)

    assert "No .env files found" in capsys.readouterr().out


def test_cmd_restart_all_reports_failed_restart(monkeypatch, tmp_path, capsys):
    """restart-all should continue reporting env-level failures."""
    env_file = tmp_path / "bad.env"
    monkeypatch.setattr("claude_code_tg.cli.discover_env_files", lambda: [env_file])
    monkeypatch.setattr(
        "claude_code_tg.cli.cmd_restart", MagicMock(side_effect=SystemExit(1))
    )

    args = MagicMock()
    cmd_restart_all(args)

    assert "Failed to restart bad.env" in capsys.readouterr().out
