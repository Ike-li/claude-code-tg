"""Shared test helpers for Telegram bot tests."""

from unittest.mock import AsyncMock, MagicMock

from claude_code_tg.bot import TGBot

VALID_SESSION_ID = "123e4567-e89b-12d3-a456-426614174000"


def make_bot(**kwargs) -> TGBot:
    defaults = {
        "token": "123:fake",
        "admin_ids": {111},
        "allowed_ids": {222},
        "project_dir": "/tmp",
        "timeout": 60,
        "queue_max_size": 3,
    }
    defaults.update(kwargs)
    return TGBot(**defaults)


def make_update(
    user_id=222,
    chat_id=222,
    text="hello",
    caption=None,
    document=None,
    photo=None,
    chat_type="private",
    bot_username="testbot",
):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.effective_chat.type = chat_type
    update.message.message_id = 123
    update.message.text = text
    update.message.caption = caption
    update.message.document = document
    update.message.photo = photo or []
    update.message.reply_text = AsyncMock(
        return_value=MagicMock(message_id=321, reply_markup=None)
    )
    update.message.reply_to_message = None
    return update


def make_context(bot_username="testbot", bot_id=999):
    context = MagicMock()
    context.bot.username = bot_username
    context.bot.id = bot_id
    context.bot.send_message = AsyncMock(
        return_value=MagicMock(
            message_id=456,
            edit_text=AsyncMock(),
            delete=AsyncMock(),
        )
    )
    context.bot.send_chat_action = AsyncMock()
    context.bot.send_message_draft = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.get_file = AsyncMock()
    return context


class FakeTelegramFile:
    def __init__(self, content=b"telegram file"):
        self.content = content
        self.downloaded_to_memory = 0

    async def download_to_memory(self, out):
        out.write(self.content)
        self.downloaded_to_memory += 1
