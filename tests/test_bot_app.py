"""Tests for Telegram application wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_tg.bot_app import (
    MAX_CONCURRENT_UPDATES,
    _setup_command_menu,
    _setup_mini_app,
    build_telegram_app,
)
from claude_code_tg.bot_commands import BOT_CONTROL_COMMANDS


class FakeBotRuntime:
    token = "123:fake"
    project_dir = "/tmp"

    def __init__(
        self,
        *,
        attachment_retention_days: float | None = None,
        command_menu_cache_file=None,
        command_menu_enabled: bool = False,
        mini_app_enabled: bool = False,
    ) -> None:
        self.attachment_retention_days = attachment_retention_days
        self.claude_command_map: dict[str, str] = {}
        self.command_menu_cache_file = command_menu_cache_file
        self.command_menu_enabled = command_menu_enabled
        self.mini_app_enabled = mini_app_enabled
        self.mini_app_public_url = "https://example.com/tgcc"
        self.mini_app_menu_text = "tgcc"
        self.start_mini_app = AsyncMock()
        self.stop_mini_app = AsyncMock()

    async def handle_start(self, update, context) -> None: ...

    async def handle_claude_command(self, update, context) -> None: ...

    async def handle_builtin_claude_command(self, update, context) -> None: ...

    async def handle_new(self, update, context) -> None: ...

    async def handle_clear(self, update, context) -> None: ...

    async def handle_attach(self, update, context) -> None: ...

    async def handle_resume(self, update, context) -> None: ...

    async def handle_sessions(self, update, context) -> None: ...

    async def handle_stop_command(self, update, context) -> None: ...

    async def handle_status(self, update, context) -> None: ...

    async def handle_mode(self, update, context) -> None: ...

    async def handle_model(self, update, context) -> None: ...

    async def handle_effort(self, update, context) -> None: ...

    async def handle_permissions(self, update, context) -> None: ...

    async def handle_help(self, update, context) -> None: ...

    async def handle_commands(self, update, context) -> None: ...

    async def handle_run(self, update, context) -> None: ...

    async def handle_forced_reply(self, update, context) -> None: ...

    async def handle_stop_callback(self, update, context) -> None: ...

    async def handle_run_view_callback(self, update, context) -> None: ...

    async def handle_resume_callback(self, update, context) -> None: ...

    async def handle_command_callback(self, update, context) -> None: ...

    async def handle_result_callback(self, update, context) -> None: ...

    async def handle_setting_callback(self, update, context) -> None: ...

    async def handle_message(self, update, context) -> None: ...

    def _restore_sessions(self) -> None: ...

    def _write_status(self) -> None: ...

    def _run_attachment_retention_cleanup(self) -> tuple[int, int, int]:
        return (0, 0, 0)

    def _record_periodic_status(self) -> None: ...


def test_build_telegram_app_registers_expected_handlers() -> None:
    app = build_telegram_app(FakeBotRuntime())

    assert app.concurrent_updates == MAX_CONCURRENT_UPDATES

    command_handlers = [
        handler for handler in app.handlers[0] if hasattr(handler, "commands")
    ]
    commands = [next(iter(handler.commands)) for handler in command_handlers]

    assert commands == [
        "start",
        "new",
        "clear",
        "attach",
        "resume",
        "sessions",
        "context",
        "usage",
        "cost",
        "reload_skills",
        "stop",
        "status",
        "mode",
        "model",
        "effort",
        "permissions",
        "help",
        "commands",
        "run",
    ]
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^stop:"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^run:(detail|compact|page|filter):"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^setting:"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^resume:"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^cmd:"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "CallbackQueryHandler"
        and handler.pattern.pattern == "^result:"
        for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "MessageHandler" for handler in app.handlers[0]
    )
    assert any(
        type(handler).__name__ == "MessageHandler" for handler in app.handlers[-1]
    )


@pytest.mark.asyncio
async def test_post_init_registers_status_job_without_attachment_cleanup() -> None:
    bot = FakeBotRuntime()
    app = build_telegram_app(bot)
    assert app.job_queue is not None
    assert app.post_init is not None

    with (
        patch.object(bot, "_restore_sessions") as restore_sessions,
        patch.object(bot, "_write_status") as write_status,
        patch.object(bot, "_run_attachment_retention_cleanup") as cleanup,
        patch.object(bot, "_record_periodic_status") as record_status,
        patch.object(type(app.job_queue), "run_repeating", autospec=True) as repeating,
        patch("claude_code_tg.bot_app._setup_command_menu", new_callable=AsyncMock),
        patch("claude_code_tg.bot_app._setup_mini_app", new_callable=AsyncMock),
    ):
        await app.post_init(app)

        restore_sessions.assert_called_once_with()
        write_status.assert_called_once_with()
        cleanup.assert_not_called()
        repeating.assert_called_once()
        assert repeating.call_args.kwargs == {"interval": 30, "first": 30}

        status_job = repeating.call_args.args[1]
        await status_job(MagicMock())

    record_status.assert_called_once_with()
    assert app.post_shutdown is not None
    await app.post_shutdown(app)
    bot.stop_mini_app.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_post_init_registers_attachment_cleanup_job_when_enabled() -> None:
    bot = FakeBotRuntime(attachment_retention_days=1)
    app = build_telegram_app(bot)
    assert app.job_queue is not None
    assert app.post_init is not None

    with (
        patch.object(bot, "_restore_sessions") as restore_sessions,
        patch.object(bot, "_write_status") as write_status,
        patch.object(
            bot,
            "_run_attachment_retention_cleanup",
            return_value=(0, 0, 0),
        ) as cleanup,
        patch.object(bot, "_record_periodic_status") as record_status,
        patch.object(type(app.job_queue), "run_repeating", autospec=True) as repeating,
        patch("claude_code_tg.bot_app._setup_command_menu", new_callable=AsyncMock),
        patch("claude_code_tg.bot_app._setup_mini_app", new_callable=AsyncMock),
    ):
        await app.post_init(app)

        restore_sessions.assert_called_once_with()
        write_status.assert_called_once_with()
        cleanup.assert_called_once_with()
        assert repeating.call_count == 2
        status_job, cleanup_job = repeating.call_args_list
        assert status_job.kwargs == {"interval": 30, "first": 30}
        assert cleanup_job.kwargs == {
            "interval": 24 * 60 * 60,
            "first": 24 * 60 * 60,
        }

        await status_job.args[1](MagicMock())
        await cleanup_job.args[1](MagicMock())

    record_status.assert_called_once_with()
    assert cleanup.call_count == 2


@pytest.mark.asyncio
async def test_setup_mini_app_publishes_menu_and_starts_server() -> None:
    bot = FakeBotRuntime(mini_app_enabled=True)
    application = MagicMock()
    application.bot.set_chat_menu_button = AsyncMock()

    await _setup_mini_app(application, bot)

    application.bot.set_chat_menu_button.assert_awaited_once()
    menu = application.bot.set_chat_menu_button.call_args.kwargs["menu_button"]
    assert menu.text == "tgcc"
    assert menu.web_app.url == "https://example.com/tgcc"
    bot.start_mini_app.assert_awaited_once_with(application.bot)


@pytest.mark.asyncio
async def test_setup_command_menu_publishes_and_wires_claude_commands() -> None:
    bot = FakeBotRuntime(command_menu_enabled=True)
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    with patch(
        "claude_code_tg.bot_app.load_or_probe_slash_commands",
        new_callable=AsyncMock,
        return_value=["code-review", "verify", "help", "model", "foo:bar"],
    ):
        await _setup_command_menu(application, bot)

    # Raw interactive built-ins are dropped from the dynamic Claude command map;
    # tgcc-owned wrappers such as /model are published through control commands.
    # "code-review" is normalized to "code_review"; the plugin command "foo:bar"
    # is kept as "foo_bar".
    assert bot.claude_command_map == {
        "code_review": "code-review",
        "verify": "verify",
        "foo_bar": "foo:bar",
    }

    application.add_handler.assert_called_once()
    handler = application.add_handler.call_args[0][0]
    assert set(handler.commands) == {"code_review", "verify", "foo_bar"}

    application.bot.set_my_commands.assert_awaited_once()
    published = application.bot.set_my_commands.call_args[0][0]
    names = [command.command for command in published]
    assert names[: len(BOT_CONTROL_COMMANDS)] == [n for n, _ in BOT_CONTROL_COMMANDS]
    assert "code_review" in names
    assert "verify" in names
    assert "foo_bar" in names


@pytest.mark.asyncio
async def test_setup_command_menu_control_only_when_probe_empty() -> None:
    bot = FakeBotRuntime(command_menu_enabled=True)
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    with patch(
        "claude_code_tg.bot_app.load_or_probe_slash_commands",
        new_callable=AsyncMock,
        return_value=[],
    ):
        await _setup_command_menu(application, bot)

    assert bot.claude_command_map == {}
    application.add_handler.assert_not_called()
    published = application.bot.set_my_commands.call_args[0][0]
    assert [command.command for command in published] == [
        n for n, _ in BOT_CONTROL_COMMANDS
    ]


@pytest.mark.asyncio
async def test_setup_command_menu_skips_probe_when_disabled() -> None:
    bot = FakeBotRuntime(command_menu_enabled=False)
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    with patch(
        "claude_code_tg.bot_app.load_or_probe_slash_commands",
        new_callable=AsyncMock,
    ) as probe:
        await _setup_command_menu(application, bot)

    probe.assert_not_awaited()
    assert bot.claude_command_map == {}
    application.add_handler.assert_not_called()
    published = application.bot.set_my_commands.call_args[0][0]
    assert [command.command for command in published] == [
        n for n, _ in BOT_CONTROL_COMMANDS
    ]


@pytest.mark.asyncio
async def test_setup_command_menu_passes_cache_file_to_loader(tmp_path) -> None:
    cache_file = tmp_path / "command-menu.json"
    bot = FakeBotRuntime(
        command_menu_enabled=True,
        command_menu_cache_file=cache_file,
    )
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    with patch(
        "claude_code_tg.bot_app.load_or_probe_slash_commands",
        new_callable=AsyncMock,
        return_value=["verify", "help"],
    ) as probe:
        await _setup_command_menu(application, bot)

    probe.assert_awaited_once_with("/tmp", cache_file)
    assert bot.claude_command_map == {"verify": "verify"}
    handler = application.add_handler.call_args[0][0]
    assert set(handler.commands) == {"verify"}


@pytest.mark.asyncio
async def test_setup_command_menu_degrades_when_publish_fails() -> None:
    bot = FakeBotRuntime(command_menu_enabled=True)
    application = MagicMock()
    application.bot.set_my_commands = AsyncMock(side_effect=RuntimeError("network"))

    with patch(
        "claude_code_tg.bot_app.load_or_probe_slash_commands",
        new_callable=AsyncMock,
        return_value=["verify"],
    ):
        # Publishing failure must not propagate and must not lose the wiring.
        await _setup_command_menu(application, bot)

    assert bot.claude_command_map == {"verify": "verify"}
    application.add_handler.assert_called_once()
