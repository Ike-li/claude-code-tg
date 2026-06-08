"""TG-Claude Code Bridge - Entry point."""

import logging
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from claude_code_tg.config import (
    ConfigError,
    load_runtime_config,
    parse_ids as _parse_ids,
)

__all__ = ["_SensitiveLogFilter", "_parse_ids", "main"]


class _SensitiveLogFilter(logging.Filter):
    """Redact known secrets before log records reach file handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        from claude_code_tg.sanitizer import sanitize

        record.msg = sanitize(record.getMessage())
        record.args = ()
        return True


def _configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, _SensitiveLogFilter) for f in handler.filters):
            handler.addFilter(_SensitiveLogFilter())
    return logging.getLogger(__name__)


def _env_paths_to_check(dotenv_path: str | None) -> list[Path]:
    env_paths = dict.fromkeys([dotenv_path or ".env", ".env"])
    return [Path(path) for path in env_paths]


def _env_path_to_load(dotenv_path: str | None) -> Path:
    return Path(dotenv_path or ".env")


def _reject_symlinked_env_paths(
    env_paths: list[Path],
    logger: logging.Logger,
) -> None:
    from claude_code_tg.file_security import rejectable_symlink_path_component

    for env_path in env_paths:
        symlink = rejectable_symlink_path_component(env_path)
        if not symlink:
            continue
        logger.error(
            "Env path %s contains a symlink (%s); refusing to load",
            env_path,
            symlink,
        )
        sys.exit(1)


def main() -> None:
    dotenv_path = os.environ.get("DOTENV_PATH")
    logger = _configure_logging()

    from claude_code_tg.utils import check_env_permissions

    env_paths = _env_paths_to_check(dotenv_path)
    _reject_symlinked_env_paths([_env_path_to_load(dotenv_path)], logger)
    check_env_permissions(env_paths)
    load_dotenv(dotenv_path)

    # Check claude CLI exists
    if not shutil.which("claude"):
        logger.error(
            "Claude Code CLI not found. Install it first: https://docs.anthropic.com/en/docs/claude-code"
        )
        sys.exit(1)

    try:
        config = load_runtime_config()
    except ConfigError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if config.log_interactions:
        from claude_code_tg import interaction_log

        interaction_log.enable()
        logger.info("Interaction logging enabled (LOG_INTERACTIONS=true)")

    from claude_code_tg.bot import TGBot
    from claude_code_tg.container import ServiceContainer
    from claude_code_tg.instance_store import instance_paths

    _, logfile = instance_paths(dotenv_path or ".env")
    status_file = logfile.parent / "status.json"

    # 使用依赖注入容器创建服务
    container = ServiceContainer.create_default(
        project_dir=config.project_dir,
        timeout=config.timeout,
        queue_max_size=config.queue_max_size,
        permission_mode=config.permission_mode,
        model=config.model,
        effort=config.effort,
        status_file=status_file,
        cli_resume_compat=config.cli_resume_compat,
        draft_preview_enabled=config.draft_preview_enabled,
    )

    # 使用容器创建 bot
    bot = TGBot(
        token=config.token,
        admin_ids=config.admin_ids,
        allowed_ids=config.allowed_ids,
        container=container,
        allowed_chat_ids=config.allowed_chat_ids,
        attachment_max_bytes=config.attachment_max_bytes,
        attachment_mode=config.attachment_mode,
        attachment_retention_days=config.attachment_retention_days,
        command_menu_enabled=config.command_menu_enabled,
        mini_app_enabled=config.mini_app_enabled,
        mini_app_public_url=config.mini_app_public_url,
        mini_app_host=config.mini_app_host,
        mini_app_port=config.mini_app_port,
        mini_app_menu_text=config.mini_app_menu_text,
        status_file=status_file,
    )

    logger.info(
        "Starting bot | project_dir=%s | admins=%s | permission_mode=%s | model=%s | effort=%s | cli_resume_compat=%s",
        config.project_dir,
        config.admin_ids,
        config.permission_mode or "claude-default",
        config.model or "claude-default",
        config.effort or "claude-default",
        config.cli_resume_compat,
    )
    bot.run()


if __name__ == "__main__":
    main()
