"""Telegram outbound message helpers."""

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes

MAX_TG_MESSAGE_LENGTH = 4000


async def send_pages(
    chat_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    limit: int = MAX_TG_MESSAGE_LENGTH,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send text, splitting at newline boundaries if too long.

    ``reply_markup``, when given, is attached to the final page only.
    """
    if not text:
        text = "（空）"
    while text:
        if len(text) <= limit:
            await _send_message(chat_id, text, context, reply_markup=reply_markup)
            break
        split_at = text.rfind("\n", 0, limit)
        drop_chars = "\n" if split_at > 0 else ""
        if split_at <= 0:
            split_at = text.rfind(" ", 0, limit)
            drop_chars = " " if split_at > 0 else ""
        if split_at <= 0:
            split_at = limit
        await context.bot.send_message(chat_id=chat_id, text=text[:split_at])
        text = text[split_at:]
        if drop_chars:
            text = text.lstrip(drop_chars)


async def _send_message(
    chat_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if reply_markup is None or "Button_copy_text_invalid" not in str(exc):
            raise
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=None)
