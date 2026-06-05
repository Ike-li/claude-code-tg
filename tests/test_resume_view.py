"""Tests for Telegram resume picker state."""

from pathlib import Path

from claude_code_tg.claude_sessions import ClaudeSessionInfo
from claude_code_tg.resume_view import (
    RESUME_BUTTON_LIMIT,
    ResumePickerStore,
    build_resume_keyboard,
    parse_resume_callback,
)


def _session(index: int, *, title: str | None = None) -> ClaudeSessionInfo:
    session_id = f"00000000-0000-0000-0000-{index:012d}"
    return ClaudeSessionInfo(
        session_id=session_id,
        updated_at=float(index),
        path=Path(f"/tmp/{index}.jsonl"),
        title=title or f"Session {index}",
    )


def test_resume_keyboard_uses_short_tokens_and_marks_current() -> None:
    store = ResumePickerStore()
    sessions = [_session(1, title="Current"), _session(2, title="Other")]

    keyboard = build_resume_keyboard(222, sessions, sessions[0].session_id, store)

    assert keyboard is not None
    first = keyboard.inline_keyboard[0][0]
    assert first.text.startswith("当前 Current")
    assert first.callback_data.startswith("resume:222:")
    assert keyboard.inline_keyboard[0][1].text == "复制ID"
    assert keyboard.inline_keyboard[0][1].copy_text.text == sessions[0].session_id
    _prefix, raw_chat_id, picker_id, token = first.callback_data.split(":")
    assert len(sessions[0].session_id) == 36
    assert len(token) == 8
    assert store.resolve(int(raw_chat_id), picker_id, token) == sessions[0].session_id


def test_resume_keyboard_limits_button_count_and_truncates_title() -> None:
    store = ResumePickerStore()
    sessions = [
        _session(index, title="A very long session title") for index in range(9)
    ]

    keyboard = build_resume_keyboard(222, sessions, None, store)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == RESUME_BUTTON_LIMIT + 1
    assert keyboard.inline_keyboard[0][0].text.startswith("接管 A very long session...")
    assert keyboard.inline_keyboard[-1][0].text == f"仅显示前 {RESUME_BUTTON_LIMIT} 个"


def test_parse_resume_callback_validates_payload() -> None:
    assert parse_resume_callback("resume:222:picker:token") == (
        222,
        "picker",
        "token",
    )
    assert parse_resume_callback("resume:+222:picker:token") is None
    assert parse_resume_callback("resume:222:picker") is None
    assert parse_resume_callback("run:222:picker:token") is None
