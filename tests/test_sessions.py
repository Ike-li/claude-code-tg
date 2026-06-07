"""Direct tests for ChatSessionStore state machine and persistence."""

import json
from collections import deque
from pathlib import Path

from claude_code_tg.executor import RunEvent
from claude_code_tg.sessions import ChatSessionStore


def make_store(
    *,
    queue_max_size: int = 3,
    permission_mode: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    status_file: Path | None = None,
) -> ChatSessionStore:
    return ChatSessionStore(
        queue_max_size=queue_max_size,
        permission_mode=permission_mode,
        model=model,
        effort=effort,
        status_file=status_file,
    )


class _Recorder:
    """Async reply callback that records the messages it received."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> None:
        self.messages.append(text)


class TestInit:
    def test_queue_max_size_floored_at_one(self) -> None:
        assert make_store(queue_max_size=0).queue_max_size == 1
        assert make_store(queue_max_size=-5).queue_max_size == 1
        assert make_store(queue_max_size=4).queue_max_size == 4

    def test_defaults_are_normalized(self) -> None:
        store = make_store(
            permission_mode="accept-edits", model="  opus  ", effort="X-HIGH"
        )
        assert store.default_permission_mode == "acceptEdits"
        assert store.default_model == "opus"
        assert store.default_effort == "xhigh"

    def test_blank_defaults_become_none(self) -> None:
        store = make_store(permission_mode=None, model="default")
        assert store.default_permission_mode is None
        assert store.default_model is None
        assert store.default_effort is None


class TestEffectiveSettings:
    def test_per_chat_override_wins_over_default(self) -> None:
        store = make_store(permission_mode="plan", model="sonnet", effort="medium")
        store.permission_modes[7] = "bypassPermissions"
        store.model_overrides[7] = "opus"
        store.effort_overrides[7] = "max"
        assert store.effective_permission_mode(7) == "bypassPermissions"
        assert store.effective_model(7) == "opus"
        assert store.effective_effort(7) == "max"

    def test_falls_back_to_default_without_override(self) -> None:
        store = make_store(permission_mode="plan", model="sonnet", effort="high")
        assert store.effective_permission_mode(99) == "plan"
        assert store.effective_model(99) == "sonnet"
        assert store.effective_effort(99) == "high"

    def test_labels_use_claude_default_when_unset(self) -> None:
        store = make_store()
        assert store.permission_mode_label(1) == "Claude Code 默认"
        assert store.model_label(1) == "Claude Code 默认"
        assert store.effort_label(1) == "Claude Code 默认"


class TestSessionVersioning:
    def test_bump_increments_and_returns_new_version(self) -> None:
        store = make_store()
        assert store.session_version(5) == 0
        assert store.bump_session_version(5) == 1
        assert store.bump_session_version(5) == 2
        assert store.session_version(5) == 2

    def test_set_session_if_current_accepts_matching_version(self) -> None:
        store = make_store()
        version = store.session_version(5)
        assert store.set_session_if_current(5, "sess-a", version) is True
        assert store.sessions[5] == "sess-a"

    def test_set_session_if_current_rejects_stale_version(self) -> None:
        store = make_store()
        stale = store.session_version(5)
        store.bump_session_version(5)  # a /new or /resume happened meanwhile
        assert store.set_session_if_current(5, "sess-late", stale) is False
        assert 5 not in store.sessions

    def test_reset_chat_bumps_version_and_clears_state(self) -> None:
        store = make_store()
        store.sessions[5] = "sess-a"
        store.queues[5] = deque([(1, "hi")])
        store.permission_modes[5] = "bypassPermissions"
        store.model_overrides[5] = "opus"
        store.effort_overrides[5] = "max"
        store.reset_chat(5)
        assert 5 not in store.sessions
        assert 5 not in store.queues
        # /new is a full reset: per-chat permission/model overrides must not
        # survive, so a new session can never inherit a stale (unsafe) mode.
        assert 5 not in store.permission_modes
        assert 5 not in store.model_overrides
        assert 5 not in store.effort_overrides
        assert store.effective_permission_mode(5) == store.default_permission_mode
        assert store.effective_model(5) == store.default_model
        assert store.effective_effort(5) == store.default_effort
        assert store.session_version(5) == 1

    def test_attach_session_sets_session_and_bumps_version(self) -> None:
        store = make_store()
        store.queues[5] = deque([(1, "queued")])
        store.attach_session(5, "sess-attached")
        assert store.sessions[5] == "sess-attached"
        assert 5 not in store.queues
        assert store.session_version(5) == 1


class TestQueue:
    async def test_not_busy_reserves_chat_and_processes_immediately(self) -> None:
        store = make_store()
        reply = _Recorder()
        assert await store.try_enqueue(5, 1, "hello", reply) is False
        assert 5 in store.busy
        assert reply.messages == []

    async def test_busy_chat_enqueues(self) -> None:
        store = make_store(queue_max_size=2)
        store.busy.add(5)
        reply = _Recorder()
        assert await store.try_enqueue(5, 1, "first", reply) is True
        queued = store.queues[5][0]
        assert queued.user_id == 1
        assert queued.prompt == "first"
        assert "已排队 (1/2)" in reply.messages[0]

    async def test_enqueue_snapshots_settings(self) -> None:
        # A queued message must capture settings in effect at enqueue time, so
        # later changes do not retroactively apply to it.
        store = make_store(queue_max_size=2)
        store.busy.add(5)
        store.permission_modes[5] = "plan"
        store.model_overrides[5] = "opus"
        store.effort_overrides[5] = "high"
        reply = _Recorder()
        await store.try_enqueue(5, 1, "first", reply)
        # User changes settings after queuing.
        store.permission_modes[5] = "bypassPermissions"
        store.model_overrides[5] = "sonnet"
        store.effort_overrides[5] = "max"
        queued = store.queues[5][0]
        assert queued.permission_mode == "plan"
        assert queued.model == "opus"
        assert queued.effort == "high"

    async def test_queue_full_rejects(self) -> None:
        store = make_store(queue_max_size=1)
        store.busy.add(5)
        reply = _Recorder()
        await store.try_enqueue(5, 1, "first", reply)
        assert await store.try_enqueue(5, 1, "second", reply) is True
        assert "队列已满" in reply.messages[-1]
        assert len(store.queues[5]) == 1

    async def test_queue_rebuilt_when_max_size_changed(self) -> None:
        store = make_store(queue_max_size=1)
        store.busy.add(5)
        reply = _Recorder()
        await store.try_enqueue(5, 1, "first", reply)
        store.queue_max_size = 3  # config reload widened the queue
        await store.try_enqueue(5, 1, "second", reply)
        assert store.queues[5].maxlen == 3
        # The pre-existing single-slot queue is replaced, so only the new item stays.
        assert len(store.queues[5]) == 1
        assert store.queues[5][0].prompt == "second"

    def test_popleft_returns_none_for_empty(self) -> None:
        assert make_store().popleft_queue(5) is None

    def test_popleft_drains_in_fifo_order_and_deletes_when_empty(self) -> None:
        store = make_store(queue_max_size=3)
        store.queues[5] = deque([(1, "a"), (2, "b")], maxlen=3)
        assert store.popleft_queue(5) == (1, "a")
        assert store.popleft_queue(5) == (2, "b")
        assert store.popleft_queue(5) is None
        assert 5 not in store.queues

    def test_queue_total_sums_across_chats(self) -> None:
        store = make_store(queue_max_size=3)
        store.queues[1] = deque([(1, "a")], maxlen=3)
        store.queues[2] = deque([(2, "b"), (2, "c")], maxlen=3)
        assert store.queue_total() == 3


class TestPersistence:
    def test_write_status_returns_none_without_status_file(self) -> None:
        assert make_store(status_file=None).write_status() is None

    def test_write_then_restore_round_trips_state(self, tmp_path: Path) -> None:
        status_file = tmp_path / "status.json"
        store = make_store(status_file=status_file)
        session_id = "123e4567-e89b-12d3-a456-426614174000"
        store.sessions[5] = session_id
        store.permission_modes[5] = "plan"
        store.model_overrides[5] = "opus"
        store.effort_overrides[5] = "high"
        assert store.write_status() is None

        restored = make_store(status_file=status_file)
        assert restored.restore_sessions() == 1
        assert restored.sessions[5] == session_id
        assert restored.permission_modes[5] == "plan"
        assert restored.model_overrides[5] == "opus"
        assert restored.effort_overrides[5] == "high"

    def test_write_status_payload_shape(self, tmp_path: Path) -> None:
        status_file = tmp_path / "status.json"
        store = make_store(status_file=status_file)
        store.sessions[5] = "sess-a"
        store.busy.add(5)
        store.write_status()
        data = json.loads(status_file.read_text())
        assert data["sessions"] == 1
        assert data["sessions_full"] == {"5": "sess-a"}
        assert data["default_permission_mode"] == "claude-default"
        assert data["default_model"] == "claude-default"
        assert data["default_effort"] == "claude-default"
        assert data["busy_chats"] == [5]
        assert "uptime_seconds" in data and "timestamp" in data

    def test_runtime_status_is_persisted_and_restored(self, tmp_path: Path) -> None:
        status_file = tmp_path / "status.json"
        store = make_store(status_file=status_file)
        store.record_runtime_event(
            5,
            RunEvent(
                kind="runtime",
                runtime_model="mimo-v2.5-pro",
                runtime_permission_mode="bypassPermissions",
                runtime_claude_code_version="2.1.156",
                runtime_cwd="/tmp/project",
                runtime_mcp_servers=(("context7", "pending"),),
                context_window=1000000,
                max_output_tokens=32000,
                runtime_speed="standard",
            ),
        )

        store.write_status()
        restored = make_store(status_file=status_file)
        restored.restore_sessions()

        runtime = restored.runtime_status(5)
        assert runtime is not None
        assert runtime.model == "mimo-v2.5-pro"
        assert runtime.permission_mode == "bypassPermissions"
        assert runtime.claude_code_version == "2.1.156"
        assert runtime.cwd == "/tmp/project"
        assert runtime.mcp_servers == (("context7", "pending"),)
        assert runtime.context_window == 1000000
        assert runtime.max_output_tokens == 32000
        assert runtime.speed == "standard"

    def test_restore_missing_file_returns_zero(self, tmp_path: Path) -> None:
        store = make_store(status_file=tmp_path / "absent.json")
        assert store.restore_sessions() == 0

    def test_restore_ignores_corrupt_json(self, tmp_path: Path) -> None:
        status_file = tmp_path / "status.json"
        status_file.write_text("{not valid json")
        store = make_store(status_file=status_file)
        assert store.restore_sessions() == 0

    def test_restore_skips_invalid_session_and_setting_entries(
        self, tmp_path: Path
    ) -> None:
        status_file = tmp_path / "status.json"
        valid_session = "123e4567-e89b-12d3-a456-426614174000"
        status_file.write_text(
            json.dumps(
                {
                    "sessions_full": {"5": valid_session, "6": 123, "7": "not-a-uuid"},
                    "permission_modes_full": {"5": "bogus-mode", "6": "plan"},
                    "model_overrides_full": {"5": "opus", "6": None},
                    "effort_overrides_full": {"5": "extreme", "6": "ultracode"},
                }
            )
        )
        store = make_store(status_file=status_file)
        store.restore_sessions()
        # Non-string id (chat 6) and non-UUID id (chat 7) are skipped.
        assert store.sessions == {5: valid_session}
        # Invalid permission mode for chat 5 is skipped; valid one kept.
        assert store.permission_modes == {6: "plan"}
        # Valid model kept; None skipped.
        assert store.model_overrides == {5: "opus"}
        assert store.effort_overrides == {6: "ultracode"}
