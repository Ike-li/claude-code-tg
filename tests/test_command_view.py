"""Tests for Telegram command picker state."""

from claude_code_tg.command_view import (
    COMMAND_BUTTON_LIMIT,
    CommandPickerStore,
    build_command_keyboard,
    parse_command_callback,
)


def test_command_keyboard_uses_short_tokens() -> None:
    store = CommandPickerStore()

    keyboard = build_command_keyboard(222, ["code-review", "foo:bar"], store)

    assert keyboard is not None
    first = keyboard.inline_keyboard[0][0]
    assert first.text == "/code-review"
    assert first.callback_data.startswith("cmd:222:")
    assert keyboard.inline_keyboard[0][1].text == "复制"
    assert keyboard.inline_keyboard[0][1].copy_text.text == "/run /code-review"
    _prefix, raw_chat_id, picker_id, token = first.callback_data.split(":")
    assert len(token) == 8
    assert store.resolve(int(raw_chat_id), picker_id, token) == "code-review"


def test_command_keyboard_limits_button_count_and_truncates_label() -> None:
    store = CommandPickerStore()
    commands = ["very-long-command-name-that-needs-truncation"] + [
        f"cmd-{index}" for index in range(COMMAND_BUTTON_LIMIT)
    ]

    keyboard = build_command_keyboard(222, commands, store)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == COMMAND_BUTTON_LIMIT + 1
    assert keyboard.inline_keyboard[0][0].text == "/very-long-command-name-t..."
    assert keyboard.inline_keyboard[-1][0].text == f"仅显示前 {COMMAND_BUTTON_LIMIT} 个"


def test_parse_command_callback_validates_payload() -> None:
    assert parse_command_callback("cmd:222:picker:token") == (
        222,
        "picker",
        "token",
    )
    assert parse_command_callback("cmd:+222:picker:token") is None
    assert parse_command_callback("cmd:222:picker") is None
    assert parse_command_callback("resume:222:picker:token") is None
