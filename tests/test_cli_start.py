"""Tests for the tgcc start command."""

import os
import signal
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import _last_error_lines, _status_file_ready, cmd_start
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_start_creates_pidfile(monkeypatch, tmp_path):
    """Mock subprocess.Popen, verify pidfile written."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)
    monkeypatch.setattr(
        "claude_code_tg.cli._wait_for_startup_ready",
        lambda *_args, **_kwargs: (True, None),
    )

    args = MagicMock()
    args.env = str(env_file)
    cmd_start(args)

    pidfile, logfile = _instance_paths(str(env_file))
    assert pidfile.exists()
    assert pidfile.read_text() == "12345"
    assert pidfile.stat().st_mode & 0o777 == 0o600
    assert logfile.stat().st_mode & 0o777 == 0o600
    assert (pidfile.parent / "instance.json").stat().st_mode & 0o777 == 0o600


def test_status_file_ready_requires_fresh_timestamp(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text('{"timestamp": 100}', encoding="utf-8")

    assert _status_file_ready(status_file, launched_at=99) is True
    assert _status_file_ready(status_file, launched_at=101) is False


def test_cmd_start_exits_when_claude_cli_missing(monkeypatch, capsys):
    """Start should fail before touching env/runtime files when claude is absent."""
    monkeypatch.setattr("shutil.which", lambda _name: None)

    args = MagicMock()
    args.env = "missing.env"
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    assert exc.value.code == 1
    assert "Claude Code CLI not found" in capsys.readouterr().out


def test_cmd_start_already_running(monkeypatch, tmp_path):
    """Existing valid PID file -> SystemExit."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    # Create a valid PID file (current process)
    pidfile, _ = _instance_paths(str(env_file))
    pidfile.write_text(str(os.getpid()))

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit):
        cmd_start(args)


def test_cmd_start_missing_env_does_not_migrate_legacy(monkeypatch, tmp_path):
    """A bad env path must fail before touching legacy instance files."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "missing.env"
    legacy_dir = tmp_path / "missing"
    legacy_dir.mkdir()
    (legacy_dir / "tgcc.log").write_text("legacy log\n")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    assert exc.value.code == 1
    assert (legacy_dir / "tgcc.log").exists()
    assert not (tmp_path / _instance_name(str(env_file))).exists()


def test_cmd_start_rejects_symlinked_env_before_runtime_files(
    monkeypatch, tmp_path, capsys
):
    """Start should not resolve a symlinked env path into a trusted target."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    real_env = tmp_path / "real.env"
    real_env.write_text("TOKEN=test", encoding="utf-8")
    link_env = tmp_path / "linked.env"
    try:
        link_env.symlink_to(real_env)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")

    args = MagicMock()
    args.env = str(link_env)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    assert exc.value.code == 1
    assert "env path contains a symlink" in capsys.readouterr().out
    assert not (tmp_path / _instance_name(str(link_env))).exists()


def test_cmd_start_rejects_legacy_running_instance(monkeypatch, tmp_path):
    """A pre-hash instance dir must still prevent duplicate polling."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    (legacy_dir / "tgcc.pid").write_text(str(os.getpid()))
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit):
        cmd_start(args)


def test_cmd_start_migrates_stale_legacy_instance(monkeypatch, tmp_path):
    """Stopped legacy files should move to the hashed instance dir before start."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    legacy_dir = tmp_path / "test"
    legacy_dir.mkdir()
    (legacy_dir / "tgcc.pid").write_text("99999999")
    (legacy_dir / "tgcc.log").write_text("legacy log\n")
    (legacy_dir / "status.json").write_text('{"sessions": 1}')
    (legacy_dir / "instance.json").write_text('{"env_path": "old"}')

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)
    monkeypatch.setattr(
        "claude_code_tg.cli._wait_for_startup_ready",
        lambda *_args, **_kwargs: (True, None),
    )

    args = MagicMock()
    args.env = str(env_file)
    cmd_start(args)

    pidfile, logfile = _instance_paths(str(env_file))
    assert pidfile.read_text() == "12345"
    # The migrated legacy log is archived (start always begins a fresh tgcc.log);
    # its content lives on in a timestamped archive next to it.
    archives = list(logfile.parent.glob("tgcc.log.*"))
    assert len(archives) == 1
    assert "legacy log" in archives[0].read_text()
    assert (logfile.parent / "status.json").read_text() == '{"sessions": 1}'
    if os.name != "nt":
        assert logfile.stat().st_mode & 0o777 == 0o600
        assert (logfile.parent / "status.json").stat().st_mode & 0o777 == 0o600
    assert not legacy_dir.exists()


def test_cmd_start_reports_runtime_file_prepare_error(monkeypatch, tmp_path, capsys):
    """Runtime path failures should be surfaced before launching a child process."""
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli._running_instances", lambda _env: [])
    monkeypatch.setattr(
        "claude_code_tg.cli._instance_paths", MagicMock(side_effect=OSError("readonly"))
    )

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "could not prepare runtime files" in output
    assert "readonly" in output


def test_cmd_start_terminates_child_when_pidfile_write_fails(
    monkeypatch, tmp_path, capsys
):
    """A started child must not survive without a recorded owner-only pidfile."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)
    monkeypatch.setattr(
        "claude_code_tg.cli._wait_for_startup_ready",
        lambda *_args, **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        "claude_code_tg.cli._write_owner_only_text",
        MagicMock(side_effect=OSError("pid path replaced")),
    )
    signals: list[signal.Signals] = []
    monkeypatch.setattr(
        "claude_code_tg.cli._send_signal_to_process_tree",
        lambda pid, sig: signals.append(sig),
    )
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda pid, timeout: True)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    output = capsys.readouterr().out
    pidfile, logfile = _instance_paths(str(env_file))
    assert exc.value.code == 1
    assert signals == [signal.SIGTERM]
    assert not pidfile.exists()
    assert logfile.exists()
    assert "could not record runtime files" in output
    assert "pid path replaced" in output


def test_cmd_start_terminates_child_when_metadata_write_fails(
    monkeypatch, tmp_path, capsys
):
    """Metadata failures must not be swallowed after the child starts."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)
    monkeypatch.setattr(
        "claude_code_tg.cli._wait_for_startup_ready",
        lambda *_args, **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        "claude_code_tg.cli._write_instance_metadata",
        MagicMock(side_effect=OSError("metadata path replaced")),
    )
    signals: list[signal.Signals] = []
    monkeypatch.setattr(
        "claude_code_tg.cli._send_signal_to_process_tree",
        lambda pid, sig: signals.append(sig),
    )
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda pid, timeout: True)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    output = capsys.readouterr().out
    pidfile, logfile = _instance_paths(str(env_file))
    assert exc.value.code == 1
    assert signals == [signal.SIGTERM]
    assert not pidfile.exists()
    assert logfile.exists()
    assert "could not record runtime files" in output
    assert "metadata path replaced" in output


def test_last_error_lines_returns_sanitized_error_log_lines(tmp_path):
    """The start-failure helper extracts [ERROR] lines so start can echo them."""
    logfile = tmp_path / "tgcc.log"
    logfile.write_text(
        "2026-06-05 10:00:00 [INFO] server: starting up\n"
        "2026-06-05 10:00:01 [ERROR] config: ADMIN_USER_IDS not set\n"
        "2026-06-05 10:00:02 [INFO] server: shutting down\n",
        encoding="utf-8",
    )
    reasons = _last_error_lines(logfile)
    assert len(reasons) == 1
    assert "ADMIN_USER_IDS not set" in reasons[0]
    assert "[INFO]" not in reasons[0]


def test_last_error_lines_missing_file_returns_empty(tmp_path):
    assert _last_error_lines(tmp_path / "nope.log") == []


def test_cmd_start_echoes_error_reason_from_log(monkeypatch, tmp_path, capsys):
    """When the detached server logs a ConfigError, start should echo it."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "bad.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = 1
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)

    _, logfile = _instance_paths(str(env_file), create=True)

    def fake_ready(_proc, _status, **_kwargs):
        logfile.write_text(
            "2026-06-05 10:00:01 [ERROR] config: ADMIN_USER_IDS not set\n",
            encoding="utf-8",
        )
        return (False, 1)

    monkeypatch.setattr("claude_code_tg.cli._wait_for_startup_ready", fake_ready)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Failed to start" in output
    assert "Reason:" in output
    assert "ADMIN_USER_IDS not set" in output


def test_cmd_start_fails_if_server_exits_immediately(monkeypatch, tmp_path, capsys):
    """Immediate child exit should be reported as start failure, not as Started."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "bad.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = 1
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    pidfile, _ = _instance_paths(str(env_file), create=False)
    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Failed to start" in captured.out
    assert not pidfile.exists()


def test_cmd_start_terminates_child_when_startup_status_missing(
    monkeypatch, tmp_path, capsys
):
    """A child that never writes fresh status must not be reported as started."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "bad.env"
    env_file.write_text("TOKEN=test")

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    monkeypatch.setattr("subprocess.Popen", MagicMock(return_value=mock_proc))
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_READY_TIMEOUT_SECONDS", 0)
    signals: list[signal.Signals] = []
    monkeypatch.setattr(
        "claude_code_tg.cli._send_signal_to_process_tree",
        lambda pid, sig: signals.append(sig),
    )
    monkeypatch.setattr("claude_code_tg.cli._wait_for_exit", lambda pid, timeout: True)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    pidfile, _ = _instance_paths(str(env_file), create=False)
    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert signals == [signal.SIGTERM]
    assert "startup status was not written" in output
    assert not pidfile.exists()


def test_cmd_start_reports_server_launch_error(monkeypatch, tmp_path, capsys):
    """Popen failures should be reported without a traceback or stale pidfile."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path)
    env_file = tmp_path / "bad.env"
    env_file.write_text("TOKEN=test")

    monkeypatch.setattr("subprocess.Popen", MagicMock(side_effect=OSError("no exec")))
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/claude")
    monkeypatch.setattr("claude_code_tg.cli.STARTUP_CHECK_SECONDS", 0)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_start(args)

    pidfile, logfile = _instance_paths(str(env_file), create=False)
    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "could not launch tgcc server" in output
    assert "no exec" in output
    assert str(logfile) in output
    assert not pidfile.exists()
