"""Runtime configuration parsing for the tgcc server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from claude_code_tg.attachments import (
    VALID_ATTACHMENT_MODES,
    normalize_attachment_mode,
    normalize_attachment_retention_days,
)
from claude_code_tg.executor import (
    DEFAULT_TIMEOUT_SECONDS,
    EFFORT_LEVELS,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.utils import parse_env_bool

BYTES_PER_MIB = 1024 * 1024


class ConfigError(ValueError):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    token: str
    admin_ids: set[int]
    allowed_ids: set[int]
    project_dir: str
    timeout: int
    queue_max_size: int
    permission_mode: str | None
    model: str | None
    effort: str | None
    cli_resume_compat: bool
    attachment_max_bytes: int
    attachment_mode: str
    attachment_retention_days: float | None
    command_menu_enabled: bool
    draft_preview_enabled: bool
    mini_app_enabled: bool
    mini_app_public_url: str
    mini_app_host: str
    mini_app_port: int
    mini_app_menu_text: str
    log_interactions: bool


def parse_ids(value: str) -> set[int]:
    if not value.strip():
        return set()
    ids: set[int] = set()
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        parsed = int(stripped)
        if parsed <= 0:
            raise ValueError(f"id must be positive: {stripped}")
        ids.add(parsed)
    return ids


def _parse_int(
    environ: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    value = int(environ.get(key, str(default)))
    if minimum is None:
        return value
    return max(minimum, value)


def _parse_port(environ: Mapping[str, str], key: str, default: int) -> int:
    value = int(environ.get(key, str(default)))
    if not 1 <= value <= 65535:
        raise ValueError(f"{key} must be between 1 and 65535")
    return value


def _validate_mini_app_url(enabled: bool, value: str) -> str:
    url = value.strip()
    if not enabled:
        return url
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(
            "TELEGRAM_MINI_APP_PUBLIC_URL must be an HTTPS URL when Mini App is enabled"
        )
    return url


def load_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    values = os.environ if environ is None else environ

    token = values.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN not set")

    try:
        admin_ids = parse_ids(values.get("ADMIN_USER_IDS", ""))
    except ValueError as exc:
        raise ConfigError(
            "ADMIN_USER_IDS contains non-positive or non-numeric values"
        ) from exc
    if not admin_ids:
        raise ConfigError("ADMIN_USER_IDS not set")

    try:
        allowed_ids = parse_ids(values.get("ALLOWED_USER_IDS", ""))
    except ValueError as exc:
        raise ConfigError(
            "ALLOWED_USER_IDS contains non-positive or non-numeric values"
        ) from exc

    project_dir = os.path.abspath(values.get("CLAUDE_PROJECT_DIR", "."))
    try:
        timeout = _parse_int(
            values,
            "CLAUDE_TIMEOUT",
            DEFAULT_TIMEOUT_SECONDS,
        )
        queue_max_size = _parse_int(values, "QUEUE_MAX_SIZE", 3, minimum=1)
        attachment_max_mb = _parse_int(values, "ATTACHMENT_MAX_MB", 20, minimum=1)
        mini_app_port = _parse_port(values, "TELEGRAM_MINI_APP_PORT", 8787)
    except ValueError as exc:
        raise ConfigError(f"Invalid config value: {exc}") from exc

    try:
        permission_mode = normalize_permission_mode(
            values.get("CLAUDE_PERMISSION_MODE")
        )
    except ValueError as exc:
        raise ConfigError(
            "CLAUDE_PERMISSION_MODE must be one of: default, acceptEdits, plan, "
            "auto, dontAsk, bypassPermissions"
        ) from exc

    try:
        model = normalize_model(values.get("CLAUDE_MODEL"))
    except ValueError as exc:
        raise ConfigError(
            "CLAUDE_MODEL must be a Claude Code model alias or full model name "
            "without whitespace or a leading hyphen"
        ) from exc

    try:
        effort = normalize_effort(values.get("CLAUDE_EFFORT"))
    except ValueError as exc:
        raise ConfigError(
            f"CLAUDE_EFFORT must be one of: {', '.join(EFFORT_LEVELS)}"
        ) from exc

    try:
        attachment_mode = normalize_attachment_mode(values.get("ATTACHMENT_MODE"))
    except ValueError as exc:
        modes = ", ".join(sorted(VALID_ATTACHMENT_MODES))
        raise ConfigError(f"ATTACHMENT_MODE must be one of: {modes}") from exc

    try:
        attachment_retention_days = normalize_attachment_retention_days(
            values.get("ATTACHMENT_RETENTION_DAYS")
        )
    except ValueError as exc:
        raise ConfigError(
            "ATTACHMENT_RETENTION_DAYS must be a non-negative number of days, "
            "or empty/0 to disable automatic cleanup"
        ) from exc

    log_interactions = parse_env_bool(values.get("LOG_INTERACTIONS"))
    cli_resume_compat = parse_env_bool(
        values.get("CLAUDE_CLI_RESUME_COMPAT"),
        default=False,
    )
    command_menu_enabled = parse_env_bool(
        values.get("CLAUDE_COMMAND_MENU"),
        default=False,
    )
    draft_preview_enabled = parse_env_bool(
        values.get("TELEGRAM_DRAFT_PREVIEW"),
        default=False,
    )
    mini_app_enabled = parse_env_bool(
        values.get("TELEGRAM_MINI_APP_ENABLED"),
        default=False,
    )
    mini_app_public_url = _validate_mini_app_url(
        mini_app_enabled,
        values.get("TELEGRAM_MINI_APP_PUBLIC_URL", ""),
    )
    mini_app_host = values.get("TELEGRAM_MINI_APP_HOST", "127.0.0.1").strip()
    if not mini_app_host:
        raise ConfigError("TELEGRAM_MINI_APP_HOST must not be empty")
    mini_app_menu_text = values.get("TELEGRAM_MINI_APP_MENU_TEXT", "tgcc").strip()
    if not mini_app_menu_text:
        raise ConfigError("TELEGRAM_MINI_APP_MENU_TEXT must not be empty")

    if not os.path.isdir(project_dir):
        raise ConfigError(f"CLAUDE_PROJECT_DIR does not exist: {project_dir}")

    return RuntimeConfig(
        token=token,
        admin_ids=admin_ids,
        allowed_ids=allowed_ids,
        project_dir=project_dir,
        timeout=timeout,
        queue_max_size=queue_max_size,
        permission_mode=permission_mode,
        model=model,
        effort=effort,
        cli_resume_compat=cli_resume_compat,
        attachment_max_bytes=attachment_max_mb * BYTES_PER_MIB,
        attachment_mode=attachment_mode,
        attachment_retention_days=attachment_retention_days,
        command_menu_enabled=command_menu_enabled,
        draft_preview_enabled=draft_preview_enabled,
        mini_app_enabled=mini_app_enabled,
        mini_app_public_url=mini_app_public_url,
        mini_app_host=mini_app_host,
        mini_app_port=mini_app_port,
        mini_app_menu_text=mini_app_menu_text,
        log_interactions=log_interactions,
    )
