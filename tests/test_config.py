"""Tests for runtime configuration parsing."""

from pathlib import Path

import pytest

from claude_code_tg.config import ConfigError, load_runtime_config, parse_ids


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", set()),
        ("   ", set()),
        ("123", {123}),
        ("123,456,789", {123, 456, 789}),
        (" 123 , 456 , 789 ", {123, 456, 789}),
        ("123,456,", {123, 456}),
    ],
)
def test_parse_ids_accepts_supported_formats(
    value: str,
    expected: set[int],
) -> None:
    assert parse_ids(value) == expected


def test_parse_ids_reports_non_numeric_values() -> None:
    with pytest.raises(ValueError):
        parse_ids("123,abc")


@pytest.mark.parametrize("value", ["0", "-1", "123,0"])
def test_parse_ids_reports_non_positive_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_ids(value)


def _valid_environment(project: Path) -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "ADMIN_USER_IDS": "111,222",
        "ALLOWED_USER_IDS": "333",
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_TIMEOUT": "42",
        "QUEUE_MAX_SIZE": "0",
        "ATTACHMENT_MAX_MB": "2",
        "ATTACHMENT_MODE": "copy-to-project",
        "ATTACHMENT_RETENTION_DAYS": "0.5",
        "CLAUDE_PERMISSION_MODE": "plan",
        "CLAUDE_MODEL": "sonnet",
        "CLAUDE_EFFORT": "ultracode",
        "CLAUDE_CLI_RESUME_COMPAT": "true",
        "CLAUDE_COMMAND_MENU": "true",
        "TELEGRAM_DRAFT_PREVIEW": "true",
        "TELEGRAM_MINI_APP_ENABLED": "true",
        "TELEGRAM_MINI_APP_PUBLIC_URL": "https://example.com/tgcc",
        "TELEGRAM_MINI_APP_HOST": "127.0.0.1",
        "TELEGRAM_MINI_APP_PORT": "8787",
        "TELEGRAM_MINI_APP_MENU_TEXT": "tgcc",
    }


def test_load_runtime_config_parses_valid_environment(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    config = load_runtime_config(_valid_environment(project))

    assert config.token == "123:abc"
    assert config.admin_ids == {111, 222}
    assert config.allowed_ids == {333}
    assert config.project_dir == str(project.resolve())
    assert config.timeout == 42
    assert config.queue_max_size == 1
    assert config.permission_mode == "plan"
    assert config.model == "sonnet"
    assert config.effort == "ultracode"
    assert config.cli_resume_compat is True
    assert config.attachment_max_bytes == 2 * 1024 * 1024
    assert config.attachment_mode == "copy-to-project"
    assert config.attachment_retention_days == 0.5
    assert config.command_menu_enabled is True
    assert config.draft_preview_enabled is True
    assert config.mini_app_enabled is True
    assert config.mini_app_public_url == "https://example.com/tgcc"
    assert config.mini_app_host == "127.0.0.1"
    assert config.mini_app_port == 8787
    assert config.mini_app_menu_text == "tgcc"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN not set"),
        ({"ADMIN_USER_IDS": ""}, "ADMIN_USER_IDS not set"),
        (
            {"CLAUDE_PERMISSION_MODE": "wild"},
            "CLAUDE_PERMISSION_MODE must be one of",
        ),
        (
            {"CLAUDE_MODEL": "bad model"},
            "CLAUDE_MODEL must be a Claude Code model alias",
        ),
        (
            {"CLAUDE_EFFORT": "extreme"},
            "CLAUDE_EFFORT must be one of",
        ),
        ({"ATTACHMENT_MODE": "wild"}, "ATTACHMENT_MODE must be one of"),
        (
            {"ATTACHMENT_RETENTION_DAYS": "soon"},
            "ATTACHMENT_RETENTION_DAYS must be a non-negative number",
        ),
        (
            {"TELEGRAM_MINI_APP_PUBLIC_URL": "http://example.com/tgcc"},
            "TELEGRAM_MINI_APP_PUBLIC_URL must be an HTTPS URL",
        ),
        (
            {"TELEGRAM_MINI_APP_PORT": "70000"},
            "Invalid config value",
        ),
        (
            {"TELEGRAM_MINI_APP_PORT": "0"},
            "Invalid config value",
        ),
    ],
)
def test_load_runtime_config_reports_invalid_values(
    tmp_path: Path,
    override: dict[str, str],
    expected: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    environ = _valid_environment(project) | override

    with pytest.raises(ConfigError, match=expected):
        load_runtime_config(environ)


def test_load_runtime_config_reports_invalid_admin_ids(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(
        ConfigError,
        match="ADMIN_USER_IDS contains non-positive or non-numeric",
    ):
        load_runtime_config(
            _valid_environment(project) | {"ADMIN_USER_IDS": "111,nope,0"}
        )


def test_load_runtime_config_reports_invalid_allowed_ids(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(
        ConfigError,
        match="ALLOWED_USER_IDS contains non-positive or non-numeric",
    ):
        load_runtime_config(
            _valid_environment(project) | {"ALLOWED_USER_IDS": "333,nope,0"}
        )


def test_load_runtime_config_reports_missing_project_dir(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="CLAUDE_PROJECT_DIR does not exist"):
        load_runtime_config(
            {
                "TELEGRAM_BOT_TOKEN": "123:abc",
                "ADMIN_USER_IDS": "111",
                "CLAUDE_PROJECT_DIR": str(tmp_path / "missing"),
            }
        )


def test_load_runtime_config_disables_command_menu_by_default(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    environ = _valid_environment(project)
    environ.pop("CLAUDE_COMMAND_MENU")

    config = load_runtime_config(environ)

    assert config.command_menu_enabled is False
