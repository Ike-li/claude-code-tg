"""Tests for bot message execution and queue draining."""

import asyncio
import logging
from collections import deque
from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import TelegramError

from claude_code_tg import bot_processing
from claude_code_tg.executor import ExecutionResult, RunEvent
from claude_code_tg.sessions import QueuedPrompt
from tests.bot_helpers import make_bot, make_context, make_update


def _q(user_id: int, prompt: str) -> QueuedPrompt:
    return QueuedPrompt(
        user_id=user_id,
        prompt=prompt,
        permission_mode=None,
        model=None,
        effort=None,
    )


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_stale_result_after_new_does_not_restore_old_session(self):
        bot = make_bot()
        context = make_context()

        async def run_and_reset(**kwargs):
            bot._session_versions[222] = bot._session_versions.get(222, 0) + 1
            bot.sessions.pop(222, None)
            return ExecutionResult(
                text="stopped",
                session_id="old-session",
                was_stopped=True,
            )

        with patch.object(bot.executor, "run", side_effect=run_and_reset):
            await bot._process_message(222, 222, "hello", context)

        assert 222 not in bot.sessions

    @pytest.mark.asyncio
    async def test_stopped_result_skips_output(self):
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()

        result = ExecutionResult(
            text="⏹ 已被用户停止。", session_id="s1", was_stopped=True
        )
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        assert context.bot.send_message.call_count == 1
        status_msg = context.bot.send_message.return_value
        text = status_msg.edit_text.call_args.args[0]
        assert "⏹ 已停止" in text
        assert status_msg.edit_text.call_args.kwargs["reply_markup"] is None
        assert bot.sessions[222] == "s1"

    @pytest.mark.asyncio
    async def test_error_result_is_marked_in_output(self):
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()

        result = ExecutionResult(text="Claude failed", session_id="s1", is_error=True)
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        output_call = context.bot.send_message.call_args_list[-1]
        assert output_call.kwargs["text"] == "📎 Session: s1...\n❌ Claude failed"
        keyboard = output_call.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "重新执行"
        assert keyboard.inline_keyboard[1][1].text == "复制结果"

    @pytest.mark.asyncio
    async def test_chat_action_failure_does_not_block_output(self):
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()
        context.bot.send_chat_action = AsyncMock(side_effect=TelegramError("boom"))

        result = ExecutionResult(text="ok", session_id="s1")
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        assert context.bot.send_message.call_args_list[-1].kwargs["text"].endswith("ok")

    @pytest.mark.asyncio
    async def test_run_start_logs_permission_mode_and_effort(self, caplog):
        bot = make_bot(permission_mode="bypassPermissions", model="opus", effort="high")
        update = make_update(text="test")
        context = make_context()
        result = ExecutionResult(text="ok", session_id="s1")

        with (
            caplog.at_level(logging.INFO, logger="claude_code_tg.bot_processing"),
            patch(
                "claude_code_tg.bot_processing.project_branch_label",
                return_value="feature/ui",
            ),
            patch.object(
                bot.executor, "run", new_callable=AsyncMock, return_value=result
            ),
        ):
            await bot.handle_message(update, context)

        assert "Run start" in caplog.text
        assert "permission_mode=bypassPermissions" in caplog.text
        assert "model=opus" in caplog.text
        assert "effort=high" in caplog.text
        status_msg = context.bot.send_message.return_value
        status_text = status_msg.edit_text.call_args.args[0]
        assert "会话: 新建" in status_text
        assert "分支: feature/ui" in status_text
        assert "模型: opus" in status_text
        assert "思考强度: high" in status_text
        assert (
            "CLI 参数: --permission-mode bypassPermissions --model opus --effort high"
            in status_text
        )
        assert "ctx: 等待 CLI 回传" in status_text

    @pytest.mark.asyncio
    async def test_status_card_renders_branch_and_ctx_usage(self):
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()

        async def fake_run(**kwargs):
            await kwargs["on_event"](
                RunEvent(
                    kind="runtime",
                    runtime_model="mimo-v2.5-pro",
                    runtime_permission_mode="bypassPermissions",
                )
            )
            await kwargs["on_event"](
                RunEvent(
                    kind="usage",
                    input_tokens=1234,
                    output_tokens=56,
                    cache_creation_input_tokens=1000,
                    cache_read_input_tokens=2000,
                )
            )
            return ExecutionResult(text="ok", session_id="s1")

        with (
            patch(
                "claude_code_tg.bot_processing.project_branch_label",
                return_value="feature/ui",
            ),
            patch.object(bot.executor, "run", side_effect=fake_run),
        ):
            await bot.handle_message(update, context)

        status_msg = context.bot.send_message.return_value
        status_text = status_msg.edit_text.call_args.args[0]
        assert "分支: feature/ui" in status_text
        assert "权限模式: bypassPermissions" in status_text
        assert "模型: mimo-v2.5-pro" in status_text
        assert "ctx: in 1.2k / out 56 / cache 3k" in status_text

    @pytest.mark.asyncio
    async def test_status_card_heartbeat_refreshes_without_events(self, monkeypatch):
        monkeypatch.setattr(bot_processing, "STATUS_CARD_HEARTBEAT_SECONDS", 0.01)
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()

        async def fake_run(**_kwargs):
            view = bot.run_views.latest(222)
            assert view is not None
            view.started_at -= 10
            await asyncio.sleep(0.05)
            return ExecutionResult(text="ok", session_id="s1")

        with patch.object(bot.executor, "run", side_effect=fake_run):
            await bot.handle_message(update, context)

        status_msg = context.bot.send_message.return_value
        edited_texts = [call.args[0] for call in status_msg.edit_text.call_args_list]
        assert any("⏳ 执行中" in text and "0:10" in text for text in edited_texts)
        assert any("✅ 完成" in text for text in edited_texts)

    @pytest.mark.asyncio
    async def test_draft_preview_disabled_by_default(self):
        bot = make_bot()
        update = make_update(text="test")
        context = make_context()
        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        context.bot.send_message_draft.assert_not_called()

    @pytest.mark.asyncio
    async def test_draft_preview_streams_private_assistant_text(self):
        bot = make_bot(draft_preview_enabled=True)
        update = make_update(text="test")
        context = make_context()

        async def fake_run(**kwargs):
            await kwargs["on_event"](
                RunEvent(kind="assistant_text", text="partial answer")
            )
            return ExecutionResult(text="final", session_id="s1")

        with patch.object(bot.executor, "run", side_effect=fake_run):
            await bot.handle_message(update, context)

        assert context.bot.send_message_draft.call_count >= 2
        first_call = context.bot.send_message_draft.call_args_list[0].kwargs
        assert first_call["chat_id"] == 222
        assert first_call["text"] == ""
        assert first_call["draft_id"] != 0
        assert context.bot.send_message_draft.call_args_list[-1].kwargs["text"] == (
            "partial answer"
        )

    @pytest.mark.asyncio
    async def test_draft_preview_throttles_and_truncates_private_text(self):
        bot = make_bot(draft_preview_enabled=True)
        update = make_update(text="test")
        context = make_context()
        long_text = "x" * 5000

        async def fake_run(**kwargs):
            await kwargs["on_event"](RunEvent(kind="assistant_text", text=long_text))
            await kwargs["on_event"](RunEvent(kind="assistant_text", text="second"))
            return ExecutionResult(text="final", session_id="s1")

        with patch.object(bot.executor, "run", side_effect=fake_run):
            await bot.handle_message(update, context)

        assert context.bot.send_message_draft.call_count == 2
        assert context.bot.send_message_draft.call_args_list[-1].kwargs["text"] == (
            "x" * 4096
        )

    @pytest.mark.asyncio
    async def test_draft_preview_error_does_not_block_output(self):
        bot = make_bot(draft_preview_enabled=True)
        update = make_update(text="test")
        context = make_context()
        context.bot.send_message_draft = AsyncMock(side_effect=TelegramError("boom"))

        result = ExecutionResult(text="ok", session_id="s1")
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        assert context.bot.send_message.call_args_list[-1].kwargs["text"].endswith("ok")

    @pytest.mark.asyncio
    async def test_draft_preview_skips_group_chats(self):
        bot = make_bot(draft_preview_enabled=True)
        update = make_update(text="@testbot test", chat_id=-100222, chat_type="group")
        context = make_context()
        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        context.bot.send_message_draft.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_message_enqueues_while_first_run_is_active(self):
        bot = make_bot()
        first_update = make_update(text="first")
        second_update = make_update(text="second")
        context = make_context()
        first_started = asyncio.Event()
        first_can_finish = asyncio.Event()
        prompts: list[str] = []

        async def fake_run(**kwargs):
            prompt = kwargs["prompt"]
            prompts.append(prompt)
            if prompt == "first":
                first_started.set()
                await first_can_finish.wait()
            return ExecutionResult(text=f"ok {prompt}", session_id=f"s{len(prompts)}")

        with patch.object(bot.executor, "run", side_effect=fake_run):
            first_task = asyncio.create_task(bot.handle_message(first_update, context))
            await asyncio.wait_for(first_started.wait(), timeout=1)

            await bot.handle_message(second_update, context)

            second_update.message.reply_text.assert_called_once()
            assert "已排队" in second_update.message.reply_text.call_args.args[0]
            assert 222 in bot.busy

            first_can_finish.set()
            await first_task

        assert prompts == ["first", "second"]
        assert 222 not in bot.busy


class TestDrainQueue:
    @pytest.mark.asyncio
    async def test_drain_queue_processes_in_order(self):
        bot = make_bot()
        bot.queues[222] = deque([_q(222, "first"), _q(222, "second"), _q(222, "third")])

        prompts = []

        async def capture_process(chat_id, user_id, prompt, context, **_kwargs):
            prompts.append(prompt)

        with patch.object(bot, "_process_message", side_effect=capture_process):
            await bot._drain_queue(222, make_context())

        assert prompts == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_drain_queue_empty(self):
        bot = make_bot()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as mock_proc:
            await bot._drain_queue(222, make_context())
            mock_proc.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_queue_continues_on_exception(self):
        bot = make_bot()
        bot.queues[222] = deque([_q(222, "first"), _q(222, "second"), _q(222, "third")])

        call_count = 0

        async def fail_then_succeed(chat_id, user_id, prompt, context, **_kwargs):
            nonlocal call_count
            call_count += 1
            if prompt == "second":
                raise RuntimeError("simulated failure")

        with patch.object(bot, "_process_message", side_effect=fail_then_succeed):
            await bot._drain_queue(222, make_context())

        assert call_count == 3
        assert 222 not in bot.queues
