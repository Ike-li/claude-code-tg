"""Tests for the tgcc stop and restart commands."""

import os
import signal
from unittest.mock import MagicMock, patch

import pytest

from claude_code_tg.cli import cmd_restart, cmd_stop
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_stop_kills_process(monkeypatch, tmp_path):
    """Mock os.kill, verify SIGTERM sent."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    pidfile, _ = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))

    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda *a, **kw: True)

    args = MagicMock()
    args.env = str(env_file)
    cmd_stop(args)

    # _read_pid probes with signal 0, cmd_stop sends SIGTERM
    assert any(pid == os.getpid() and sig == signal.SIGTERM for pid, sig in kill_calls)
    assert not pidfile.exists()


def test_cmd_stop_treats_missing_process_as_stopped(monkeypatch, tmp_path, capsys):
    """A stale PID that disappears before SIGTERM should still be cleaned up."""
    pidfile = tmp_path / "tgcc.pid"
    logfile = tmp_path / "tgcc.log"
    pidfile.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(
        "claude_code_tg.cli._running_instances",
        lambda _env: [(12345, pidfile, logfile)],
    )
    monkeypatch.setattr(
        "claude_code_tg.cli._send_signal_to_process_tree",
        MagicMock(side_effect=ProcessLookupError),
    )

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    cmd_stop(args)

    assert not pidfile.exists()
    assert "Stopped (PID 12345)" in capsys.readouterr().out


def test_cmd_stop_not_running(monkeypatch, tmp_path, capsys):
    """No PID file -> prints 'Not running'."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    args = MagicMock()
    args.env = str(env_file)
    cmd_stop(args)

    captured = capsys.readouterr()
    assert "Not running" in captured.out
    assert not (tmp_path / _instance_name(str(env_file))).exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink PID checks are POSIX-only")
def test_cmd_stop_ignores_symlinked_pidfile(monkeypatch, tmp_path, capsys):
    """Stop should not signal a PID read through a symlinked runtime file."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    target = tmp_path / "outside.pid"
    target.write_text(str(os.getpid()), encoding="utf-8")
    pidfile, _ = _instance_paths(str(env_file))
    try:
        pidfile.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))

    args = MagicMock()
    args.env = str(env_file)
    cmd_stop(args)

    captured = capsys.readouterr()
    assert "Not running" in captured.out
    assert kill_calls == []
    assert pidfile.is_symlink()
    assert target.read_text(encoding="utf-8") == str(os.getpid())


def test_cmd_stop_stops_legacy_running_instance(monkeypatch, tmp_path):
    """Stop should clean up legacy pid files for upgraded installations."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    legacy_pidfile = legacy_dir / "tgcc.pid"
    legacy_pidfile.write_text(str(os.getpid()))

    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda *a, **kw: True)

    args = MagicMock()
    args.env = str(env_file)
    cmd_stop(args)

    assert any(pid == os.getpid() and sig == signal.SIGTERM for pid, sig in kill_calls)
    assert not legacy_pidfile.exists()


def test_cmd_stop_warns_when_pidfile_cleanup_fails(monkeypatch, tmp_path, capsys):
    """A pidfile cleanup race should warn without turning stop into a failure."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    pidfile, _ = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))

    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda *a, **kw: True)

    args = MagicMock()
    args.env = str(env_file)
    with patch.object(type(pidfile), "unlink", side_effect=OSError("busy")):
        cmd_stop(args)

    output = capsys.readouterr().out
    assert any(pid == os.getpid() and sig == signal.SIGTERM for pid, sig in kill_calls)
    assert "Warning: could not remove pid file" in output
    assert "Stopped (PID" in output


def test_cmd_stop_kills_after_timeout(monkeypatch, tmp_path, capsys):
    """Stop escalates to SIGKILL when the process does not exit."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    pidfile, _ = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))

    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda *a, **kw: False)

    args = MagicMock()
    args.env = str(env_file)
    cmd_stop(args)

    assert any(pid == os.getpid() and sig == signal.SIGTERM for pid, sig in kill_calls)
    assert any(pid == os.getpid() and sig == signal.SIGKILL for pid, sig in kill_calls)
    assert "SIGKILL" in capsys.readouterr().out


def test_cmd_stop_ignores_process_lookup_during_sigkill(monkeypatch, tmp_path, capsys):
    """Escalation should tolerate a process disappearing before SIGKILL lands."""
    pidfile = tmp_path / "tgcc.pid"
    logfile = tmp_path / "tgcc.log"
    pidfile.write_text("12345", encoding="utf-8")
    send_calls: list[tuple[int, signal.Signals]] = []

    def fake_send(pid: int, sig: signal.Signals) -> None:
        send_calls.append((pid, sig))
        if sig == signal.SIGKILL:
            raise ProcessLookupError

    monkeypatch.setattr(
        "claude_code_tg.cli._running_instances",
        lambda _env: [(12345, pidfile, logfile)],
    )
    monkeypatch.setattr("claude_code_tg.cli._send_signal_to_process_tree", fake_send)
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda *a, **kw: False)

    args = MagicMock()
    args.env = str(tmp_path / "test.env")
    cmd_stop(args)

    assert send_calls == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]
    assert not pidfile.exists()
    assert "SIGKILL" in capsys.readouterr().out


def test_cmd_restart_dispatches_stop_then_start(monkeypatch):
    """restart is intentionally a stop followed by start for the same args."""
    calls: list[str] = []
    monkeypatch.setattr(
        "claude_code_tg.cli.cmd_stop", lambda _args: calls.append("stop")
    )
    monkeypatch.setattr(
        "claude_code_tg.cli.cmd_start", lambda _args: calls.append("start")
    )

    args = MagicMock()
    cmd_restart(args)

    assert calls == ["stop", "start"]
