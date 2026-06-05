"""Telegram result action buttons and rerun prompt state."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from claude_code_tg.telegram_ui import copy_button

RESULT_ACTIONS_PER_CHAT_LIMIT = 10


@dataclass
class ResultAction:
    chat_id: int
    token: str
    prompt: str


class ResultActionStore:
    """Small process-local store for final-result action callbacks."""

    def __init__(self, *, per_chat_limit: int = RESULT_ACTIONS_PER_CHAT_LIMIT) -> None:
        self._per_chat_limit = per_chat_limit
        self._actions: dict[tuple[int, str], ResultAction] = {}
        self._chat_tokens: dict[int, deque[str]] = {}

    def create(self, chat_id: int, prompt: str) -> ResultAction:
        token = uuid.uuid4().hex[:10]
        action = ResultAction(chat_id=chat_id, token=token, prompt=prompt)
        self._actions[(chat_id, token)] = action
        tokens = self._chat_tokens.setdefault(chat_id, deque())
        tokens.append(token)
        while len(tokens) > self._per_chat_limit:
            old_token = tokens.popleft()
            self._actions.pop((chat_id, old_token), None)
        return action

    def resolve(self, chat_id: int, token: str) -> str | None:
        action = self._actions.get((chat_id, token))
        if action is None:
            return None
        return action.prompt


def build_result_keyboard(
    chat_id: int,
    prompt: str,
    result_text: str,
    store: ResultActionStore,
) -> InlineKeyboardMarkup:
    action = store.create(chat_id, prompt)
    rows = [
        [
            InlineKeyboardButton(
                "重新执行",
                callback_data=f"result:rerun:{chat_id}:{action.token}",
                style="primary",
            ),
            InlineKeyboardButton(
                "状态",
                callback_data=f"result:status:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "新会话",
                callback_data=f"result:new:{chat_id}",
            ),
            copy_button("复制结果", result_text),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def parse_result_callback(data: str) -> tuple[str, int, str] | None:
    parts = data.split(":")
    if len(parts) not in {3, 4} or parts[0] != "result":
        return None
    action = parts[1]
    if action not in {"rerun", "status", "new"}:
        return None
    raw_chat_id = parts[2]
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    if raw_chat_id != str(chat_id):
        return None
    if action == "rerun":
        if len(parts) != 4 or not parts[3]:
            return None
        return action, chat_id, parts[3]
    if len(parts) != 3:
        return None
    return action, chat_id, ""
