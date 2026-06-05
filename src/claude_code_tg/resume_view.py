"""In-memory Telegram resume-session picker state."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from claude_code_tg.claude_sessions import ClaudeSessionInfo
from claude_code_tg.telegram_ui import copy_button

RESUME_PICKERS_PER_CHAT_LIMIT = 3
RESUME_BUTTON_LIMIT = 8
RESUME_TITLE_LIMIT = 22


@dataclass
class ResumePicker:
    chat_id: int
    picker_id: str
    sessions: dict[str, str] = field(default_factory=dict)


class ResumePickerStore:
    """Small process-local store for /resume inline button callbacks."""

    def __init__(self, *, per_chat_limit: int = RESUME_PICKERS_PER_CHAT_LIMIT) -> None:
        self._per_chat_limit = per_chat_limit
        self._pickers: dict[tuple[int, str], ResumePicker] = {}
        self._chat_pickers: dict[int, deque[str]] = {}

    def create(self, chat_id: int, sessions: list[ClaudeSessionInfo]) -> ResumePicker:
        picker_id = uuid.uuid4().hex[:10]
        picker = ResumePicker(chat_id=chat_id, picker_id=picker_id)
        for item in sessions[:RESUME_BUTTON_LIMIT]:
            token = uuid.uuid4().hex[:8]
            picker.sessions[token] = item.session_id
        key = (chat_id, picker_id)
        self._pickers[key] = picker
        pickers = self._chat_pickers.setdefault(chat_id, deque())
        pickers.append(picker_id)
        while len(pickers) > self._per_chat_limit:
            old_picker_id = pickers.popleft()
            self._pickers.pop((chat_id, old_picker_id), None)
        return picker

    def resolve(self, chat_id: int, picker_id: str, token: str) -> str | None:
        picker = self._pickers.get((chat_id, picker_id))
        if picker is None:
            return None
        return picker.sessions.get(token)


def build_resume_keyboard(
    chat_id: int,
    sessions: list[ClaudeSessionInfo],
    current_session: str | None,
    store: ResumePickerStore,
) -> InlineKeyboardMarkup | None:
    if not sessions:
        return None
    picker = store.create(chat_id, sessions)
    rows: list[list[InlineKeyboardButton]] = []
    for token, item in zip(picker.sessions, sessions, strict=False):
        current = item.session_id == current_session
        label = _session_button_label(item, current=current)
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"resume:{chat_id}:{picker.picker_id}:{token}",
                    style="primary" if current else None,
                ),
                copy_button("复制ID", item.session_id),
            ]
        )
    if len(sessions) > RESUME_BUTTON_LIMIT:
        rows.append(
            [
                InlineKeyboardButton(
                    f"仅显示前 {RESUME_BUTTON_LIMIT} 个",
                    callback_data=f"resume:{chat_id}:{picker.picker_id}:noop",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def parse_resume_callback(data: str) -> tuple[int, str, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "resume":
        return None
    raw_chat_id, picker_id, token = parts[1], parts[2], parts[3]
    if not picker_id or not token:
        return None
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    if raw_chat_id != str(chat_id):
        return None
    return chat_id, picker_id, token


def _session_button_label(item: ClaudeSessionInfo, *, current: bool) -> str:
    title = item.title or "无标题"
    title = title.replace("\n", " ").strip() or "无标题"
    if len(title) > RESUME_TITLE_LIMIT:
        title = title[: RESUME_TITLE_LIMIT - 3].rstrip() + "..."
    prefix = "当前 " if current else "接管 "
    return f"{prefix}{title} · {item.session_id[:8]}"
