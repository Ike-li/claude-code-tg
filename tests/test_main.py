"""Tests for server module."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.token_fixtures import telegram_bot_token, url_encoded_telegram_bot_token


def test_parse_ids_reexport_remains_available():
    from claude_code_tg.server import _parse_ids

    assert _parse_ids("123, 456,") == {123, 456}


class TestSensitiveLogFilter:
    def test_redacts_telegram_token_args(self):
        from claude_code_tg.server import _SensitiveLogFilter

        token = telegram_bot_token()
        record = logging.LogRecord(
            name="telegram",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="POST https://api.telegram.org/bot%s/getUpdates",
            args=(token,),
            exc_info=None,
        )

        assert _SensitiveLogFilter().filter(record) is True
        assert token not in record.getMessage()
        assert "***" in record.getMessage()

    def test_redacts_telegram_token_after_log_formatting(self):
        from claude_code_tg.server import _SensitiveLogFilter

        token = telegram_bot_token()
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='HTTP Request: %s %s "HTTP/1.1 %d %s"',
            args=("POST", url, 200, "OK"),
            exc_info=None,
        )

        assert _SensitiveLogFilter().filter(record) is True
        assert token not in record.getMessage()
        assert "bot***" not in record.getMessage()
        assert "***" in record.getMessage()

    def test_redacts_url_encoded_telegram_file_token(self):
        from claude_code_tg.server import _SensitiveLogFilter

        token = url_encoded_telegram_bot_token()
        url = f"https://api.telegram.org/file/bot{token}/documents/file_0.txt"
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='HTTP Request: GET %s "HTTP/1.1 200 OK"',
            args=(url,),
            exc_info=None,
        )

        assert _SensitiveLogFilter().filter(record) is True
        assert token not in record.getMessage()
        assert "bot***" not in record.getMessage()
        assert "***" in record.getMessage()


class TestMainValidation:
    def test_env_permissions_checked_before_dotenv_load(self):
        from claude_code_tg.server import main

        events = []

        def fake_check_env_permissions(paths):
            events.append(("check", tuple(paths)))

        def fake_load_dotenv(path):
            events.append(("load", path))
            raise SystemExit(7)

        with (
            patch.dict(os.environ, {"DOTENV_PATH": "/tmp/tgcc/bot.env"}, clear=True),
            patch(
                "claude_code_tg.utils.check_env_permissions",
                side_effect=fake_check_env_permissions,
            ),
            patch("claude_code_tg.server.load_dotenv", side_effect=fake_load_dotenv),
            pytest.raises(SystemExit) as exc,
        ):
            main()

        assert exc.value.code == 7
        assert events == [
            ("check", (Path("/tmp/tgcc/bot.env"), Path(".env"))),
            ("load", "/tmp/tgcc/bot.env"),
        ]

    def test_symlinked_dotenv_path_rejected_before_dotenv_load(self, tmp_path):
        from claude_code_tg.server import main

        real_env = tmp_path / "real.env"
        real_env.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
        link_env = tmp_path / "linked.env"
        try:
            link_env.symlink_to(real_env)
        except OSError:
            pytest.skip("symlink creation is unavailable")

        with (
            patch.dict(os.environ, {"DOTENV_PATH": str(link_env)}, clear=True),
            patch("claude_code_tg.server.load_dotenv") as load_dotenv,
            pytest.raises(SystemExit) as exc,
        ):
            main()

        assert exc.value.code == 1
        load_dotenv.assert_not_called()

    def test_explicit_dotenv_path_can_load_with_unrelated_default_symlink(
        self, monkeypatch, tmp_path
    ):
        from claude_code_tg.server import main

        explicit_env = tmp_path / "explicit.env"
        explicit_env.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
        real_default = tmp_path / "real-default.env"
        real_default.write_text("TELEGRAM_BOT_TOKEN=456:def\n", encoding="utf-8")
        default_link = tmp_path / ".env"
        try:
            default_link.symlink_to(real_default)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        monkeypatch.chdir(tmp_path)
        events = []

        def fake_check_env_permissions(paths):
            events.append(("check", tuple(paths)))

        def fake_load_dotenv(path):
            events.append(("load", path))
            raise SystemExit(7)

        with (
            patch.dict(os.environ, {"DOTENV_PATH": str(explicit_env)}, clear=True),
            patch(
                "claude_code_tg.utils.check_env_permissions",
                side_effect=fake_check_env_permissions,
            ),
            patch("claude_code_tg.server.load_dotenv", side_effect=fake_load_dotenv),
            pytest.raises(SystemExit) as exc,
        ):
            main()

        assert exc.value.code == 7
        assert events == [
            ("check", (explicit_env, Path(".env"))),
            ("load", str(explicit_env)),
        ]

    def test_missing_claude_cli_exits(self):
        from claude_code_tg.server import main

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value=None),
            pytest.raises(SystemExit),
        ):
            main()

    def test_no_token_exits(self):
        from claude_code_tg.server import main

        env = {"ADMIN_USER_IDS": "123"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_no_admin_exits(self):
        from claude_code_tg.server import main

        env = {"TELEGRAM_BOT_TOKEN": "123:abc"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_bad_project_dir_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "CLAUDE_PROJECT_DIR": "/nonexistent_dir_xyz",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_timeout_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "CLAUDE_TIMEOUT": "notanumber",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_permission_mode_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "CLAUDE_PERMISSION_MODE": "wild",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_model_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "CLAUDE_MODEL": "bad model",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_effort_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "CLAUDE_EFFORT": "extreme",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_attachment_mode_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "ATTACHMENT_MODE": "wild",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_attachment_retention_days_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "ATTACHMENT_RETENTION_DAYS": "soon",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_admin_ids_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "abc",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_invalid_allowed_ids_exits(self):
        from claude_code_tg.server import main

        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111",
            "ALLOWED_USER_IDS": "222,nope",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            pytest.raises(SystemExit),
        ):
            main()

    def test_valid_config_constructs_and_runs_bot(self, tmp_path):
        from claude_code_tg.server import main

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        runtime_dir = tmp_path / "runtime"
        logfile = runtime_dir / "tgcc.log"
        constructed = {}

        class FakeBot:
            def __init__(self, **kwargs):
                constructed["kwargs"] = kwargs

            def run(self):
                constructed["ran"] = True

        env = {
            "DOTENV_PATH": str(tmp_path / "prod.env"),
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ADMIN_USER_IDS": "111, 222",
            "ALLOWED_USER_IDS": "333",
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "CLAUDE_TIMEOUT": "42",
            "QUEUE_MAX_SIZE": "0",
            "ATTACHMENT_MAX_MB": "2",
            "ATTACHMENT_MODE": "copy-to-project",
            "ATTACHMENT_RETENTION_DAYS": "0.5",
            "CLAUDE_PERMISSION_MODE": "plan",
            "CLAUDE_MODEL": "sonnet",
            "CLAUDE_EFFORT": "x-high",
            "CLAUDE_COMMAND_MENU": "true",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("claude_code_tg.utils.check_env_permissions"),
            patch("claude_code_tg.server.load_dotenv"),
            patch("claude_code_tg.server.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "claude_code_tg.instance_store.instance_paths",
                return_value=(runtime_dir / "tgcc.pid", logfile),
            ),
            patch("claude_code_tg.bot.TGBot", FakeBot),
        ):
            main()

        assert constructed["ran"] is True
        assert constructed["kwargs"] == {
            "token": "123:abc",
            "admin_ids": {111, 222},
            "allowed_ids": {333},
            "project_dir": str(project_dir.resolve()),
            "timeout": 42,
            "queue_max_size": 1,
            "permission_mode": "plan",
            "model": "sonnet",
            "effort": "xhigh",
            "attachment_max_bytes": 2 * 1024 * 1024,
            "attachment_mode": "copy-to-project",
            "attachment_retention_days": 0.5,
            "command_menu_enabled": True,
            "draft_preview_enabled": False,
            "mini_app_enabled": False,
            "mini_app_public_url": "",
            "mini_app_host": "127.0.0.1",
            "mini_app_port": 8787,
            "mini_app_menu_text": "tgcc",
            "cli_resume_compat": False,
            "status_file": runtime_dir / "status.json",
        }
