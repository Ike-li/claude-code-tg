"""Small Telegram UI helpers shared by bot handlers."""

from __future__ import annotations

from html import escape
from typing import Literal, cast

from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import InlineKeyboardButtonLimit, ParseMode

HTML_PARSE_MODE = ParseMode.HTML

SettingKind = Literal["model", "perm", "effort"]

MODEL_CHOICES = ("sonnet", "opus")
PERMISSION_CHOICES = ("default", "plan", "acceptEdits", "auto")
EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max", "ultracode")
COPY_TEXT_LIMIT = InlineKeyboardButtonLimit.MAX_COPY_TEXT


def html_escape(text: str) -> str:
    return escape(text, quote=False)


def html_escape_limited(text: str, limit: int) -> str:
    """Escape text for Telegram HTML while keeping escaped length bounded."""
    stripped = text.strip()
    if len(html_escape(stripped)) <= limit:
        return html_escape(stripped)

    suffix = "..."
    if limit <= 0:
        return ""
    if limit < len(suffix):
        return suffix[:limit]
    target = max(0, limit - len(suffix))
    low = 0
    high = len(stripped)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = html_escape(stripped[:mid].rstrip())
        if len(candidate) <= target:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best + suffix


def build_setting_keyboard(kind: SettingKind, chat_id: int) -> InlineKeyboardMarkup:
    if kind == "model":
        choices: tuple[str, ...] = MODEL_CHOICES
        labels = {choice: choice for choice in choices}
    elif kind == "perm":
        choices = PERMISSION_CHOICES
        labels = {choice: choice for choice in choices}
    else:
        choices = EFFORT_CHOICES
        labels = {choice: choice for choice in choices}

    rows: list[list[InlineKeyboardButton]] = []
    for start in range(0, len(choices), 2):
        row = [
            InlineKeyboardButton(
                labels[value],
                callback_data=f"setting:{kind}:{chat_id}:{value}",
            )
            for value in choices[start : start + 2]
        ]
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                "重置",
                callback_data=f"setting:{kind}:{chat_id}:reset",
                style="danger",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def copy_text_value(text: str, *, limit: int = COPY_TEXT_LIMIT) -> str:
    stripped = text.strip() or "（空）"
    if len(stripped) <= limit:
        return stripped
    if limit <= 0:
        return ""
    if limit <= 3:
        return "..."[:limit]
    return stripped[: limit - 3].rstrip() + "..."


def copy_button(label: str, text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, copy_text=CopyTextButton(copy_text_value(text)))


def build_status_keyboard(
    status_text: str, session_id: str | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if session_id:
        rows.append([copy_button("复制 session_id", session_id)])
    rows.append([copy_button("复制状态", status_text)])
    return InlineKeyboardMarkup(rows)


def parse_setting_callback(data: str) -> tuple[SettingKind, int, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "setting":
        return None

    raw_kind, raw_chat_id, value = parts[1], parts[2], parts[3]
    if raw_kind not in {"model", "perm", "effort"} or not value:
        return None
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    if raw_chat_id != str(chat_id):
        return None
    return cast(SettingKind, raw_kind), chat_id, value
