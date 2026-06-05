from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from claude_code_tg.message_output import send_pages


@pytest.mark.asyncio
async def test_send_pages_sends_empty_placeholder() -> None:
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    await send_pages(123, "", context)

    context.bot.send_message.assert_called_once_with(
        chat_id=123, text="（空）", reply_markup=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("alpha\nbeta", 6, ["alpha", "beta"]),
        ("alpha\n  beta", 8, ["alpha", "  beta"]),
        ("alpha beta", 7, ["alpha", "beta"]),
        ("abcdef", 3, ["abc", "def"]),
    ],
)
async def test_send_pages_splits_long_messages(
    text: str, limit: int, expected: list[str]
) -> None:
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    await send_pages(123, text, context, limit=limit)

    assert [
        call.kwargs["text"] for call in context.bot.send_message.call_args_list
    ] == expected


@pytest.mark.asyncio
async def test_send_pages_retries_without_invalid_copy_text_button() -> None:
    context = MagicMock()
    context.bot.send_message = AsyncMock(
        side_effect=[BadRequest("Button_copy_text_invalid"), MagicMock()]
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("copy", callback_data="x")]])

    await send_pages(123, "hello", context, reply_markup=keyboard)

    first, second = context.bot.send_message.call_args_list
    assert first.kwargs["reply_markup"] is keyboard
    assert second.kwargs == {"chat_id": 123, "text": "hello", "reply_markup": None}
