"""Tests for Telegram final-result action state."""

from claude_code_tg.result_view import (
    ResultActionStore,
    build_result_keyboard,
    parse_result_callback,
)


def test_result_keyboard_uses_short_rerun_token_and_copy_text() -> None:
    store = ResultActionStore()

    keyboard = build_result_keyboard(222, "run tests", "passed", store)

    rerun = keyboard.inline_keyboard[0][0]
    assert rerun.text == "重新执行"
    assert rerun.callback_data.startswith("result:rerun:222:")
    _prefix, _action, raw_chat_id, token = rerun.callback_data.split(":")
    assert len(token) == 10
    assert store.resolve(int(raw_chat_id), token) == "run tests"
    assert keyboard.inline_keyboard[1][1].copy_text.text == "passed"


def test_result_keyboard_keeps_new_session_non_danger() -> None:
    keyboard = build_result_keyboard(222, "prompt", "result", ResultActionStore())

    rerun = keyboard.inline_keyboard[0][0]
    new_session = keyboard.inline_keyboard[1][0]

    assert rerun.style == "primary"
    assert new_session.text == "新会话"
    assert new_session.style is None


def test_result_keyboard_truncates_copy_text() -> None:
    keyboard = build_result_keyboard(222, "prompt", "x" * 1000, ResultActionStore())

    copy_text = keyboard.inline_keyboard[1][1].copy_text.text

    assert len(copy_text) == 256
    assert copy_text.endswith("...")


def test_parse_result_callback_validates_payload() -> None:
    assert parse_result_callback("result:rerun:222:token") == (
        "rerun",
        222,
        "token",
    )
    assert parse_result_callback("result:status:222") == ("status", 222, "")
    assert parse_result_callback("result:new:222") == ("new", 222, "")
    assert parse_result_callback("result:rerun:222") is None
    assert parse_result_callback("result:status:222:extra") is None
    assert parse_result_callback("result:rerun:+222:token") is None
    assert parse_result_callback("cmd:rerun:222:token") is None
