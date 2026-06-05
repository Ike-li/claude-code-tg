"""Tests for shared Telegram UI helpers."""

from claude_code_tg.telegram_ui import copy_text_value, html_escape_limited


def test_html_escape_limited_respects_tiny_limits() -> None:
    assert html_escape_limited("abcdef", 0) == ""
    assert html_escape_limited("abcdef", 1) == "."
    assert html_escape_limited("abcdef", 2) == ".."


def test_html_escape_limited_keeps_escaped_length_bounded() -> None:
    result = html_escape_limited("<abcdef>", 8)

    assert result == "&lt;a..."
    assert len(result) <= 8


def test_copy_text_value_respects_tiny_limits() -> None:
    assert copy_text_value("abcdef", limit=0) == ""
    assert copy_text_value("abcdef", limit=1) == "."
    assert copy_text_value("abcdef", limit=2) == ".."
    assert copy_text_value("abcdef", limit=3) == "..."


def test_copy_text_value_default_matches_telegram_limit() -> None:
    result = copy_text_value("x" * 300)

    assert len(result) == 256
    assert result.endswith("...")
