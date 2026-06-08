"""Tests for session ownership validation.

Verifies that users cannot hijack other users' sessions.
"""

import uuid

from claude_code_tg.sessions import ChatSessionStore


class TestSessionOwnership:
    def test_normalize_and_validate_new_session(self, tmp_path):
        """Test validating a session that's not yet owned."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id = 123

        # First time validating - should succeed
        result = store.normalize_and_validate_session_id(session_id, chat_id)
        assert result == session_id

        # Session not yet owned (not attached)
        assert session_id not in store.session_owners

    def test_normalize_and_validate_owned_by_same_chat(self, tmp_path):
        """Test validating a session owned by the same chat."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id = 123

        # Attach session to chat_id 123
        store.attach_session(chat_id, session_id)
        assert store.session_owners[session_id] == chat_id

        # Same chat can validate its own session
        result = store.normalize_and_validate_session_id(session_id, chat_id)
        assert result == session_id

    def test_normalize_and_validate_owned_by_different_chat(self, tmp_path):
        """Test that a session owned by chat A cannot be validated by chat B."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id_a = 123
        chat_id_b = 456

        # Attach session to chat A
        store.attach_session(chat_id_a, session_id)
        assert store.session_owners[session_id] == chat_id_a

        # Chat B tries to validate/hijack - should fail
        result = store.normalize_and_validate_session_id(session_id, chat_id_b)
        assert result is None

    def test_normalize_and_validate_invalid_uuid(self, tmp_path):
        """Test that invalid UUIDs are rejected."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        chat_id = 123

        # Invalid UUID formats
        assert store.normalize_and_validate_session_id("not-a-uuid", chat_id) is None
        assert store.normalize_and_validate_session_id("", chat_id) is None
        assert store.normalize_and_validate_session_id("12345", chat_id) is None

    def test_attach_session_records_ownership(self, tmp_path):
        """Test that attach_session records ownership."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id = 123

        # Before attach, no ownership
        assert session_id not in store.session_owners

        # Attach session
        store.attach_session(chat_id, session_id)

        # After attach, ownership recorded
        assert store.session_owners[session_id] == chat_id

    def test_attach_session_transfers_ownership(self, tmp_path):
        """Test that attaching a new session removes old ownership."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        old_session = str(uuid.uuid4())
        new_session = str(uuid.uuid4())
        chat_id = 123

        # Attach old session
        store.attach_session(chat_id, old_session)
        assert store.session_owners[old_session] == chat_id

        # Attach new session
        store.attach_session(chat_id, new_session)

        # Old ownership removed, new ownership added
        assert old_session not in store.session_owners
        assert store.session_owners[new_session] == chat_id

    def test_reset_chat_removes_ownership(self, tmp_path):
        """Test that reset_chat removes ownership."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id = 123

        # Attach session
        store.attach_session(chat_id, session_id)
        assert store.session_owners[session_id] == chat_id

        # Reset chat
        store.reset_chat(chat_id)

        # Ownership removed
        assert session_id not in store.session_owners
        assert chat_id not in store.sessions

    def test_restore_sessions_records_ownership(self, tmp_path):
        """Test that restoring sessions from file records ownership."""
        status_file = tmp_path / "status.json"

        # Create initial store and attach session
        store1 = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=status_file,
        )

        session_id = str(uuid.uuid4())
        chat_id = 123
        store1.attach_session(chat_id, session_id)
        store1.write_status()

        # Create new store and restore
        store2 = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=status_file,
        )

        restored_count = store2.restore_sessions()
        assert restored_count == 1

        # Ownership should be restored
        assert store2.session_owners[session_id] == chat_id
        assert store2.sessions[chat_id] == session_id

    def test_set_session_if_current_records_ownership(self, tmp_path):
        """Test that set_session_if_current records ownership."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_id = str(uuid.uuid4())
        chat_id = 123

        # Get current version
        version = store.session_version(chat_id)

        # Set session
        success = store.set_session_if_current(chat_id, session_id, version)
        assert success

        # Ownership should be recorded
        assert store.session_owners[session_id] == chat_id

    def test_multiple_chats_different_sessions(self, tmp_path):
        """Test that multiple chats can own different sessions."""
        store = ChatSessionStore(
            queue_max_size=3,
            permission_mode=None,
            model=None,
            effort=None,
            status_file=tmp_path / "status.json",
        )

        session_a = str(uuid.uuid4())
        session_b = str(uuid.uuid4())
        chat_a = 123
        chat_b = 456

        # Attach different sessions
        store.attach_session(chat_a, session_a)
        store.attach_session(chat_b, session_b)

        # Both ownerships recorded
        assert store.session_owners[session_a] == chat_a
        assert store.session_owners[session_b] == chat_b

        # Each chat can validate its own session
        assert store.normalize_and_validate_session_id(session_a, chat_a) == session_a
        assert store.normalize_and_validate_session_id(session_b, chat_b) == session_b

        # But not each other's
        assert store.normalize_and_validate_session_id(session_a, chat_b) is None
        assert store.normalize_and_validate_session_id(session_b, chat_a) is None
