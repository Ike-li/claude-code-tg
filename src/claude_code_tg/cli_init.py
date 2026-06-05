"""Interactive tgcc init command."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from claude_code_tg.attachments import (
    VALID_ATTACHMENT_MODES,
    normalize_attachment_mode,
    normalize_attachment_retention_days,
)
from claude_code_tg.executor import (
    EFFORT_LEVELS,
    VALID_PERMISSION_MODES,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.file_security import write_owner_only_text
from claude_code_tg.utils import parse_positive_ids

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


def prompt_env_value(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        print(
            "\nError: tgcc init needs interactive input. Run it in a terminal, "
            "or copy .env.example and edit it manually."
        )
        sys.exit(1)
    return value or default


def prompt_normalized_env_value(
    label: str,
    default: str,
    normalize: Callable[[str | None], str | None],
    *,
    hint: str,
) -> str:
    while True:
        value = prompt_env_value(label, default)
        try:
            normalized = normalize(value)
        except ValueError:
            print(f"Invalid {label}: {hint}.")
            continue
        return normalized or ""


def prompt_bool_env_value(label: str, default: str = "false") -> str:
    while True:
        value = prompt_env_value(label, default)
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return "true"
        if normalized in _FALSE_VALUES:
            return "false"
        print(f"Invalid {label}: use true or false.")


def prompt_id_list_env_value(label: str) -> str:
    while True:
        value = prompt_env_value(label)
        if not value.strip():
            return ""
        ids, invalid = parse_positive_ids(value)
        if invalid or not ids:
            print(f"Invalid {label}: use comma-separated positive numeric IDs.")
            continue
        return ",".join(str(parsed) for parsed in ids)


def prompt_int_env_value(
    label: str,
    default: str,
    *,
    minimum: int | None = None,
) -> str:
    while True:
        value = prompt_env_value(label, default)
        try:
            parsed = int(value)
        except ValueError:
            print(f"Invalid {label}: must be an integer.")
            continue
        if minimum is not None and parsed < minimum:
            print(f"Invalid {label}: must be at least {minimum}.")
            continue
        return str(parsed)


def prompt_attachment_retention_days() -> str:
    while True:
        value = prompt_env_value("ATTACHMENT_RETENTION_DAYS", "")
        try:
            days = normalize_attachment_retention_days(value)
        except ValueError:
            print(
                "Invalid ATTACHMENT_RETENTION_DAYS: must be a non-negative "
                "number of days, or empty/0 to disable."
            )
            continue
        return "" if days is None else f"{days:g}"


def cmd_init(args: argparse.Namespace) -> None:
    """Interactively create a tgcc .env file."""
    env_file = Path(args.env or ".env")
    if env_file.exists() and not args.force:
        print(f"Error: {env_file} already exists. Use --force to overwrite.")
        sys.exit(1)

    full_mode = getattr(args, "full", False)

    if full_mode:
        _init_full(args, env_file)
    else:
        _init_quick(args, env_file)


def _init_quick(args: argparse.Namespace, env_file: Path) -> None:
    """Quick setup: only 3 essential questions, sensible defaults for the rest."""
    print("╭─────────────────────────────────────────────╮")
    print("│        tgcc · 快速配置（3 步）              │")
    print("╰─────────────────────────────────────────────╯")
    print()
    print("你需要提前准备：")
    print("  1. 找 @BotFather 创建 Bot，获取 Token")
    print("  2. 找 @userinfobot 获取你的数字 User ID")
    print()
    print("─" * 46)

    # ── 3 essential questions ──
    print()
    print("❶ Bot Token（从 @BotFather 获取）")
    token = prompt_env_value("TELEGRAM_BOT_TOKEN")
    print()

    print("❷ 你的 Telegram User ID（数字，非 @用户名）")
    print("   从 @userinfobot 获取")
    admin_ids = prompt_id_list_env_value("ADMIN_USER_IDS")
    print()

    print("❸ Claude 要操作的项目目录 [默认: 当前目录]")
    project_dir = prompt_env_value(
        "CLAUDE_PROJECT_DIR", str(Path(".").resolve(strict=False))
    )

    # ── defaults for everything else ──
    print()
    print("─" * 46)
    print("✅ 完成！以下使用默认值，可稍后编辑 .env 修改：")
    print()
    print("   ALLOWED_USER_IDS            (仅你一人)")
    print("   CLAUDE_PERMISSION_MODE      bypassPermissions")
    print("   CLAUDE_MODEL                （Claude Code 默认）")
    print("   CLAUDE_EFFORT               （Claude Code 默认）")
    print("   ATTACHMENT_MODE             path")
    print("   ATTACHMENT_MAX_MB           20")
    print("   CLAUDE_TIMEOUT              300")
    print("   QUEUE_MAX_SIZE              3")
    print()

    content = _build_env_content(
        token=token,
        admin_ids=admin_ids,
        allowed_ids="",
        project_dir=project_dir,
        timeout="300",
        queue_max_size="3",
        permission_mode="bypassPermissions",
        model="",
        effort="",
        cli_resume_compat="false",
        attachment_max_mb="20",
        attachment_mode="path",
        attachment_retention_days="",
        skip_permissions="false",
        log_interactions="false",
        command_menu="false",
        draft_preview="false",
        mini_app_enabled="false",
        mini_app_public_url="",
        mini_app_host="127.0.0.1",
        mini_app_port="8787",
        mini_app_menu_text="tgcc",
    )
    _write_env_file(env_file, content, args)
    _print_post_init(env_file, token, admin_ids)


def _init_full(args: argparse.Namespace, env_file: Path) -> None:
    """Full setup: ask every config option."""
    print("Create tgcc configuration")
    print("Press Enter to accept defaults.")
    print()
    print("TELEGRAM_BOT_TOKEN: create a bot with @BotFather and paste the token.")
    token = prompt_env_value("TELEGRAM_BOT_TOKEN")
    print()
    print(
        "ADMIN_USER_IDS / ALLOWED_USER_IDS are numeric Telegram user IDs, not "
        "@usernames. Message @userinfobot to get yours. Put your own ID in "
        "ADMIN_USER_IDS; add other trusted users to ALLOWED_USER_IDS "
        "(comma-separated)."
    )
    admin_ids = prompt_id_list_env_value("ADMIN_USER_IDS")
    allowed_ids = prompt_id_list_env_value("ALLOWED_USER_IDS")
    project_dir = prompt_env_value(
        "CLAUDE_PROJECT_DIR", str(Path(".").resolve(strict=False))
    )
    timeout = prompt_int_env_value("CLAUDE_TIMEOUT", "300")
    queue_max_size = prompt_int_env_value("QUEUE_MAX_SIZE", "3", minimum=1)
    permission_mode = prompt_normalized_env_value(
        "CLAUDE_PERMISSION_MODE",
        "bypassPermissions",
        normalize_permission_mode,
        hint="must be one of " + ", ".join(sorted(VALID_PERMISSION_MODES)),
    )
    model = prompt_normalized_env_value(
        "CLAUDE_MODEL",
        "",
        normalize_model,
        hint=(
            "must be a Claude Code model alias or full model name without "
            "whitespace or a leading hyphen"
        ),
    )
    effort = prompt_normalized_env_value(
        "CLAUDE_EFFORT",
        "",
        normalize_effort,
        hint="must be one of " + ", ".join(EFFORT_LEVELS),
    )
    cli_resume_compat = prompt_bool_env_value("CLAUDE_CLI_RESUME_COMPAT", "false")
    attachment_max_mb = prompt_int_env_value("ATTACHMENT_MAX_MB", "20", minimum=1)
    attachment_mode = prompt_normalized_env_value(
        "ATTACHMENT_MODE",
        "path",
        normalize_attachment_mode,
        hint="must be one of " + ", ".join(sorted(VALID_ATTACHMENT_MODES)),
    )
    attachment_retention_days = prompt_attachment_retention_days()
    skip_permissions = prompt_bool_env_value("CLAUDE_SKIP_PERMISSIONS", "false")
    log_interactions = prompt_bool_env_value("LOG_INTERACTIONS", "false")
    command_menu = prompt_bool_env_value("CLAUDE_COMMAND_MENU", "false")
    draft_preview = prompt_bool_env_value("TELEGRAM_DRAFT_PREVIEW", "false")
    mini_app_enabled = prompt_bool_env_value("TELEGRAM_MINI_APP_ENABLED", "false")
    mini_app_public_url = prompt_env_value("TELEGRAM_MINI_APP_PUBLIC_URL")
    mini_app_host = prompt_env_value("TELEGRAM_MINI_APP_HOST", "127.0.0.1")
    mini_app_port = prompt_int_env_value(
        "TELEGRAM_MINI_APP_PORT",
        "8787",
        minimum=1,
    )
    mini_app_menu_text = prompt_env_value("TELEGRAM_MINI_APP_MENU_TEXT", "tgcc")

    content = _build_env_content(
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
        attachment_max_mb=attachment_max_mb,
        attachment_mode=attachment_mode,
        attachment_retention_days=attachment_retention_days,
        skip_permissions=skip_permissions,
        log_interactions=log_interactions,
        command_menu=command_menu,
        draft_preview=draft_preview,
        mini_app_enabled=mini_app_enabled,
        mini_app_public_url=mini_app_public_url,
        mini_app_host=mini_app_host,
        mini_app_port=mini_app_port,
        mini_app_menu_text=mini_app_menu_text,
    )
    _write_env_file(env_file, content, args)
    _print_post_init(env_file, token, admin_ids)


def _build_env_content(
    token: str,
    admin_ids: str,
    allowed_ids: str,
    project_dir: str,
    timeout: str,
    queue_max_size: str,
    permission_mode: str,
    model: str,
    effort: str,
    cli_resume_compat: str,
    attachment_max_mb: str,
    attachment_mode: str,
    attachment_retention_days: str,
    skip_permissions: str,
    log_interactions: str,
    command_menu: str,
    draft_preview: str,
    mini_app_enabled: str,
    mini_app_public_url: str,
    mini_app_host: str,
    mini_app_port: str,
    mini_app_menu_text: str,
) -> str:
    return "\n".join(
        [
            "# TG-Claude Code Bridge",
            "# Generated by tgcc init; keep this file 0600 and do not commit it.",
            "# Use one dedicated BotFather token per instance.",
            "# Telegram user IDs are comma-separated numeric IDs; keep admin access narrow.",
            "# CLAUDE_PROJECT_DIR should point at the repo Claude may edit; run tgcc doctor after changes.",
            "# CLAUDE_PERMISSION_MODE defaults to bypassPermissions for trusted local projects.",
            "# Use default or plan before starting on untrusted/shared project directories.",
            "# CLAUDE_CLI_RESUME_COMPAT rewrites tgcc transcript entrypoints so local",
            "# Claude Code /resume may show Telegram-started sessions; off by default.",
            "# ATTACHMENT_MODE=path passes instance cache paths, copy-to-project copies attachments",
            "# into the project, and reject disables Telegram file intake.",
            "# CLAUDE_SKIP_PERMISSIONS is a legacy broad bypass; CLAUDE_SKIP_PERMISSIONS=true is dangerous",
            "# and only for trusted project directories.",
            "# TELEGRAM_DRAFT_PREVIEW streams ephemeral draft previews in private chats; off by default.",
            "# TELEGRAM_MINI_APP_* enables the optional HTTPS Mini App console.",
            f"TELEGRAM_BOT_TOKEN={token}",
            f"ADMIN_USER_IDS={admin_ids}",
            f"ALLOWED_USER_IDS={allowed_ids}",
            f"CLAUDE_PROJECT_DIR={project_dir}",
            f"CLAUDE_TIMEOUT={timeout}",
            f"QUEUE_MAX_SIZE={queue_max_size}",
            f"CLAUDE_PERMISSION_MODE={permission_mode}",
            f"CLAUDE_MODEL={model}",
            f"CLAUDE_EFFORT={effort}",
            f"CLAUDE_CLI_RESUME_COMPAT={cli_resume_compat}",
            f"ATTACHMENT_MAX_MB={attachment_max_mb}",
            f"ATTACHMENT_MODE={attachment_mode}",
            f"ATTACHMENT_RETENTION_DAYS={attachment_retention_days}",
            f"CLAUDE_SKIP_PERMISSIONS={skip_permissions}",
            f"LOG_INTERACTIONS={log_interactions}",
            f"CLAUDE_COMMAND_MENU={command_menu}",
            f"TELEGRAM_DRAFT_PREVIEW={draft_preview}",
            f"TELEGRAM_MINI_APP_ENABLED={mini_app_enabled}",
            f"TELEGRAM_MINI_APP_PUBLIC_URL={mini_app_public_url}",
            f"TELEGRAM_MINI_APP_HOST={mini_app_host}",
            f"TELEGRAM_MINI_APP_PORT={mini_app_port}",
            f"TELEGRAM_MINI_APP_MENU_TEXT={mini_app_menu_text}",
            "",
        ]
    )


def _write_env_file(env_file: Path, content: str, args: argparse.Namespace) -> None:
    try:
        permissions_ok = write_owner_only_text(
            env_file,
            content,
            exclusive=not args.force,
            owner_only_parent=False,
        )
    except FileExistsError:
        print(f"Error: {env_file} already exists. Use --force to overwrite.")
        sys.exit(1)
    except OSError as exc:
        print(f"Error: could not write {env_file}: {exc}")
        sys.exit(1)
    if not permissions_ok:
        print(f"Warning: could not set {env_file} permissions to 0600.")


def _print_post_init(env_file: Path, token: str, admin_ids: str) -> None:
    print(f"✅ 已创建 {env_file}")
    if not token or not admin_ids:
        print("⚠️  TELEGRAM_BOT_TOKEN 和 ADMIN_USER_IDS 是启动的必要条件。")
    if not shutil.which("claude"):
        print("⚠️  未在 PATH 中找到 Claude Code CLI，请先安装并认证。")
    print()
    print("🚀 下一步：")
    print(f"   tgcc doctor --env {env_file}")
    print(f"   tgcc start --env {env_file}")
    print(f"   tgcc status --env {env_file}")
