"""Tests for the tgcc doctor command."""

import json
import os
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import cmd_doctor
from claude_code_tg.instance_store import (
    instance_name as _instance_name,
    instance_paths as _instance_paths,
)


def test_cmd_doctor_reports_valid_env(monkeypatch, tmp_path, capsys):
    """Doctor should summarize a usable local config without exposing secrets."""
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=123456:ABC",
                "ADMIN_USER_IDS=111",
                "ALLOWED_USER_IDS=222,333",
                f"CLAUDE_PROJECT_DIR={project}",
                "CLAUDE_TIMEOUT=300",
                "QUEUE_MAX_SIZE=3",
                "CLAUDE_PERMISSION_MODE=default",
                "CLAUDE_MODEL=sonnet",
                "CLAUDE_CLI_RESUME_COMPAT=true",
                "ATTACHMENT_MAX_MB=20",
                "ATTACHMENT_MODE=path",
                "ATTACHMENT_RETENTION_DAYS=30",
                "CLAUDE_SKIP_PERMISSIONS=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )

    args = MagicMock()
    args.env = str(env_file)
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "tgcc doctor" in output
    assert "OK   TELEGRAM_BOT_TOKEN: configured" in output
    assert "OK   CLAUDE_MODEL: sonnet" in output
    assert "OK   CLAUDE_CLI_RESUME_COMPAT: true" in output
    assert "OK   ATTACHMENT_RETENTION_DAYS: 30 day(s)" in output
    assert "OK   Runtime permissions:" in output
    assert "OK   Claude Code CLI: found at /usr/bin/claude" in output
    assert "Summary:" in output
    assert "ABC" not in output


def test_cmd_doctor_exits_for_invalid_env(tmp_path, capsys):
    """Doctor should fail fast for config that cannot start the bot."""
    env_file = tmp_path / "bad.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=",
                "ADMIN_USER_IDS=not-an-id",
                "CLAUDE_PROJECT_DIR=/does/not/exist",
                "CLAUDE_MODEL=bad model",
                "ATTACHMENT_MODE=wild",
                "ATTACHMENT_RETENTION_DAYS=soon",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    args = MagicMock()
    args.env = str(env_file)
    with pytest.raises(SystemExit) as exc:
        cmd_doctor(args)

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "FAIL TELEGRAM_BOT_TOKEN: missing" in output
    assert "FAIL ADMIN_USER_IDS:" in output
    assert "FAIL CLAUDE_PROJECT_DIR:" in output
    assert "FAIL CLAUDE_MODEL:" in output
    assert "FAIL ATTACHMENT_MODE:" in output
    assert "FAIL ATTACHMENT_RETENTION_DAYS:" in output


def test_cmd_doctor_fails_for_group_readable_env(monkeypatch, tmp_path, capsys):
    """Doctor fails on broad env permissions: the env file holds the bot token."""
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o644)

    args = MagicMock()
    args.env = str(env_file)
    args.format = "text"
    args.fix_permissions = False
    args.strict = False
    with pytest.raises(SystemExit) as exc:
        cmd_doctor(args)

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "FAIL Env permissions:" in output
    assert "Claude Code CLI" in output


def test_cmd_doctor_strict_exits_for_warning(monkeypatch, tmp_path, capsys):
    """--strict should let scripts fail on warnings, not only hard failures."""
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "QUEUE_MAX_SIZE=0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    args = MagicMock()
    args.env = str(env_file)
    args.strict = True
    with pytest.raises(SystemExit) as exc:
        cmd_doctor(args)

    assert exc.value.code == 1
    assert "WARN QUEUE_MAX_SIZE:" in capsys.readouterr().out


def test_cmd_doctor_json_output_hides_secrets(monkeypatch, tmp_path, capsys):
    """JSON output should be parseable for automation and still avoid raw tokens."""
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=123456:ABC",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    args = MagicMock()
    args.env = str(env_file)
    args.format = "json"
    cmd_doctor(args)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["summary"]["failures"] == 0
    assert any(
        item["name"] == "TELEGRAM_BOT_TOKEN" and item["detail"] == "configured"
        for item in payload["diagnostics"]
    )
    assert "ABC" not in output


def test_cmd_doctor_warns_for_group_readable_runtime_files(
    monkeypatch, tmp_path, capsys
):
    """Doctor should catch stale or hand-created runtime files with broad modes."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    _, logfile = _instance_paths(str(env_file), create=True)
    logfile.write_text("old log\n", encoding="utf-8")
    logfile.chmod(0o644)
    logfile.parent.chmod(0o755)

    args = MagicMock()
    args.env = str(env_file)
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "WARN Runtime permissions:" in output
    assert "tgcc.log" in output
    assert "expected 600" in output
    assert "expected 700" in output


def test_cmd_doctor_fix_permissions_repairs_env_and_runtime_files(
    monkeypatch, tmp_path, capsys
):
    """--fix-permissions narrows local files before the final diagnostics run."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o644)
    _, logfile = _instance_paths(str(env_file), create=True)
    logfile.write_text("old log\n", encoding="utf-8")
    logfile.chmod(0o644)
    logfile.parent.chmod(0o755)

    args = MagicMock()
    args.env = str(env_file)
    args.fix_permissions = True
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "OK   Permission repair:" in output
    assert "WARN Env permissions:" not in output
    assert "WARN Runtime permissions:" not in output
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert logfile.parent.stat().st_mode & 0o777 == 0o700
    assert logfile.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="symlink permission checks are POSIX-only")
def test_cmd_doctor_warns_and_skips_runtime_symlink(monkeypatch, tmp_path, capsys):
    """Doctor should not chmod through symlinked runtime files."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    _, logfile = _instance_paths(str(env_file), create=True)
    target = tmp_path / "outside.log"
    target.write_text("outside\n", encoding="utf-8")
    target.chmod(0o644)
    logfile.symlink_to(target)

    args = MagicMock()
    args.env = str(env_file)
    args.fix_permissions = True
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "OK   Permission repair:" in output
    assert "1 symlink(s) skipped" in output
    assert "WARN Runtime permissions:" in output
    assert "tgcc.log" in output
    assert "is a symlink" in output
    assert target.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name == "nt", reason="symlink permission checks are POSIX-only")
def test_cmd_doctor_warns_and_skips_env_symlink_ancestor(monkeypatch, tmp_path, capsys):
    """Doctor should not report env permissions as OK through a symlinked parent."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    real_env_dir = tmp_path / "real-env"
    linked_env_dir = tmp_path / "linked-env"
    real_env_dir.mkdir()
    try:
        linked_env_dir.symlink_to(real_env_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    env_file = real_env_dir / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o644)

    args = MagicMock()
    args.env = str(linked_env_dir / "bot.env")
    args.fix_permissions = True
    with pytest.raises(SystemExit) as excinfo:
        cmd_doctor(args)

    output = capsys.readouterr().out
    assert excinfo.value.code == 1
    assert "OK   Permission repair:" in output
    assert "symlink(s) skipped" in output
    assert "WARN Env permissions:" in output
    assert "linked-env" in output
    assert "is a symlink in env path" in output
    assert "FAIL TELEGRAM_BOT_TOKEN: missing" in output
    assert "FAIL ADMIN_USER_IDS: missing" in output
    assert env_file.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name == "nt", reason="symlink permission checks are POSIX-only")
def test_cmd_doctor_skips_user_symlinked_runtime_ancestor(
    monkeypatch, tmp_path, capsys
):
    """Doctor repair should not chmod runtime files through a symlinked ancestor."""
    real_tgcc = tmp_path / "real-tgcc"
    link_tgcc = tmp_path / "linked-tgcc"
    real_tgcc.mkdir()
    try:
        link_tgcc.symlink_to(real_tgcc, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", link_tgcc)
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    real_instance_dir = real_tgcc / _instance_name(str(env_file))
    real_instance_dir.mkdir(parents=True)
    logfile = real_instance_dir / "tgcc.log"
    logfile.write_text("old log\n", encoding="utf-8")
    real_instance_dir.chmod(0o755)
    logfile.chmod(0o644)

    args = MagicMock()
    args.env = str(env_file)
    args.fix_permissions = True
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "OK   Permission repair:" in output
    assert "symlink(s) skipped" in output
    assert "WARN Runtime permissions:" in output
    assert "linked-tgcc" in output
    assert "is a symlink in an owner-only path" in output
    assert real_instance_dir.stat().st_mode & 0o777 == 0o755
    assert logfile.stat().st_mode & 0o777 == 0o644


def test_cmd_doctor_warns_for_group_readable_attachment_cache(
    monkeypatch, tmp_path, capsys
):
    """Doctor should include stale attachment caches in runtime permission checks."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    _, logfile = _instance_paths(str(env_file), create=True)

    instance_chat_dir = logfile.parent / "attachments" / "111"
    instance_chat_dir.mkdir(parents=True)
    instance_file = instance_chat_dir / "old.txt"
    instance_file.write_text("old instance attachment\n", encoding="utf-8")
    (logfile.parent / "attachments").chmod(0o755)
    instance_chat_dir.chmod(0o755)
    instance_file.chmod(0o644)

    project_cache_dir = project / ".tgcc-attachments"
    project_chat_dir = project_cache_dir / "222"
    project_chat_dir.mkdir(parents=True)
    project_file = project_chat_dir / "old.txt"
    project_file.write_text("old project attachment\n", encoding="utf-8")
    project_cache_dir.chmod(0o755)
    project_chat_dir.chmod(0o755)
    project_file.chmod(0o644)

    args = MagicMock()
    args.env = str(env_file)
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "WARN Runtime permissions:" in output
    assert "attachments" in output
    assert ".tgcc-attachments" in output
    assert "expected 600" in output
    assert "expected 700" in output


def test_cmd_doctor_fix_permissions_repairs_attachment_cache(
    monkeypatch, tmp_path, capsys
):
    """--fix-permissions should narrow existing attachment cache trees."""
    monkeypatch.setattr("claude_code_tg.instance_store.TGCC_DIR", tmp_path / ".tgcc")
    monkeypatch.setattr(
        "claude_code_tg.diagnostics.shutil.which", lambda _cmd: "/usr/bin/claude"
    )
    project = tmp_path / "project"
    project.mkdir()
    env_file = tmp_path / "bot.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=token",
                "ADMIN_USER_IDS=111",
                f"CLAUDE_PROJECT_DIR={project}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    _, logfile = _instance_paths(str(env_file), create=True)

    instance_cache_dir = logfile.parent / "attachments"
    instance_chat_dir = instance_cache_dir / "111"
    instance_chat_dir.mkdir(parents=True)
    instance_file = instance_chat_dir / "old.txt"
    instance_file.write_text("old instance attachment\n", encoding="utf-8")
    instance_cache_dir.chmod(0o755)
    instance_chat_dir.chmod(0o755)
    instance_file.chmod(0o644)

    project_cache_dir = project / ".tgcc-attachments"
    project_chat_dir = project_cache_dir / "222"
    project_chat_dir.mkdir(parents=True)
    project_file = project_chat_dir / "old.txt"
    project_file.write_text("old project attachment\n", encoding="utf-8")
    project_cache_dir.chmod(0o755)
    project_chat_dir.chmod(0o755)
    project_file.chmod(0o644)

    args = MagicMock()
    args.env = str(env_file)
    args.fix_permissions = True
    cmd_doctor(args)

    output = capsys.readouterr().out
    assert "OK   Permission repair:" in output
    assert "WARN Runtime permissions:" not in output
    assert instance_cache_dir.stat().st_mode & 0o777 == 0o700
    assert instance_chat_dir.stat().st_mode & 0o777 == 0o700
    assert instance_file.stat().st_mode & 0o777 == 0o600
    assert project_cache_dir.stat().st_mode & 0o777 == 0o700
    assert project_chat_dir.stat().st_mode & 0o777 == 0o700
    assert project_file.stat().st_mode & 0o777 == 0o600
