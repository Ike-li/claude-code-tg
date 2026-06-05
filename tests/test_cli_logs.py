"""Tests for the tgcc logs command."""

import os
import threading
import time
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import cmd_logs
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_logs_missing_does_not_create_instance_dir(monkeypatch, tmp_path, capsys):
    """Viewing logs for a missing instance must not create an empty instance dir."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    args = MagicMock()
    args.env = str(env_file)
    args.lines = 50
    args.follow = False
    cmd_logs(args)

    captured = capsys.readouterr()
    assert "No log file found" in captured.out
    assert not (tmp_path / _instance_name(str(env_file))).exists()


def test_cmd_logs_without_env_requires_choice_for_multi_env(
    monkeypatch, tmp_path, capsys
):
    """Bare logs in a multi-env directory should not show stale default logs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cctg.env").write_text("TOKEN=test")
    (tmp_path / "gmgn.env").write_text("TOKEN=test")

    args = MagicMock()
    args.env = None
    args.lines = 50
    args.follow = False

    with pytest.raises(SystemExit) as exc:
        cmd_logs(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Multiple .env files found" in captured.out
    assert "tgcc logs --env <file>" in captured.out


def test_cmd_logs_zero_lines_prints_no_history(monkeypatch, tmp_path, capsys):
    """-n 0 should mean no historical tail, not the entire log file."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    _, logfile = _instance_paths(str(tmp_path / "test.env"))
    logfile.write_text("line1\nline2\n", encoding="utf-8")

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    args.lines = 0
    args.follow = False
    cmd_logs(args)

    assert capsys.readouterr().out == ""


def test_cmd_logs_follow_handles_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    """Ctrl+C during follow mode should exit cleanly without a traceback."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    _, logfile = _instance_paths(str(tmp_path / "test.env"))
    logfile.write_text("line1\n", encoding="utf-8")
    monkeypatch.setattr(
        "claude_code_tg.cli.time.sleep", MagicMock(side_effect=KeyboardInterrupt)
    )

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    args.lines = 0
    args.follow = True
    cmd_logs(args)

    assert capsys.readouterr().out == ""


def test_cmd_logs_replaces_invalid_utf8(monkeypatch, tmp_path, capsys):
    """Corrupt log bytes should not crash the log viewer."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    _, logfile = _instance_paths(str(tmp_path / "test.env"))
    logfile.write_bytes(b"line1\nbad:\xff\n")

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    args.lines = 50
    args.follow = False
    cmd_logs(args)

    output = capsys.readouterr().out
    assert "line1" in output
    assert "bad:\ufffd" in output


@pytest.mark.skipif(os.name == "nt", reason="symlink log checks are POSIX-only")
def test_cmd_logs_rejects_symlinked_logfile(monkeypatch, tmp_path, capsys):
    """tgcc logs should not print content through a symlinked runtime log."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    outside = tmp_path / "outside.log"
    outside.write_text("outside secret\n", encoding="utf-8")
    _, logfile = _instance_paths(str(tmp_path / "test.env"))
    try:
        logfile.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    args.lines = 50
    args.follow = False
    cmd_logs(args)

    captured = capsys.readouterr()
    assert "symlink" in captured.out
    assert "outside secret" not in captured.out


@pytest.mark.skipif(os.name == "nt", reason="symlink log checks are POSIX-only")
def test_cmd_logs_rejects_symlinked_instance_dir(monkeypatch, tmp_path, capsys):
    """tgcc logs should not read through a symlinked runtime directory."""
    tgcc_dir = tmp_path / "tgcc"
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tgcc_dir)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    real_dir = tmp_path / "real-instance"
    real_dir.mkdir()
    (real_dir / "tgcc.log").write_text("outside secret\n", encoding="utf-8")
    instance_dir = tgcc_dir / _instance_name(str(env_file))
    instance_dir.parent.mkdir()
    try:
        instance_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.env = str(env_file)
    args.lines = 50
    args.follow = False
    cmd_logs(args)

    captured = capsys.readouterr()
    assert "Log path contains a symlink" in captured.out
    assert "outside secret" not in captured.out


def test_cmd_logs_follow_detects_rotation(monkeypatch, tmp_path, capsys):
    """Log rotation (file truncation) is detected and new content is read."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    _, logfile = _instance_paths(str(tmp_path / "test.env"))
    logfile.write_text("line1\nline2\n")

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    args.lines = 50
    args.follow = True

    # Run cmd_logs in a thread; it will loop forever.
    def run_logs():
        with suppress(Exception):
            cmd_logs(args)

    thread = threading.Thread(target=run_logs, daemon=True)
    thread.start()
    time.sleep(0.3)

    # Simulate log rotation: truncate and write new content.
    logfile.write_text("rotated1\nrotated2\n")
    time.sleep(1.0)

    captured = capsys.readouterr()
    assert "line1" in captured.out or "rotated1" in captured.out
