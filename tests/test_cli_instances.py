"""Tests for multi-instance CLI helpers."""

from contextlib import ExitStack
from pathlib import Path

import pytest

from claude_code_tg.cli_instances import (
    _open_log_followers,
    format_env_list as _format_env_list,
    print_instance_log_tail as _print_instance_log_tail,
    print_status_for_env as _print_status_for_env,
    resolve_single_env as _resolve_single_env,
    rewind_if_truncated as _rewind_if_truncated,
    show_instance_logs as _show_instance_logs,
)
from claude_code_tg.instance_store import instance_paths as _instance_paths


def test_format_env_list_uses_filenames_only(tmp_path):
    """Multi-env prompts should stay compact and avoid full local paths."""
    env_files = [tmp_path / "prod.env", tmp_path / "dev.env"]

    assert _format_env_list(env_files) == "prod.env, dev.env"


def test_rewind_if_truncated_seeks_to_start_when_file_shrank(tmp_path):
    logfile = tmp_path / "tgcc.log"
    logfile.write_text("a\nb\nc\n")
    with logfile.open("r") as f:
        f.seek(0, 2)  # move to end (offset > current size after truncation)
        logfile.write_text("x\n")  # rotate: new file is smaller
        _rewind_if_truncated(logfile, f)
        assert f.tell() == 0


def test_rewind_if_truncated_keeps_position_when_file_grew(tmp_path):
    logfile = tmp_path / "tgcc.log"
    logfile.write_text("a\n")
    with logfile.open("r") as f:
        f.read()
        pos = f.tell()
        with logfile.open("a") as appender:
            appender.write("b\n")
        _rewind_if_truncated(logfile, f)
        assert f.tell() == pos


def test_resolve_single_env_uses_implicit_only_env(monkeypatch, tmp_path):
    """Single-env directories can omit --env for one-instance commands."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "only.env").write_text("TOKEN=test")

    assert _resolve_single_env(None, command="logs") == Path("only.env")


def test_resolve_single_env_prefers_default_env(monkeypatch, tmp_path):
    """A local .env remains the default even when other env files exist."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TOKEN=default")
    (tmp_path / "prod.env").write_text("TOKEN=prod")

    assert _resolve_single_env(None, command="logs") == Path(".env")


def test_resolve_single_env_returns_default_candidate_without_env_files(
    monkeypatch, tmp_path
):
    """Commands keep reporting .env as the candidate when no env file exists yet."""
    monkeypatch.chdir(tmp_path)

    assert _resolve_single_env(None, command="start") == Path(".env")


def test_resolve_single_env_rejects_ambiguous_logs(monkeypatch, tmp_path, capsys):
    """Ambiguous multi-env commands should print a command-specific hint."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prod.env").write_text("TOKEN=prod")
    (tmp_path / "dev.env").write_text("TOKEN=dev")

    with pytest.raises(SystemExit) as exc:
        _resolve_single_env(None, command="logs")

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Multiple .env files found: dev.env, prod.env" in output
    assert "tgcc logs --env <file>" in output


@pytest.mark.parametrize(
    ("command", "hint", "forbidden"),
    [
        ("start", "tgcc start-all", None),
        ("status", "tgcc status --all", "status-all"),
        ("doctor", "tgcc doctor --env <file>", "doctor-all"),
        ("foreground", "tgcc foreground --env <file>", None),
        (
            "attachments prune",
            "tgcc attachments prune --all-envs",
            "attachments prune-all",
        ),
        ("restart", "tgcc restart-all", None),
    ],
)
def test_resolve_single_env_rejects_ambiguous_commands_with_real_hints(
    monkeypatch, tmp_path, capsys, command, hint, forbidden
):
    """Multi-env guidance should point to commands and flags that really exist."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prod.env").write_text("TOKEN=prod")
    (tmp_path / "dev.env").write_text("TOKEN=dev")

    with pytest.raises(SystemExit) as exc:
        _resolve_single_env(None, command=command)

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert hint in output
    if forbidden:
        assert forbidden not in output


def test_print_instance_log_tail_prefixes_recent_lines(monkeypatch, tmp_path, capsys):
    """Multi-instance log tails should label only the requested recent lines."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=test")
    _, logfile = _instance_paths(str(env_file))
    logfile.write_text("old\nnew\n", encoding="utf-8")

    _print_instance_log_tail(env_file, lines=1)

    output = capsys.readouterr().out
    assert f"== {env_file.name} | {logfile} ==" in output
    assert "[bot.env] new" in output
    assert "[bot.env] old" not in output


def test_print_instance_log_tail_reports_missing_log(monkeypatch, tmp_path, capsys):
    """A missing log should produce a clear per-instance message."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=test")
    _, logfile = _instance_paths(str(env_file), create=False)

    _print_instance_log_tail(env_file, lines=10)

    output = capsys.readouterr().out
    assert f"== {env_file.name} | {logfile} ==" in output
    assert "[bot.env] No log file found." in output


def test_open_log_followers_opens_existing_logs_at_end(monkeypatch, tmp_path):
    """Follow mode should start at EOF so historical lines are not replayed."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=test")
    _, logfile = _instance_paths(str(env_file))
    logfile.write_text("old\n", encoding="utf-8")

    with ExitStack() as stack:
        followers = _open_log_followers([env_file], stack)

        assert [(label, path) for label, path, _ in followers] == [("bot.env", logfile)]
        assert followers[0][2].tell() == logfile.stat().st_size


def test_open_log_followers_reports_missing_logs(monkeypatch, tmp_path, capsys):
    """Follow mode should skip missing logs without creating runtime dirs."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    env_file = tmp_path / "bot.env"
    env_file.write_text("TOKEN=test")
    _, logfile = _instance_paths(str(env_file), create=False)

    with ExitStack() as stack:
        followers = _open_log_followers([env_file], stack)

    assert followers == []
    assert not logfile.parent.exists()
    assert "[bot.env] No log file found." in capsys.readouterr().out


def test_show_instance_logs_follow_stops_cleanly_on_keyboard_interrupt(
    monkeypatch, tmp_path, capsys
):
    """Follow mode should exit quietly when the operator presses Ctrl+C."""
    log_file = tmp_path / "tgcc.log"
    log_file.write_text("", encoding="utf-8")

    class InterruptingLog:
        def readline(self):
            return ""

        def tell(self):
            return 0

    monkeypatch.setattr(
        "claude_code_tg.cli_instances._open_log_followers",
        lambda _env_files, _stack: [("bot.env", log_file, InterruptingLog())],
    )
    monkeypatch.setattr(
        "claude_code_tg.cli_instances.time.sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    _show_instance_logs([tmp_path / "bot.env"], lines=0, follow=True)

    assert "Following logs. Press Ctrl+C to stop." in capsys.readouterr().out


def test_print_status_for_env_uses_running_instances(monkeypatch, tmp_path, capsys):
    """Status summaries should show pid and log path without reading logs."""
    env_file = tmp_path / "bot.env"
    _, logfile = _instance_paths(str(env_file), create=False)
    monkeypatch.setattr(
        "claude_code_tg.cli_instances.running_instances",
        lambda _env: [(1234, tmp_path / "tgcc.pid", logfile)],
    )

    _print_status_for_env(env_file, width=8)

    output = capsys.readouterr().out
    assert "bot.env" in output
    assert "Running (PID 1234)" in output
    assert f"Logs: {logfile}" in output
