"""Optional interaction tracing for tgcc.

Logs the *content* exchanged at each hop — Telegram in/out and the headless
``claude -p`` call — so you can follow a turn end to end. Disabled by default;
enable with ``LOG_INTERACTIONS=true``.

Implementation notes:
- A dedicated ``claude_code_tg.interactions`` logger is muted (level above
  CRITICAL) until :func:`enable` raises it to INFO. This avoids threading a
  boolean through every component constructor.
- Records propagate to the root handler configured in ``server.py``, so the
  global ``_SensitiveLogFilter`` redacts tokens/secrets automatically.
- Long payloads (big prompts/outputs) are truncated to keep logs readable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("claude_code_tg.interactions")
# Muted until enable() is called. info() short-circuits via isEnabledFor.
logger.setLevel(logging.CRITICAL + 1)

# Truncate long payloads; full content lives in the underlying transport.
MAX_PAYLOAD_CHARS = 1500


def enable() -> None:
    """Turn on interaction tracing (INFO level)."""
    logger.setLevel(logging.INFO)


def is_enabled() -> bool:
    return logger.isEnabledFor(logging.INFO)


def _fmt(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "(empty)"
    collapsed = text.replace("\n", "\\n")
    if len(collapsed) <= MAX_PAYLOAD_CHARS:
        return collapsed
    return f"{collapsed[:MAX_PAYLOAD_CHARS]}… (+{len(collapsed) - MAX_PAYLOAD_CHARS} chars)"


def tg_in(chat_id: int, text: str) -> None:
    """User → bot (message received from Telegram)."""
    logger.info("[TG  recv] chat=%s ← %s", chat_id, _fmt(text))


def tg_out(chat_id: int, text: str) -> None:
    """Bot → user (reply sent to Telegram)."""
    logger.info("[TG  send] chat=%s → %s", chat_id, _fmt(text))


def claude_send(chat_id: int, text: str) -> None:
    """Bot → headless ``claude -p`` (prompt fed on stdin)."""
    logger.info("[claude snd] chat=%s → %s", chat_id, _fmt(text))


def claude_recv(chat_id: int, text: str) -> None:
    """Headless ``claude -p`` → bot (final result text)."""
    logger.info("[claude rcv] chat=%s ← %s", chat_id, _fmt(text))
