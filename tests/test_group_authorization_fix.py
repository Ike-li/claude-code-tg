"""Tests for group chat authorization defense-in-depth fix.

Verifies that command handlers check _is_chat_allowed even if chat_gate
somehow fails to block unauthorized groups.
"""

import inspect

import pytest

from claude_code_tg import bot_commands
from claude_code_tg.bot import TGBot


@pytest.fixture
def bot(tmp_path):
    """Create a TGBot instance with test configuration."""
    return TGBot(
        token="test_token",
        admin_ids={123},
        allowed_ids={123},
        allowed_chat_ids={999},  # Only chat 999 is allowed
        project_dir=str(tmp_path),
        status_file=tmp_path / "status.json",
    )


def test_all_commands_have_chat_allowed_check():
    """Verify all command handlers check _is_chat_allowed.

    This is a code inspection test to ensure we don't regress.
    """
    # Commands that should have defense-in-depth checks
    commands_to_check = [
        "handle_new",
        "handle_attach",
        "handle_resume",
        "handle_sessions",
        "handle_stop_command",
        "handle_status",
        "handle_model",
        "handle_effort",
        "_handle_permission_mode",
    ]

    for cmd_name in commands_to_check:
        # Get the method from BotCommandHandlers class
        method = getattr(bot_commands.BotCommandHandlers, cmd_name)
        source = inspect.getsource(method)

        # Check that _is_chat_allowed is called
        assert "_is_chat_allowed" in source, (
            f"{cmd_name} must call _is_chat_allowed for defense-in-depth. "
            f"This prevents authorization bypass if chat_gate fails."
        )


def test_authorized_user_in_allowed_group_can_use_commands(tmp_path):
    """Sanity check: authorized users in allowed groups should work normally."""
    bot = TGBot(
        token="test_token",
        admin_ids={123},
        allowed_ids={123},
        allowed_chat_ids={999},  # Group 999 allowed
        project_dir=str(tmp_path),
        status_file=tmp_path / "status.json",
    )

    # User 123 in allowed group 999
    assert bot._is_authorized(123)
    assert bot._is_chat_allowed(999, "group")

    # User 123 in unauthorized group 888
    assert bot._is_authorized(123)
    assert not bot._is_chat_allowed(888, "group")


def test_private_chats_always_allowed(tmp_path):
    """Private chats should always be allowed (governed by user auth only)."""
    bot = TGBot(
        token="test_token",
        admin_ids={123},
        allowed_ids={123},
        allowed_chat_ids=set(),  # No groups allowed
        project_dir=str(tmp_path),
        status_file=tmp_path / "status.json",
    )

    # Private chats are always allowed
    assert bot._is_chat_allowed(123, "private")
    assert bot._is_chat_allowed(456, "private")

    # But groups require explicit allowlist
    assert not bot._is_chat_allowed(999, "group")
