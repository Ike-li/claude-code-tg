"""Synthetic token fixtures that avoid committing real secret-shaped literals."""

from urllib.parse import quote


def telegram_bot_token() -> str:
    """Return a Telegram-token-shaped value built only at runtime."""
    bot_id = str(10**9 + 23_456_789)
    secret = "A" + ("B" * 19) + ("_" * 10) + ("-" * 5)
    return f"{bot_id}:{secret}"


def url_encoded_telegram_bot_token() -> str:
    return quote(telegram_bot_token(), safe="")
