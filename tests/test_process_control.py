"""Direct tests for process and PID helpers."""

import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_tg import process_control


def test_send_signal_to_process_tree_targets_process_group(monkeypatch):
    calls: list[tuple[str, int, signal.Signals]] = []

    monkeypatch.setattr(process_control.os, "name", "posix")
    monkeypatch.setattr(process_control.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        process_control.os,
        "killpg",
        lambda pid, sig: calls.append(("killpg", pid, sig)),
    )
    monkeypatch.setattr(
        process_control.os,
        "kill",
        lambda pid, sig: calls.append(("kill", pid, sig)),
    )

    process_control.send_signal_to_process_tree(123, signal.SIGTERM)

    assert calls == [("killpg", 123, signal.SIGTERM)]


def test_send_signal_to_process_tree_targets_process_when_not_group_leader(
    monkeypatch,
):
    calls: list[tuple[str, int, signal.Signals]] = []

    monkeypatch.setattr(process_control.os, "name", "posix")
    monkeypatch.setattr(process_control.os, "getpgid", lambda _pid: 999)
    monkeypatch.setattr(
        process_control.os,
        "killpg",
        lambda pid, sig: calls.append(("killpg", pid, sig)),
    )
    monkeypatch.setattr(
        process_control.os,
        "kill",
        lambda pid, sig: calls.append(("kill", pid, sig)),
    )

    process_control.send_signal_to_process_tree(123, signal.SIGTERM)

    assert calls == [("kill", 123, signal.SIGTERM)]


def test_send_signal_to_process_tree_falls_back_when_getpgid_fails(monkeypatch):
    calls: list[tuple[str, int, signal.Signals]] = []

    def fail_getpgid(_pid):
        raise OSError("no process group")

    monkeypatch.setattr(process_control.os, "name", "posix")
    monkeypatch.setattr(process_control.os, "getpgid", fail_getpgid)
    monkeypatch.setattr(
        process_control.os,
        "kill",
        lambda pid, sig: calls.append(("kill", pid, sig)),
    )

    process_control.send_signal_to_process_tree(123, signal.SIGTERM)

    assert calls == [("kill", 123, signal.SIGTERM)]


def test_send_signal_to_process_tree_reraises_missing_process(monkeypatch):
    def fail_getpgid(_pid):
        raise ProcessLookupError

    monkeypatch.setattr(process_control.os, "name", "posix")
    monkeypatch.setattr(process_control.os, "getpgid", fail_getpgid)

    with pytest.raises(ProcessLookupError):
        process_control.send_signal_to_process_tree(123, signal.SIGTERM)


def test_read_pid_unlinks_invalid_pidfile(tmp_path):
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text("not-a-pid", encoding="utf-8")

    assert process_control.read_pid(pidfile) is None
    assert not pidfile.exists()


def test_read_pid_valid(tmp_path):
    """Current-process PID files should be read back as running."""
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")

    assert process_control.read_pid(pidfile) == os.getpid()


def test_read_pid_stale(tmp_path):
    """Nonexistent-process PID files should be cleaned up."""
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text("99999999", encoding="utf-8")

    assert process_control.read_pid(pidfile) is None
    assert not pidfile.exists()


def test_read_pid_ignores_unreadable_pidfile(tmp_path):
    """Unreadable or racy PID files should not crash status scans."""
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")
    with patch(
        "claude_code_tg.process_control.open_rejecting_symlink_read",
        side_effect=PermissionError,
    ):
        assert process_control.read_pid(pidfile) is None


def test_read_pid_ignores_unlink_error_for_invalid_pidfile(monkeypatch, tmp_path):
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text("not-a-pid", encoding="utf-8")

    monkeypatch.setattr(
        Path, "unlink", lambda self, **_kwargs: (_ for _ in ()).throw(OSError("busy"))
    )

    assert process_control.read_pid(pidfile) is None
    assert pidfile.exists()


def test_read_pid_ignores_unlink_error_for_stale_pidfile(tmp_path):
    """Stale PID cleanup is best-effort when the pidfile cannot be removed."""
    pidfile = tmp_path / "tgcc.pid"
    pidfile.write_text("99999999", encoding="utf-8")
    with patch.object(type(pidfile), "unlink", side_effect=OSError):
        assert process_control.read_pid(pidfile) is None
    assert pidfile.exists()


def test_read_pid_missing_file(tmp_path):
    """Missing PID files are treated as not running."""
    pidfile = tmp_path / "nonexistent.pid"

    assert process_control.read_pid(pidfile) is None


@pytest.mark.skipif(os.name == "nt", reason="symlink PID checks are POSIX-only")
def test_read_pid_rejects_symlink(tmp_path, monkeypatch):
    """PID probes should not follow symlinked runtime PID files."""
    target = tmp_path / "outside.pid"
    target.write_text(str(os.getpid()), encoding="utf-8")
    pidfile = tmp_path / "tgcc.pid"
    try:
        pidfile.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    kill_calls = []
    monkeypatch.setattr("os.kill", lambda pid, sig: kill_calls.append((pid, sig)))

    assert process_control.read_pid(pidfile) is None
    assert kill_calls == []
    assert pidfile.is_symlink()
    assert target.read_text(encoding="utf-8") == str(os.getpid())


def test_read_pid_permission_error(tmp_path):
    """PermissionError during os.kill probe means the process exists."""
    pidfile = tmp_path / "test.pid"
    pidfile.write_text("12345", encoding="utf-8")
    with patch("os.kill", side_effect=PermissionError):
        result = process_control.read_pid(pidfile)
    assert result == 12345


def test_wait_for_exit_returns_true_after_process_disappears(monkeypatch):
    kill_calls: list[tuple[int, int]] = []
    sleep_calls: list[float] = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if len(kill_calls) == 3:
            raise ProcessLookupError

    monkeypatch.setattr(process_control.os, "kill", fake_kill)
    monkeypatch.setattr(process_control.time, "sleep", sleep_calls.append)

    assert process_control.wait_for_exit(123, timeout=1) is True
    assert kill_calls == [(123, 0), (123, 0), (123, 0)]
    assert sleep_calls == [0.1, 0.1]


def test_wait_for_exit_returns_false_on_timeout(monkeypatch):
    kill_calls: list[tuple[int, int]] = []
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        process_control.os,
        "kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )
    monkeypatch.setattr(process_control.time, "sleep", sleep_calls.append)

    assert process_control.wait_for_exit(123, timeout=0.3) is False
    assert kill_calls == [(123, 0), (123, 0), (123, 0)]
    assert sleep_calls == [0.1, 0.1, 0.1]


def test_wait_for_exit_exits_quickly():
    """A PID that's already gone should return True immediately."""
    assert process_control.wait_for_exit(99999999, timeout=1) is True


def test_wait_for_exit_timeout():
    """The current process should still be alive at timeout."""
    assert process_control.wait_for_exit(os.getpid(), timeout=0.3) is False
