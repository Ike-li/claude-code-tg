"""Tests for executor module."""

import asyncio
import json
import signal

import pytest

from claude_code_tg.executor import (
    INVALID_TIMEOUT_FALLBACK_SECONDS,
    ExecutionResult,
    Executor,
    RunEvent,
    _await_stderr,
    _coerce_timeout_seconds,
    _drain_stderr,
    _tail_text,
    _write_prompt_stdin,
    build_cli_setting_args,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
    sanitize_command,
    summarize_tool_input,
    summarize_tool_result_content,
)


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult(text="hello")
        assert r.text == "hello"
        assert r.session_id == ""
        assert r.is_error is False
        assert r.was_stopped is False
        assert r.duration_ms == 0
        assert r.num_turns == 0
        assert r.tool_count == 0

    def test_all_fields(self):
        r = ExecutionResult(
            text="done",
            session_id="abc-123",
            is_error=True,
            was_stopped=True,
            duration_ms=5000,
            num_turns=3,
            tool_count=7,
        )
        assert r.session_id == "abc-123"
        assert r.is_error is True
        assert r.was_stopped is True


class TestExecutorSessionId:
    def test_new_session_id_is_uuid(self):
        ex = Executor()
        sid = ex.new_session_id()
        assert len(sid) == 36
        assert sid.count("-") == 4


class TestTimeoutConfig:
    def test_positive_timeout_is_preserved(self):
        assert _coerce_timeout_seconds(12) == 12

    def test_negative_timeout_means_unlimited(self):
        assert _coerce_timeout_seconds(-1) is None

    def test_zero_timeout_falls_back(self, caplog):
        assert _coerce_timeout_seconds(0) == INVALID_TIMEOUT_FALLBACK_SECONDS
        assert "timeout=0" in caplog.text


class TestExecutorConfigNormalization:
    def test_permission_mode_defaults_and_aliases(self):
        assert normalize_permission_mode(None) is None
        assert normalize_permission_mode(" ") is None
        assert normalize_permission_mode("ask") == "default"
        assert normalize_permission_mode("ACCEPT_EDITS") == "acceptEdits"
        assert normalize_permission_mode("bypass_permissions") == "bypassPermissions"

    def test_permission_mode_rejects_unknown_values(self):
        with pytest.raises(ValueError):
            normalize_permission_mode("wild")

    def test_model_defaults_and_values(self):
        assert normalize_model(None) is None
        assert normalize_model(" ") is None
        assert normalize_model("default") is None
        assert normalize_model("claude-default") is None
        assert normalize_model("none") is None
        assert normalize_model("off") is None
        assert normalize_model("sonnet") == "sonnet"

    @pytest.mark.parametrize("value", ["--debug", "sonnet latest", "sonnet\nlatest"])
    def test_model_rejects_unsafe_values(self, value):
        with pytest.raises(ValueError):
            normalize_model(value)

    def test_effort_defaults_aliases_and_values(self):
        assert normalize_effort(None) is None
        assert normalize_effort(" ") is None
        assert normalize_effort("default") is None
        assert normalize_effort("LOW") == "low"
        assert normalize_effort("x-high") == "xhigh"
        assert normalize_effort("max") == "max"
        assert normalize_effort("ultra-code") == "ultracode"

    def test_effort_rejects_unknown_values(self):
        with pytest.raises(ValueError):
            normalize_effort("extreme")

    def test_cli_setting_args_normalize_runtime_choices(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SKIP_PERMISSIONS", raising=False)

        args = build_cli_setting_args(
            permission_mode="accept-edits",
            model="opus",
            effort="ultra-code",
        )

        assert args == (
            "--permission-mode",
            "acceptEdits",
            "--model",
            "opus",
            "--effort",
            "ultracode",
        )

    def test_cli_setting_args_include_legacy_skip_permissions_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SKIP_PERMISSIONS", "true")

        args = build_cli_setting_args()

        assert args == ("--dangerously-skip-permissions",)


class TestToolSummaries:
    def test_tail_text_returns_empty_for_non_positive_limits(self):
        assert _tail_text("a\nb", max_lines=0, max_chars=10) == ""
        assert _tail_text("a\nb", max_lines=1, max_chars=0) == ""

    def test_sanitize_command_redacts_sensitive_cli_flags(self):
        command = "curl --token my-secret-token --password=hunter2 --safe value"

        result = sanitize_command(command)

        assert "my-secret-token" not in result
        assert "hunter2" not in result
        assert "--token ***" in result
        assert "--password=***" in result
        assert "--safe value" in result

    def test_sanitize_command_redacts_quoted_sensitive_cli_flags(self):
        command = "tool --api-key 'secret-value' --authorization \"bearer-value\""

        result = sanitize_command(command)

        assert "secret-value" not in result
        assert "bearer-value" not in result
        assert "--api-key '***'" in result
        assert '--authorization "***"' in result

    def test_bash_summary_prefers_description_and_command(self):
        summary = summarize_tool_input(
            "Bash",
            {"description": "Run tests", "command": "uv run pytest tests -q"},
        )

        assert "Run tests" in summary
        assert "uv run pytest tests -q" in summary

    def test_bash_summary_redacts_sensitive_command_args(self):
        summary = summarize_tool_input(
            "Bash",
            {"command": "deploy --token my-secret-token --password=hunter2"},
        )

        assert "my-secret-token" not in summary
        assert "hunter2" not in summary

    def test_path_tool_summary_uses_path_without_content(self):
        summary = summarize_tool_input(
            "Write",
            {"file_path": "src/app.py", "content": "secret file body"},
        )

        assert summary == "src/app.py"
        assert "secret file body" not in summary

    def test_grep_summary_uses_pattern_and_path(self):
        summary = summarize_tool_input("Grep", {"pattern": "tool_use", "path": "src"})

        assert "pattern: tool_use" in summary
        assert "path: src" in summary

    def test_tool_result_summary_tails_and_sanitizes(self):
        secret = "sk-" + "abcdefghijklmnopqrstuvwxyz1234"
        content = "\n".join(f"line {index}" for index in range(12))
        summary = summarize_tool_result_content(f"{content}\nsecret {secret}")

        assert "line 0" not in summary
        assert "line 11" in summary
        assert secret not in summary


class TestExecutorStreamHelpers:
    @pytest.mark.asyncio
    async def test_drain_stderr_none_returns_empty_text(self):
        assert await _drain_stderr(None) == ""

    @pytest.mark.asyncio
    async def test_await_stderr_swallows_cancelled_error(self):
        async def cancelled():
            raise asyncio.CancelledError

        task = asyncio.create_task(cancelled())

        assert await _await_stderr(task) == ""

    @pytest.mark.asyncio
    async def test_write_prompt_stdin_ignores_missing_stream(self):
        await _write_prompt_stdin(None, "prompt")

    @pytest.mark.asyncio
    async def test_write_prompt_stdin_handles_broken_pipe(self):
        stream = BrokenPipeStdin()

        await _write_prompt_stdin(stream, "prompt")

        assert stream.closed is True
        assert stream.data == b""


class TestExecutorRun:
    @pytest.fixture
    def executor(self):
        return Executor()

    @pytest.mark.asyncio
    async def test_success_result(self, executor, monkeypatch):
        result_event = {
            "type": "result",
            "subtype": "success",
            "result": "Hello!",
            "is_error": False,
            "duration_ms": 1234,
            "num_turns": 1,
            "session_id": "test-session-id",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="hi", chat_id=1, project_dir="/tmp")
        assert result.text == "Hello!"
        assert result.session_id == "test-session-id"
        assert result.is_error is False
        assert result.duration_ms == 1234

    @pytest.mark.asyncio
    async def test_cli_resume_compat_rewrites_result_session(
        self, executor, monkeypatch
    ):
        result_event = {
            "type": "result",
            "result": "ok",
            "is_error": False,
            "duration_ms": 1,
            "num_turns": 1,
            "session_id": "123e4567-e89b-12d3-a456-426614174000",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        calls = []

        def fake_rewrite(project_dir, session_id):
            calls.append((project_dir, session_id))
            return True

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(
            "claude_code_tg.executor.rewrite_session_entrypoint_for_cli_resume",
            fake_rewrite,
        )

        await executor.run(
            prompt="hi",
            chat_id=1,
            project_dir="/tmp/project",
            cli_resume_compat=True,
        )

        assert calls == [("/tmp/project", "123e4567-e89b-12d3-a456-426614174000")]

    @pytest.mark.asyncio
    async def test_tool_use_counting(self, executor, monkeypatch):
        events = [
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "reading..."}]},
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Read"}]},
            },
            {
                "type": "result",
                "result": "Done",
                "is_error": False,
                "duration_ms": 100,
                "num_turns": 1,
                "session_id": "s1",
            },
        ]
        stdout_data = b"\n".join(json.dumps(e).encode() for e in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        tool_counts = []

        async def on_tool(count):
            tool_counts.append(count)

        result = await executor.run(
            prompt="test", chat_id=1, project_dir="/tmp", on_tool_use=on_tool
        )
        assert result.tool_count == 2
        assert tool_counts == [1, 2]

    @pytest.mark.asyncio
    async def test_run_events_preserve_tool_order_and_results(
        self, executor, monkeypatch
    ):
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {
                                "command": "uv run pytest tests/test_executor.py"
                            },
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "passed",
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_2",
                            "name": "Read",
                            "input": {"file_path": "src/claude_code_tg/executor.py"},
                        }
                    ]
                },
            },
            {
                "type": "result",
                "result": "Done",
                "is_error": False,
                "duration_ms": 100,
                "num_turns": 1,
                "session_id": "s1",
            },
        ]
        stdout_data = b"\n".join(json.dumps(e).encode() for e in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        run_events: list[RunEvent] = []

        async def on_event(event: RunEvent):
            run_events.append(event)

        result = await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            on_event=on_event,
        )

        assert result.tool_count == 2
        assert [(event.kind, event.tool_index) for event in run_events] == [
            ("tool_started", 1),
            ("tool_result", 1),
            ("tool_started", 2),
            ("run_completed", None),
        ]
        assert run_events[0].tool_name == "Bash"
        assert "uv run pytest" in run_events[0].summary
        assert run_events[1].output == "passed"
        assert run_events[2].summary == "src/claude_code_tg/executor.py"

    @pytest.mark.asyncio
    async def test_tool_result_without_id_uses_oldest_pending_tool(
        self, executor, monkeypatch
    ):
        events = [
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "content": "ok"}]},
            },
            {"type": "result", "result": "Done", "is_error": False, "session_id": "s1"},
        ]
        stdout_data = b"\n".join(json.dumps(e).encode() for e in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        run_events: list[RunEvent] = []

        async def on_event(event: RunEvent):
            run_events.append(event)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            on_event=on_event,
        )

        assert run_events[1].kind == "tool_result"
        assert run_events[1].tool_index == 1
        assert run_events[1].tool_name == "Bash"

    @pytest.mark.asyncio
    async def test_run_events_include_usage_snapshot(self, executor, monkeypatch):
        events = [
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 1234,
                        "output_tokens": 56,
                        "cache_creation_input_tokens": 1000,
                        "cache_read_input_tokens": 2000,
                    },
                    "content": [{"type": "text", "text": "thinking"}],
                },
            },
            {"type": "result", "result": "Done", "is_error": False, "session_id": "s1"},
        ]
        stdout_data = b"\n".join(json.dumps(e).encode() for e in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        run_events: list[RunEvent] = []

        async def on_event(event: RunEvent):
            run_events.append(event)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            on_event=on_event,
        )

        assistant_event = run_events[0]
        assert assistant_event.kind == "assistant_text"
        assert assistant_event.input_tokens == 1234
        assert assistant_event.output_tokens == 56
        assert assistant_event.cache_creation_input_tokens == 1000
        assert assistant_event.cache_read_input_tokens == 2000

    @pytest.mark.asyncio
    async def test_run_events_include_runtime_metadata(self, executor, monkeypatch):
        events = [
            {
                "type": "system",
                "subtype": "init",
                "cwd": "/tmp/project",
                "model": "mimo-v2.5-pro",
                "permissionMode": "bypassPermissions",
                "claude_code_version": "2.1.156",
                "mcp_servers": [
                    {"name": "context7", "status": "pending"},
                    {"name": "github", "status": "needs-auth"},
                ],
                "fast_mode_state": "off",
            },
            {
                "type": "result",
                "result": "Done",
                "is_error": False,
                "session_id": "s1",
                "usage": {
                    "input_tokens": 43,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 12288,
                    "speed": "standard",
                },
                "modelUsage": {
                    "mimo-v2.5-pro": {
                        "inputTokens": 43,
                        "outputTokens": 8,
                        "cacheReadInputTokens": 12288,
                        "contextWindow": 1000000,
                        "maxOutputTokens": 32000,
                    }
                },
            },
        ]
        stdout_data = b"\n".join(json.dumps(e).encode() for e in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        run_events: list[RunEvent] = []

        async def on_event(event: RunEvent):
            run_events.append(event)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            on_event=on_event,
        )

        runtime_event = run_events[0]
        completed_event = run_events[1]
        assert runtime_event.kind == "runtime"
        assert runtime_event.runtime_model == "mimo-v2.5-pro"
        assert runtime_event.runtime_permission_mode == "bypassPermissions"
        assert runtime_event.runtime_fast_mode_state == "off"
        assert runtime_event.runtime_claude_code_version == "2.1.156"
        assert runtime_event.runtime_cwd == "/tmp/project"
        assert runtime_event.runtime_mcp_servers == (
            ("context7", "pending"),
            ("github", "needs-auth"),
        )
        assert completed_event.kind == "run_completed"
        assert completed_event.runtime_model == "mimo-v2.5-pro"
        assert completed_event.context_window == 1000000
        assert completed_event.max_output_tokens == 32000
        assert completed_event.runtime_speed == "standard"
        assert completed_event.input_tokens == 43
        assert completed_event.output_tokens == 8
        assert completed_event.cache_read_input_tokens == 12288

    @pytest.mark.asyncio
    async def test_error_result(self, executor, monkeypatch):
        result_event = {
            "type": "result",
            "result": "Something went wrong",
            "is_error": True,
            "duration_ms": 500,
            "num_turns": 1,
            "session_id": "s1",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="fail", chat_id=1, project_dir="/tmp")
        assert result.is_error is True
        assert "Something went wrong" in result.text

    @pytest.mark.asyncio
    async def test_error_no_text(self, executor, monkeypatch):
        result_event = {
            "type": "result",
            "result": "",
            "is_error": True,
            "duration_ms": 100,
            "num_turns": 1,
            "session_id": "s1",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="fail", chat_id=1, project_dir="/tmp")
        assert result.is_error is True
        assert result.text == "执行出错，无输出。"

    @pytest.mark.asyncio
    async def test_no_result_event_nonzero_exit(self, executor, monkeypatch):
        async def fake_exec(*args, **kwargs):
            return FakeProcess(
                stdout_data=b"", stderr_data=b"CLI error msg\n", returncode=1
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="bad", chat_id=1, project_dir="/tmp")
        assert result.is_error is True
        assert "CLI error msg" in result.text

    @pytest.mark.asyncio
    async def test_no_result_event_zero_exit(self, executor, monkeypatch):
        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=b"", returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="empty", chat_id=1, project_dir="/tmp")
        assert result.text == "执行完成，无输出。"

    @pytest.mark.asyncio
    async def test_idle_timeout_keeps_running_process_alive(
        self, executor, monkeypatch
    ):
        proc = EventuallySuccessfulProcess(
            stdout_data=json.dumps(
                {
                    "type": "result",
                    "result": "ok after idle",
                    "is_error": False,
                    "duration_ms": 1,
                    "num_turns": 1,
                    "session_id": "s1",
                }
            ).encode()
            + b"\n",
            returncode=None,
        )
        wait_for_calls = 0

        async def fake_exec(*args, **kwargs):
            return proc

        async def fake_wait_for(awaitable, *, timeout):
            nonlocal wait_for_calls
            wait_for_calls += 1
            if wait_for_calls == 1:
                awaitable.close()
                raise TimeoutError
            return await awaitable

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

        result = await executor.run(
            prompt="slow", chat_id=1, project_dir="/tmp", timeout=1
        )
        assert result.is_error is False
        assert result.text == "ok after idle"
        assert proc.terminated is False
        assert proc.killed is False
        assert wait_for_calls >= 2

    @pytest.mark.asyncio
    async def test_new_session_uses_session_id_flag(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "new-id",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="hi", chat_id=1, session_id=None, project_dir="/tmp")
        assert "--session-id" in captured_cmd

    @pytest.mark.asyncio
    async def test_existing_session_uses_resume_flag(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "existing-id",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(
            prompt="hi", chat_id=1, session_id="existing-id", project_dir="/tmp"
        )
        assert "--resume" in captured_cmd
        assert "existing-id" in captured_cmd

    @pytest.mark.asyncio
    async def test_sanitizes_output(self, executor, monkeypatch):
        secret = "sk-" + "abcdefghijklmnopqrstuvwxyz1234"
        result_event = {
            "type": "result",
            "result": f"key is {secret}",
            "is_error": False,
            "duration_ms": 1,
            "num_turns": 1,
            "session_id": "s1",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert secret not in result.text

    @pytest.mark.asyncio
    async def test_malformed_json_lines_skipped(self, executor, monkeypatch):
        stdout_data = (
            b"not json\n"
            + json.dumps(
                {
                    "type": "result",
                    "result": "ok",
                    "is_error": False,
                    "duration_ms": 1,
                    "num_turns": 1,
                    "session_id": "s1",
                }
            ).encode()
            + b"\n"
        )

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_process_removed_after_run(self, executor, monkeypatch):
        async def fake_exec(*args, **kwargs):
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=42, project_dir="/tmp")
        assert 42 not in executor._processes

    @pytest.mark.asyncio
    async def test_large_stderr_does_not_deadlock(self, executor, monkeypatch):
        result_event = {
            "type": "result",
            "result": "ok",
            "is_error": False,
            "duration_ms": 1,
            "num_turns": 1,
            "session_id": "s1",
        }
        stdout_data = json.dumps(result_event).encode() + b"\n"
        # 128KB of stderr — larger than default 64KB pipe buffer
        stderr_data = b"warning line\n" * 10000

        async def fake_exec(*args, **kwargs):
            return FakeProcess(
                stdout_data=stdout_data, stderr_data=stderr_data, returncode=0
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert result.is_error is False
        assert result.text == "ok"

    @pytest.mark.asyncio
    async def test_skip_permissions_default_false(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.delenv("CLAUDE_SKIP_PERMISSIONS", raising=False)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert "--dangerously-skip-permissions" not in captured_cmd

    @pytest.mark.asyncio
    async def test_skip_permissions_explicit_true(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setenv("CLAUDE_SKIP_PERMISSIONS", "true")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert "--dangerously-skip-permissions" in captured_cmd

    @pytest.mark.asyncio
    async def test_skip_permissions_accepts_on(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setenv("CLAUDE_SKIP_PERMISSIONS", "on")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert "--dangerously-skip-permissions" in captured_cmd

    @pytest.mark.asyncio
    async def test_skip_permissions_explicit_false(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setenv("CLAUDE_SKIP_PERMISSIONS", "false")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert "--dangerously-skip-permissions" not in captured_cmd

    @pytest.mark.asyncio
    async def test_permission_mode_flag(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            permission_mode="accept-edits",
        )

        assert "--permission-mode" in captured_cmd
        assert "acceptEdits" in captured_cmd

    @pytest.mark.asyncio
    async def test_model_flag(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            model="sonnet",
        )

        assert "--model" in captured_cmd
        assert "sonnet" in captured_cmd

    @pytest.mark.asyncio
    async def test_effort_flag(self, executor, monkeypatch):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(
            prompt="test",
            chat_id=1,
            project_dir="/tmp",
            effort="ultra-code",
        )

        assert "--effort" in captured_cmd
        assert "ultracode" in captured_cmd

    @pytest.mark.asyncio
    async def test_invalid_effort_rejected(self, executor):
        with pytest.raises(ValueError):
            await executor.run(
                prompt="test",
                chat_id=1,
                project_dir="/tmp",
                effort="extreme",
            )

    @pytest.mark.asyncio
    async def test_invalid_model_rejected(self, executor):
        with pytest.raises(ValueError):
            await executor.run(
                prompt="test",
                chat_id=1,
                project_dir="/tmp",
                model="sonnet latest",
            )
        with pytest.raises(ValueError):
            await executor.run(
                prompt="test",
                chat_id=1,
                project_dir="/tmp",
                model="--debug",
            )

    @pytest.mark.asyncio
    async def test_permission_mode_overrides_legacy_skip_env(
        self, executor, monkeypatch
    ):
        captured_cmd = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setenv("CLAUDE_SKIP_PERMISSIONS", "true")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(
            prompt="test", chat_id=1, project_dir="/tmp", permission_mode="plan"
        )

        assert "--permission-mode" in captured_cmd
        assert "plan" in captured_cmd
        assert "--dangerously-skip-permissions" not in captured_cmd

    @pytest.mark.asyncio
    async def test_invalid_permission_mode_rejected(self, executor):
        with pytest.raises(ValueError):
            await executor.run(
                prompt="test",
                chat_id=1,
                project_dir="/tmp",
                permission_mode="not-a-mode",
            )

    @pytest.mark.asyncio
    async def test_prompt_truncation(self, executor, monkeypatch):
        captured_cmd = []
        captured_kwargs = {}
        processes = []

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            captured_kwargs.update(kwargs)
            proc = FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )
            processes.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        long_prompt = "x" * 60000
        await executor.run(prompt=long_prompt, chat_id=1, project_dir="/tmp")

        assert long_prompt not in captured_cmd
        assert captured_cmd[captured_cmd.index("--input-format") + 1] == "text"
        assert captured_kwargs["stdin"] is asyncio.subprocess.PIPE
        actual_prompt = processes[0].stdin.text
        assert len(actual_prompt) <= 50015  # 50000 + "\n...(truncated)"
        assert actual_prompt.endswith("...(truncated)")

    @pytest.mark.asyncio
    async def test_process_starts_new_session_for_tree_cleanup(
        self, executor, monkeypatch
    ):
        captured_kwargs = {}

        async def fake_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return FakeProcess(
                stdout_data=json.dumps(
                    {
                        "type": "result",
                        "result": "ok",
                        "is_error": False,
                        "duration_ms": 1,
                        "num_turns": 1,
                        "session_id": "s1",
                    }
                ).encode()
                + b"\n",
                returncode=0,
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await executor.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert captured_kwargs["start_new_session"] is True

    @pytest.mark.asyncio
    async def test_assistant_event_without_list_content_is_ignored(
        self, executor, monkeypatch
    ):
        events = [
            {"type": "assistant", "message": {"content": "plain text"}},
            {"type": "result", "result": "ok", "is_error": False, "session_id": "s1"},
        ]
        stdout_data = b"\n".join(json.dumps(event).encode() for event in events) + b"\n"

        async def fake_exec(*args, **kwargs):
            return FakeProcess(stdout_data=stdout_data, returncode=0)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await executor.run(prompt="test", chat_id=1, project_dir="/tmp")

        assert result.text == "ok"
        assert result.tool_count == 0


class TestExecutorStop:
    @pytest.mark.asyncio
    async def test_stop_no_process(self):
        ex = Executor()
        assert await ex.stop(999) is False

    @pytest.mark.asyncio
    async def test_stop_already_finished(self):
        ex = Executor()
        proc = FakeProcess(stdout_data=b"", returncode=0)
        ex._processes[1] = proc
        assert await ex.stop(1) is False

    @pytest.mark.asyncio
    async def test_stop_running_process(self):
        ex = Executor()
        proc = FakeProcess(stdout_data=b"", returncode=None)
        ex._processes[1] = proc
        result = await ex.stop(1)
        assert result is True
        assert proc.terminated

    @pytest.mark.asyncio
    async def test_stop_sets_stopped_flag(self):
        ex = Executor()
        proc = FakeProcess(stdout_data=b"", returncode=None)
        ex._processes[1] = proc
        await ex.stop(1)
        assert 1 in ex._stopped

    @pytest.mark.asyncio
    async def test_was_stopped_result(self, monkeypatch):
        ex = Executor()

        async def fake_exec(*args, **kwargs):
            proc = FakeProcess(stdout_data=b"", returncode=None)
            # Simulate stop being called during execution
            ex._stopped.add(1)
            proc.returncode = -15
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        result = await ex.run(prompt="test", chat_id=1, project_dir="/tmp")
        assert result.was_stopped is True
        assert 1 not in ex._stopped

    @pytest.mark.asyncio
    async def test_kill_returns_when_process_already_finished(self):
        ex = Executor()
        proc = FakeProcess(returncode=0)

        await ex._kill(proc)

        assert proc.terminated is False
        assert proc.killed is False

    @pytest.mark.asyncio
    async def test_kill_escalates_when_terminate_wait_times_out(self, monkeypatch):
        ex = Executor()
        proc = FakeProcess(returncode=None)

        async def timeout_wait_for(awaitable, *, timeout):
            awaitable.close()
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", timeout_wait_for)

        await ex._kill(proc)

        assert proc.terminated is True
        assert proc.killed is True

    def test_signal_process_tree_uses_process_group_when_available(self, monkeypatch):
        ex = Executor()
        proc = FakeProcess(returncode=None)
        proc.pid = 4321
        calls = []
        monkeypatch.setattr(
            "claude_code_tg.executor.send_signal_to_process_tree",
            lambda pid, sig: calls.append((pid, sig)),
        )

        ex._signal_process_tree(proc, signal.SIGTERM)

        assert calls == [(4321, signal.SIGTERM)]
        assert proc.terminated is False

    def test_signal_process_tree_falls_back_when_signal_delivery_fails(
        self, monkeypatch
    ):
        ex = Executor()
        proc = FakeProcess(returncode=None)
        proc.pid = 4321
        monkeypatch.setattr(
            "claude_code_tg.executor.send_signal_to_process_tree",
            lambda _pid, _sig: (_ for _ in ()).throw(OSError("delivery failed")),
        )

        ex._signal_process_tree(proc, signal.SIGKILL)

        assert proc.killed is True

    def test_signal_process_tree_ignores_missing_process(self, monkeypatch):
        ex = Executor()
        proc = FakeProcess(returncode=None)
        proc.pid = 4321
        monkeypatch.setattr(
            "claude_code_tg.executor.send_signal_to_process_tree",
            lambda _pid, _sig: (_ for _ in ()).throw(ProcessLookupError),
        )

        ex._signal_process_tree(proc, signal.SIGTERM)

        assert proc.terminated is False


# --- Test helpers ---


class FakeStreamReader:
    def __init__(self, data: bytes):
        self._lines = data.split(b"\n") if data else []
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        while self._index < len(self._lines):
            line = self._lines[self._index]
            self._index += 1
            if line:
                return line + b"\n"
        raise StopAsyncIteration

    async def readline(self):
        while self._index < len(self._lines):
            line = self._lines[self._index]
            self._index += 1
            if line:
                return line + b"\n"
        return b""

    async def read(self):
        return b"\n".join(self._lines)


class FakeStdin:
    def __init__(self):
        self.data = b""
        self.closed = False

    @property
    def text(self):
        return self.data.decode()

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class BrokenPipeStdin(FakeStdin):
    def write(self, data):
        raise BrokenPipeError


class FakeProcess:
    def __init__(
        self,
        stdout_data: bytes = b"",
        stderr_data: bytes = b"",
        returncode: int | None = 0,
    ):
        self.stdout = FakeStreamReader(stdout_data)
        self.stderr = FakeStreamReader(stderr_data)
        self.stdin = FakeStdin()
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    async def wait(self):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9


class EventuallySuccessfulProcess(FakeProcess):
    async def wait(self):
        self.returncode = 0
        return self.returncode


class HangingProcess:
    def __init__(self):
        self.stdout = HangingReader()
        self.stderr = FakeStreamReader(b"")
        self.stdin = FakeStdin()
        self.returncode = None
        self.terminated = False
        self.killed = False

    async def wait(self):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9


class HangingReader:
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(100)
        raise StopAsyncIteration

    async def readline(self):
        await asyncio.sleep(100)
        return b""
