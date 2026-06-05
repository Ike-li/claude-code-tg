"""Process-local ForceReply intent state."""

from __future__ import annotations

from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal

PendingReplyIntent = Literal["run", "resume", "model", "permissions", "effort"]

PENDING_REPLIES_PER_CHAT_LIMIT = 10


@dataclass(frozen=True)
class PendingReply:
    chat_id: int
    message_id: int
    user_id: int
    intent: PendingReplyIntent


class PendingReplyStore:
    """Small per-process store for ForceReply prompts."""

    def __init__(self, *, per_chat_limit: int = PENDING_REPLIES_PER_CHAT_LIMIT) -> None:
        self._per_chat_limit = per_chat_limit
        self._replies: dict[tuple[int, int], PendingReply] = {}
        self._chat_messages: dict[int, deque[int]] = {}

    def create(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        intent: PendingReplyIntent,
    ) -> PendingReply:
        reply = PendingReply(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            intent=intent,
        )
        key = (chat_id, message_id)
        self._replies[key] = reply
        messages = self._chat_messages.setdefault(chat_id, deque())
        messages.append(message_id)
        while len(messages) > self._per_chat_limit:
            old_message_id = messages.popleft()
            self._replies.pop((chat_id, old_message_id), None)
        return reply

    def pop(self, chat_id: int, message_id: int) -> PendingReply | None:
        reply = self._replies.pop((chat_id, message_id), None)
        messages = self._chat_messages.get(chat_id)
        if messages is not None:
            with suppress(ValueError):
                messages.remove(message_id)
            if not messages:
                self._chat_messages.pop(chat_id, None)
        return reply

    def get(self, chat_id: int, message_id: int) -> PendingReply | None:
        return self._replies.get((chat_id, message_id))
