"""Telegram application wiring for TGBot."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from telegram import BotCommand, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    JobQueue,
    MessageHandler,
    filters,
)

from claude_code_tg.bot_commands import (
    BOT_CONTROL_COMMANDS,
    RESERVED_BOT_COMMAND_NAMES,
)
from claude_code_tg.command_menu import (
    build_claude_menu,
    load_or_probe_slash_commands,
)

logger = logging.getLogger(__name__)

ATTACHMENT_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60
# Telegram caps the bot command menu at 100 entries.
MAX_TELEGRAM_MENU_COMMANDS = 100
# Concurrent update handling lets Stop callbacks and follow-up messages be
# processed while a Claude subprocess is running. Per-chat run serialization
# still lives in ChatSessionStore busy/queue state.
MAX_CONCURRENT_UPDATES = 8
# Guard the invariant that a full menu (control + Claude commands) always fits.
assert len(BOT_CONTROL_COMMANDS) <= MAX_TELEGRAM_MENU_COMMANDS


class TelegramBotRuntime(Protocol):
    token: str
    attachment_retention_days: float | None
    command_menu_cache_file: Path | None
    command_menu_enabled: bool
    mini_app_enabled: bool
    mini_app_public_url: str
    mini_app_menu_text: str
    project_dir: str
    claude_command_map: dict[str, str]

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_attach(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_stop_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_mode(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_model(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_effort(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_permissions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_run(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_forced_reply(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_commands(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_stop_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_run_view_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_resume_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_command_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_result_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_setting_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_claude_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    async def handle_builtin_claude_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None: ...

    def _restore_sessions(self) -> None: ...

    def _write_status(self) -> None: ...

    def _run_attachment_retention_cleanup(self) -> tuple[int, int, int]: ...

    def _record_periodic_status(self) -> None: ...

    async def start_mini_app(self, telegram_bot: object) -> None: ...

    async def stop_mini_app(self) -> None: ...


def build_telegram_app(bot: TelegramBotRuntime) -> Application:
    async def post_init(application: Application) -> None:
        bot._restore_sessions()
        bot._write_status()
        if bot.attachment_retention_days is not None:
            bot._run_attachment_retention_cleanup()
        if application.job_queue:

            async def periodic_status(_context: ContextTypes.DEFAULT_TYPE) -> None:
                bot._record_periodic_status()

            application.job_queue.run_repeating(periodic_status, interval=30, first=30)
            if bot.attachment_retention_days is not None:

                async def attachment_cleanup(
                    _context: ContextTypes.DEFAULT_TYPE,
                ) -> None:
                    bot._run_attachment_retention_cleanup()

                application.job_queue.run_repeating(
                    attachment_cleanup,
                    interval=ATTACHMENT_CLEANUP_INTERVAL_SECONDS,
                    first=ATTACHMENT_CLEANUP_INTERVAL_SECONDS,
                )

        await _setup_command_menu(application, bot)
        if bot.mini_app_enabled:
            await _setup_mini_app(application, bot)

    async def post_shutdown(_application: Application) -> None:
        await bot.stop_mini_app()

    app: Application = (
        Application.builder()
        .token(bot.token)
        .job_queue(JobQueue())
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(MAX_CONCURRENT_UPDATES)
        .connection_pool_size(MAX_CONCURRENT_UPDATES + 4)
        # Proxied connections to api.telegram.org can be slow to handshake;
        # the PTB defaults (5s) drop messages on transient proxy jitter.
        .connect_timeout(20.0)
        .read_timeout(20.0)
        .write_timeout(20.0)
        .pool_timeout(5.0)
        .build()
    )

    app.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, bot.handle_forced_reply),
        group=-1,
    )
    app.add_handler(CommandHandler("start", bot.handle_start))
    app.add_handler(CommandHandler("new", bot.handle_new))
    app.add_handler(CommandHandler("clear", bot.handle_clear))
    app.add_handler(CommandHandler("attach", bot.handle_attach))
    app.add_handler(CommandHandler("resume", bot.handle_resume))
    app.add_handler(CommandHandler("sessions", bot.handle_sessions))
    app.add_handler(CommandHandler("context", bot.handle_builtin_claude_command))
    app.add_handler(CommandHandler("usage", bot.handle_builtin_claude_command))
    app.add_handler(CommandHandler("cost", bot.handle_builtin_claude_command))
    app.add_handler(CommandHandler("reload_skills", bot.handle_builtin_claude_command))
    app.add_handler(CommandHandler("stop", bot.handle_stop_command))
    app.add_handler(CommandHandler("status", bot.handle_status))
    app.add_handler(CommandHandler("mode", bot.handle_mode))
    app.add_handler(CommandHandler("model", bot.handle_model))
    app.add_handler(CommandHandler("effort", bot.handle_effort))
    app.add_handler(CommandHandler("permissions", bot.handle_permissions))
    app.add_handler(CommandHandler("help", bot.handle_help))
    app.add_handler(CommandHandler("commands", bot.handle_commands))
    app.add_handler(CommandHandler("run", bot.handle_run))
    app.add_handler(
        CallbackQueryHandler(
            bot.handle_run_view_callback,
            pattern=r"^run:(detail|compact|page|filter):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(bot.handle_setting_callback, pattern=r"^setting:")
    )
    app.add_handler(
        CallbackQueryHandler(bot.handle_resume_callback, pattern=r"^resume:")
    )
    app.add_handler(CallbackQueryHandler(bot.handle_command_callback, pattern=r"^cmd:"))
    app.add_handler(
        CallbackQueryHandler(bot.handle_result_callback, pattern=r"^result:")
    )
    app.add_handler(CallbackQueryHandler(bot.handle_stop_callback, pattern=r"^stop:"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.Document.ALL,
            bot.handle_message,
        )
    )

    return app


async def _setup_mini_app(application: Application, bot: TelegramBotRuntime) -> None:
    menu = MenuButtonWebApp(
        text=bot.mini_app_menu_text,
        web_app=WebAppInfo(url=bot.mini_app_public_url),
    )
    try:
        await application.bot.set_chat_menu_button(menu_button=menu)
    except Exception:
        logger.exception("Failed to publish Telegram Mini App menu button")
    await bot.start_mini_app(application.bot)


async def _setup_command_menu(
    application: Application, bot: TelegramBotRuntime
) -> None:
    """Publish the Telegram command menu and wire tappable Claude commands.

    Always publishes the bot's control commands. When Claude command menu support
    is enabled, also loads/probes project slash commands, registers a handler so
    menu taps execute them, and adds them to the menu. Any load/probe/publish
    failure degrades to a control-only menu so bot startup is never blocked.
    """
    control = [BotCommand(name, desc) for name, desc in BOT_CONTROL_COMMANDS]
    reserved = set(RESERVED_BOT_COMMAND_NAMES)

    claude_entries = []
    if bot.command_menu_enabled:
        try:
            probed = await load_or_probe_slash_commands(
                bot.project_dir,
                bot.command_menu_cache_file,
            )
            claude_entries = build_claude_menu(
                probed,
                reserved,
                limit=MAX_TELEGRAM_MENU_COMMANDS - len(control),
            )
        except Exception:
            logger.exception("Failed to prepare Claude slash commands for menu")
    else:
        logger.info("Claude command menu probing is disabled")

    bot.claude_command_map = {e.tg_name: e.claude_command for e in claude_entries}
    if claude_entries:
        application.add_handler(
            CommandHandler(
                [e.tg_name for e in claude_entries], bot.handle_claude_command
            )
        )

    commands = control + [BotCommand(e.tg_name, e.description) for e in claude_entries]
    try:
        await application.bot.set_my_commands(commands[:MAX_TELEGRAM_MENU_COMMANDS])
    except Exception:
        logger.exception("Failed to publish Telegram command menu")
        return

    logger.info(
        "Command menu published: %d control + %d Claude command(s)",
        len(control),
        len(claude_entries),
    )
