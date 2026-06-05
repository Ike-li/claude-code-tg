"""In-memory Telegram command picker state."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from claude_code_tg.telegram_ui import copy_button

COMMAND_PICKERS_PER_CHAT_LIMIT = 3
COMMAND_BUTTON_LIMIT = 20
COMMAND_LABEL_LIMIT = 28


@dataclass
class CommandPicker:
    chat_id: int
    picker_id: str
    commands: dict[str, str] = field(default_factory=dict)


class CommandPickerStore:
    """Small process-local store for /commands inline button callbacks."""

    def __init__(self, *, per_chat_limit: int = COMMAND_PICKERS_PER_CHAT_LIMIT) -> None:
        self._per_chat_limit = per_chat_limit
        self._pickers: dict[tuple[int, str], CommandPicker] = {}
        self._chat_pickers: dict[int, deque[str]] = {}

    def create(self, chat_id: int, commands: list[str]) -> CommandPicker:
        picker_id = uuid.uuid4().hex[:10]
        picker = CommandPicker(chat_id=chat_id, picker_id=picker_id)
        for command in commands[:COMMAND_BUTTON_LIMIT]:
            token = uuid.uuid4().hex[:8]
            picker.commands[token] = command
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
        return picker.commands.get(token)


def build_command_keyboard(
    chat_id: int,
    commands: list[str],
    store: CommandPickerStore,
) -> InlineKeyboardMarkup | None:
    if not commands:
        return None
    picker = store.create(chat_id, commands)
    rows: list[list[InlineKeyboardButton]] = []
    for token, command in picker.commands.items():
        command_text = f"/run /{command.strip().lstrip('/')}"
        rows.append(
            [
                InlineKeyboardButton(
                    _command_button_label(command),
                    callback_data=f"cmd:{chat_id}:{picker.picker_id}:{token}",
                ),
                copy_button("复制", command_text),
            ]
        )
    if len(commands) > COMMAND_BUTTON_LIMIT:
        rows.append(
            [
                InlineKeyboardButton(
                    f"仅显示前 {COMMAND_BUTTON_LIMIT} 个",
                    callback_data=f"cmd:{chat_id}:{picker.picker_id}:noop",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def parse_command_callback(data: str) -> tuple[int, str, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "cmd":
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


def _command_button_label(command: str) -> str:
    label = f"/{command.strip().lstrip('/')}"
    if len(label) > COMMAND_LABEL_LIMIT:
        label = label[: COMMAND_LABEL_LIMIT - 3].rstrip() + "..."
    return label
