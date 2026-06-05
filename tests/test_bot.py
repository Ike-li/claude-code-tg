"""Tests for bot module."""

import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import ForceReply
from telegram.ext import ApplicationHandlerStop

from claude_code_tg.claude_sessions import ClaudeSessionInfo
from claude_code_tg.executor import ExecutionResult, RunEvent
from claude_code_tg.run_view import apply_run_event, render_detail
from tests.bot_helpers import VALID_SESSION_ID, make_bot, make_context, make_update


class TestAuthorization:
    def test_admin_is_authorized(self):
        bot = make_bot(admin_ids={111}, allowed_ids=set())
        assert bot._is_authorized(111) is True

    def test_allowed_user_is_authorized(self):
        bot = make_bot(admin_ids={111}, allowed_ids={222})
        assert bot._is_authorized(222) is True

    def test_unknown_user_not_authorized(self):
        bot = make_bot(admin_ids={111}, allowed_ids={222})
        assert bot._is_authorized(999) is False

    def test_admin_always_in_allowed(self):
        bot = make_bot(admin_ids={111}, allowed_ids={222})
        assert 111 in bot.allowed_ids


class TestSessionManagement:
    def test_no_session_initially(self):
        bot = make_bot()
        sid, existing = bot._get_or_create_session(222)
        assert sid is None
        assert existing is False

    def test_existing_session(self):
        bot = make_bot()
        bot.sessions[222] = "abc-123"
        sid, existing = bot._get_or_create_session(222)
        assert sid == "abc-123"
        assert existing is True

    @pytest.mark.asyncio
    async def test_new_clears_session(self):
        bot = make_bot()
        bot.sessions[222] = "old-session"
        update = make_update()
        context = make_context()
        await bot.handle_new(update, context)
        assert 222 not in bot.sessions
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_clears_permission_model_and_effort_overrides(self):
        # A new session must never inherit a stale (possibly unsafe, e.g.
        # bypassPermissions) per-chat override set before /new.
        bot = make_bot(permission_mode="default", model="sonnet", effort="high")
        bot.sessions[222] = "old-session"
        bot.permission_modes[222] = "bypassPermissions"
        bot.model_overrides[222] = "opus"
        bot.effort_overrides[222] = "max"
        update = make_update()
        context = make_context()
        await bot.handle_new(update, context)
        assert 222 not in bot.permission_modes
        assert 222 not in bot.model_overrides
        assert 222 not in bot.effort_overrides
        assert bot._effective_permission_mode(222) == "default"
        assert bot._effective_model(222) == "sonnet"
        assert bot._effective_effort(222) == "high"
        reply = update.message.reply_text.call_args[0][0]
        assert "权限模式、模型和思考强度已重置为默认" in reply

    @pytest.mark.asyncio
    async def test_new_while_busy_stops_and_clears_queue(self):
        bot = make_bot()
        bot.sessions[222] = "old-session"
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "queued")])
        update = make_update()
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ) as mock_stop:
            await bot.handle_new(update, context)

        mock_stop.assert_called_once_with(222)
        assert 222 not in bot.sessions
        assert 222 not in bot.queues
        assert "已停止" in update.message.reply_text.call_args[0][0]


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999)
        context = make_context()
        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self):
        bot = make_bot()
        update = make_update(text="   ")
        context = make_context()
        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_message_ignored(self):
        bot = make_bot()
        update = MagicMock()
        update.message = None
        context = make_context()
        await bot.handle_message(update, context)

    @pytest.mark.asyncio
    async def test_no_effective_chat_ignored(self):
        bot = make_bot()
        update = make_update()
        update.effective_chat = None
        context = make_context()
        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_message(self):
        bot = make_bot()
        update = make_update(text="hi there")
        context = make_context()

        result = ExecutionResult(text="Hello!", session_id="new-session")
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        assert bot.sessions[222] == "new-session"
        assert 222 not in bot.busy

    @pytest.mark.asyncio
    async def test_message_uses_permission_mode(self):
        bot = make_bot(permission_mode="plan")
        update = make_update(text="plan this")
        context = make_context()
        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ) as mock_run:
            await bot.handle_message(update, context)

        assert mock_run.call_args.kwargs["permission_mode"] == "plan"
        status_text = context.bot.send_message.call_args_list[0].kwargs["text"]
        assert "权限模式: plan" in status_text

    @pytest.mark.asyncio
    async def test_message_uses_model(self):
        bot = make_bot(model="sonnet")
        update = make_update(text="use model")
        context = make_context()
        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ) as mock_run:
            await bot.handle_message(update, context)

        assert mock_run.call_args.kwargs["model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_message_passes_cli_resume_compat(self):
        bot = make_bot(cli_resume_compat=True)
        update = make_update(text="compat")
        context = make_context()
        result = ExecutionResult(text="ok", session_id=VALID_SESSION_ID)

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ) as mock_run:
            await bot.handle_message(update, context)

        assert mock_run.call_args.kwargs["cli_resume_compat"] is True

    @pytest.mark.asyncio
    async def test_message_updates_status_card_with_tool_details(self):
        bot = make_bot()
        update = make_update(text="run tests")
        context = make_context()

        async def fake_run(**kwargs):
            await kwargs["on_event"](
                RunEvent(
                    kind="tool_started",
                    tool_index=1,
                    tool_name="Bash",
                    summary="uv run pytest tests/test_executor.py -q",
                )
            )
            await kwargs["on_event"](
                RunEvent(
                    kind="tool_result",
                    tool_index=1,
                    tool_name="Bash",
                    output="1 passed",
                )
            )
            return ExecutionResult(text="Done", session_id="s1", tool_count=1)

        with patch.object(bot.executor, "run", side_effect=fake_run):
            await bot.handle_message(update, context)

        status_msg = context.bot.send_message.return_value
        final_status = status_msg.edit_text.call_args.args[0]
        assert "✅ 完成" in final_status
        assert "任务: run tests" in final_status
        assert "#1 Bash" in final_status
        assert "工具输入/输出已折叠" in final_status
        assert "uv run pytest" not in final_status
        assert "1 passed" not in final_status
        view = bot.run_views.latest(222)
        assert view is not None
        detail = render_detail(view)
        assert "uv run pytest" in detail
        assert "1 passed" in detail
        keyboard = status_msg.edit_text.call_args.kwargs["reply_markup"]
        buttons = keyboard.inline_keyboard[0]
        assert buttons[0].text == "详情"
        assert all(button.text != "⏹ Stop" for button in buttons)

    @pytest.mark.asyncio
    async def test_removes_bot_mention(self):
        bot = make_bot()
        update = make_update(text="@testbot hello", chat_type="group")
        update.message.reply_to_message = None
        context = make_context(bot_username="testbot")

        captured_prompt = []
        original_result = ExecutionResult(text="ok", session_id="s1")

        async def capture_run(**kwargs):
            captured_prompt.append(kwargs["prompt"])
            return original_result

        with patch.object(bot.executor, "run", side_effect=capture_run):
            await bot.handle_message(update, context)

        assert captured_prompt[0] == "hello"

    @pytest.mark.asyncio
    async def test_group_ignores_non_mention(self):
        bot = make_bot()
        update = make_update(text="random message", chat_type="group")
        update.message.reply_to_message = None
        context = make_context()
        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)
            mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_responds_to_reply(self):
        bot = make_bot()
        update = make_update(text="do something", chat_type="group")
        reply_user = MagicMock()
        reply_user.id = 999  # bot id
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.from_user = reply_user
        context = make_context(bot_id=999)

        result = ExecutionResult(text="done", session_id="s1")
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_message(update, context)

        context.bot.send_message.assert_called()


class TestQueueing:
    @pytest.mark.asyncio
    async def test_busy_chat_queues_message(self):
        bot = make_bot()
        bot.busy.add(222)
        update = make_update(text="queued msg")
        context = make_context()

        await bot.handle_message(update, context)

        assert 222 in bot.queues
        assert len(bot.queues[222]) == 1
        update.message.reply_text.assert_called_once()
        assert "已排队" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_full_queue_rejected(self):
        bot = make_bot(queue_max_size=2)
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "a"), (222, "b")], maxlen=2)

        update = make_update(text="overflow")
        context = make_context()

        await bot.handle_message(update, context)

        assert len(bot.queues[222]) == 2
        update.message.reply_text.assert_called_once()
        assert "队列已满" in update.message.reply_text.call_args[0][0]


class TestStopCommand:
    @pytest.mark.asyncio
    async def test_stop_when_running(self):
        bot = make_bot()
        update = make_update()
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ):
            await bot.handle_stop_command(update, context)

        update.message.reply_text.assert_called_with("⏹ 已停止。")

    @pytest.mark.asyncio
    async def test_stop_when_idle(self):
        bot = make_bot()
        update = make_update()
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=False
        ):
            await bot.handle_stop_command(update, context)

        update.message.reply_text.assert_called_with("没有正在执行的任务。")


class TestStopCallback:
    @pytest.mark.asyncio
    async def test_stop_callback_success(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:222"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ):
            await bot.handle_stop_callback(update, context)

        query.edit_message_text.assert_called_with("⏹ 已停止。")

    @pytest.mark.asyncio
    async def test_stop_callback_already_done(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:222"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=False
        ):
            await bot.handle_stop_callback(update, context)

        query.edit_message_text.assert_called_with("✅ 已完成。")

    @pytest.mark.asyncio
    async def test_stop_callback_accepts_negative_group_chat_id(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:-100123"
        query.message.chat_id = -100123
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ) as mock_stop:
            await bot.handle_stop_callback(update, context)

        mock_stop.assert_called_once_with(-100123)
        query.edit_message_text.assert_called_with("⏹ 已停止。")

    @pytest.mark.asyncio
    async def test_stop_callback_unauthorized(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 999
        query.data = "stop:222"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot.executor, "stop", new_callable=AsyncMock) as mock_stop:
            await bot.handle_stop_callback(update, context)
            mock_stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_callback_invalid_data(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:notanumber"
        query.answer = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot.executor, "stop", new_callable=AsyncMock) as mock_stop:
            await bot.handle_stop_callback(update, context)
            mock_stop.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "callback_data",
        ["notstop:222", "stop:", "stop:222:extra", "stop:+222", "stop: 222"],
    )
    async def test_stop_callback_rejects_malformed_payloads(self, callback_data):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot.executor, "stop", new_callable=AsyncMock) as mock_stop:
            await bot.handle_stop_callback(update, context)
            mock_stop.assert_not_called()

        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_callback_no_message(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:222"
        query.message = None
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot.executor, "stop", new_callable=AsyncMock) as mock_stop:
            await bot.handle_stop_callback(update, context)
            mock_stop.assert_not_called()
        query.edit_message_text.assert_not_called()


class TestRunViewCallback:
    @pytest.mark.asyncio
    async def test_run_view_callback_expands_details(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        apply_run_event(
            view,
            RunEvent(
                kind="tool_started",
                tool_index=1,
                tool_name="Bash",
                summary="uv run pytest",
            ),
        )
        apply_run_event(
            view,
            RunEvent(
                kind="tool_result",
                tool_index=1,
                tool_name="Bash",
                output="passed",
            ),
        )
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"run:detail:222:{view.run_id}"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args.args[0]
        assert "详情" in text
        assert "#1 Bash" in text
        assert "uv run pytest" in text
        assert "passed" in text
        keyboard = query.edit_message_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "收起"

    @pytest.mark.asyncio
    async def test_run_view_callback_compacts_details(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        view.expanded = True
        apply_run_event(
            view,
            RunEvent(
                kind="tool_started",
                tool_index=1,
                tool_name="Read",
                summary="src/app.py",
            ),
        )
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"run:compact:222:{view.run_id}"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        assert view.expanded is False
        text = query.edit_message_text.call_args.args[0]
        assert "当前: #1 Read" in text
        assert "详情:" not in text

    @pytest.mark.asyncio
    async def test_run_view_callback_changes_page(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        view.expanded = True
        for index in range(1, 7):
            apply_run_event(
                view,
                RunEvent(
                    kind="tool_started",
                    tool_index=index,
                    tool_name="Bash",
                    summary=f"command {index}",
                ),
            )
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"run:page:222:{view.run_id}:1"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        assert view.expanded is True
        assert view.detail_page == 1
        text = query.edit_message_text.call_args.args[0]
        assert "详情: 全部 2/2" in text
        assert "#5 Bash" in text
        assert "#6 Bash" in text

    @pytest.mark.asyncio
    async def test_run_view_callback_changes_filter_and_resets_page(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        view.expanded = True
        view.detail_page = 3
        apply_run_event(
            view,
            RunEvent(
                kind="tool_started",
                tool_index=1,
                tool_name="Bash",
                summary="uv run pytest",
            ),
        )
        apply_run_event(
            view,
            RunEvent(kind="tool_result", tool_index=1, output="passed"),
        )
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"run:filter:222:{view.run_id}:output"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        assert view.expanded is True
        assert view.detail_filter == "output"
        assert view.detail_page == 0
        text = query.edit_message_text.call_args.args[0]
        assert "详情: 输出 1/1" in text
        assert "passed" in text
        assert "uv run pytest" not in text

    @pytest.mark.asyncio
    async def test_run_view_callback_rejects_cross_chat(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"run:detail:222:{view.run_id}"
        query.message.chat_id = 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_view_callback_reports_expired_detail(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "run:detail:222:missing"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        query.answer.assert_any_call("详情已过期")
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_view_callback_unauthorized_user_ignored(self):
        bot = make_bot()
        view = bot.run_views.create(222)
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 999
        query.data = f"run:detail:222:{view.run_id}"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_run_view_callback(update, context)

        query.edit_message_text.assert_not_called()


class TestStatusCommand:
    @pytest.mark.asyncio
    async def test_status_idle(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        await bot.handle_status(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "🟢 空闲" in reply
        assert "会话: 无" in reply
        assert "权限模式: Claude Code 默认" in reply
        assert "模型: Claude Code 默认" in reply
        assert "附件: path, 单个附件≤20 MB" in reply
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "复制状态"

    @pytest.mark.asyncio
    async def test_status_busy_with_session(self):
        bot = make_bot(
            permission_mode="acceptEdits",
            model="opus",
            attachment_mode="copy-to-project",
            attachment_max_bytes=3 * 1024 * 1024,
        )
        bot.busy.add(222)
        bot.sessions[222] = VALID_SESSION_ID
        update = make_update()
        context = make_context()
        await bot.handle_status(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "🔴 执行中" in reply
        assert f"会话: {VALID_SESSION_ID}" in reply
        assert "权限模式: acceptEdits" in reply
        assert "模型: opus" in reply
        assert "思考强度: Claude Code 默认" in reply
        assert "附件: copy-to-project, 单个附件≤3 MB" in reply
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "复制 session_id"
        assert keyboard.inline_keyboard[0][0].copy_text.text == VALID_SESSION_ID

    @pytest.mark.asyncio
    async def test_status_includes_last_claude_runtime_metadata(self):
        bot = make_bot()
        bot.state.record_runtime_event(
            222,
            RunEvent(
                kind="runtime",
                runtime_model="mimo-v2.5-pro",
                runtime_permission_mode="bypassPermissions",
                runtime_claude_code_version="2.1.156",
                runtime_cwd="/Users/raylee/code/tmp/cctg_test",
                runtime_mcp_servers=(
                    ("context7", "connected"),
                    ("github", "needs-auth"),
                ),
            ),
        )
        bot.state.record_runtime_event(
            222,
            RunEvent(
                kind="run_completed",
                context_window=1000000,
                max_output_tokens=32000,
                runtime_speed="standard",
            ),
        )
        update = make_update()
        context = make_context()

        await bot.handle_status(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Claude CLI 回传:" in reply
        assert "claude_code_version: 2.1.156" in reply
        assert "cwd: /Users/raylee/code/tmp/cctg_test" in reply
        assert "model: mimo-v2.5-pro" in reply
        assert "permissionMode: bypassPermissions" in reply
        assert "mcp_servers: context7=connected, github=needs-auth" in reply
        assert "contextWindow: 1000000" in reply
        assert "maxOutputTokens: 32000" in reply
        assert "speed: standard" in reply


class TestModeCommand:
    @pytest.mark.asyncio
    async def test_mode_without_args_shows_current_mode(self):
        bot = make_bot(permission_mode="default")
        update = make_update()
        context = make_context()
        context.args = []

        await bot.handle_mode(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "当前权限模式: default" in reply
        assert "acceptEdits" in reply

    @pytest.mark.asyncio
    async def test_mode_sets_chat_mode(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = ["accept-edits"]

        await bot.handle_mode(update, context)

        assert bot.permission_modes[222] == "acceptEdits"
        reply = update.message.reply_text.call_args[0][0]
        assert "acceptEdits" in reply
        data = json.loads(status_file.read_text())
        assert data["permission_modes_full"]["222"] == "acceptEdits"

    @pytest.mark.asyncio
    async def test_mode_rejects_invalid_mode(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["wild"]

        await bot.handle_mode(update, context)

        assert bot.permission_modes == {}
        assert "无效" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_mode_reset_uses_default_mode(self):
        bot = make_bot(permission_mode="plan")
        bot.permission_modes[222] = "acceptEdits"
        update = make_update()
        context = make_context()
        context.args = ["reset"]

        await bot.handle_mode(update, context)

        assert 222 not in bot.permission_modes
        assert "plan" in update.message.reply_text.call_args[0][0]


class TestPermissionsCommand:
    @pytest.mark.asyncio
    async def test_permissions_without_args_shows_current_mode(self):
        bot = make_bot(permission_mode="default")
        update = make_update()
        context = make_context()
        context.args = []

        await bot.handle_permissions(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "当前权限模式: default" in reply
        assert "acceptEdits" in reply
        assert "/permissions <mode>" in reply
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "default"
        assert keyboard.inline_keyboard[0][1].text == "plan"

    @pytest.mark.asyncio
    async def test_permissions_sets_chat_mode(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = ["accept-edits"]

        await bot.handle_permissions(update, context)

        assert bot.permission_modes[222] == "acceptEdits"
        reply = update.message.reply_text.call_args[0][0]
        assert "acceptEdits" in reply
        data = json.loads(status_file.read_text())
        assert data["permission_modes_full"]["222"] == "acceptEdits"

    @pytest.mark.asyncio
    async def test_permissions_reset_uses_default_mode(self):
        bot = make_bot(permission_mode="plan")
        bot.permission_modes[222] = "acceptEdits"
        update = make_update()
        context = make_context()
        context.args = ["reset"]

        await bot.handle_permissions(update, context)

        assert 222 not in bot.permission_modes
        assert "plan" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_permissions_rejects_invalid_mode(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["wild"]

        await bot.handle_permissions(update, context)

        assert bot.permission_modes == {}
        assert "无效" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_permissions_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999)
        context = make_context()
        context.args = ["accept-edits"]

        await bot.handle_permissions(update, context)

        assert bot.permission_modes == {}
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_permissions_callback_sets_chat_mode(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:perm:222:plan"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert bot.permission_modes[222] == "plan"
        query.edit_message_text.assert_called_once_with(
            "权限模式已设置为 plan，下一条消息生效。",
            reply_markup=None,
        )
        data = json.loads(status_file.read_text())
        assert data["permission_modes_full"]["222"] == "plan"

    @pytest.mark.asyncio
    async def test_setting_callback_rejects_cross_chat(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:perm:222:plan"
        query.message.chat_id = 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert bot.permission_modes == {}
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_setting_callback_unauthorized_user_ignored(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 999
        query.data = "setting:perm:222:plan"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert bot.permission_modes == {}
        query.edit_message_text.assert_not_called()


class TestModelCommand:
    @pytest.mark.asyncio
    async def test_model_without_args_shows_current_model(self):
        bot = make_bot(model="sonnet")
        update = make_update()
        context = make_context()
        context.args = []

        await bot.handle_model(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "当前模型: sonnet" in reply
        assert "opus" in reply
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "sonnet"
        assert keyboard.inline_keyboard[0][1].text == "opus"

    @pytest.mark.asyncio
    async def test_model_sets_chat_override(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = ["opus"]

        await bot.handle_model(update, context)

        assert bot.model_overrides[222] == "opus"
        reply = update.message.reply_text.call_args[0][0]
        assert "opus" in reply
        data = json.loads(status_file.read_text())
        assert data["model_overrides_full"]["222"] == "opus"

    @pytest.mark.asyncio
    async def test_model_rejects_invalid_model(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["bad model"]

        await bot.handle_model(update, context)

        assert bot.model_overrides == {}
        assert "无效" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_model_reset_uses_default_model(self):
        bot = make_bot(model="sonnet")
        bot.model_overrides[222] = "opus"
        update = make_update()
        context = make_context()
        context.args = ["reset"]

        await bot.handle_model(update, context)

        assert 222 not in bot.model_overrides
        assert "sonnet" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_model_callback_sets_chat_override(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:model:222:opus"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert bot.model_overrides[222] == "opus"
        query.edit_message_text.assert_called_once_with(
            "模型已设置为 opus，下一条消息生效。",
            reply_markup=None,
        )
        data = json.loads(status_file.read_text())
        assert data["model_overrides_full"]["222"] == "opus"

    @pytest.mark.asyncio
    async def test_model_callback_reset_uses_default_model(self):
        bot = make_bot(model="sonnet")
        bot.model_overrides[222] = "opus"
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:model:222:reset"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert 222 not in bot.model_overrides
        query.edit_message_text.assert_called_once_with(
            "模型已重置为: sonnet",
            reply_markup=None,
        )


class TestEffortCommand:
    @pytest.mark.asyncio
    async def test_effort_without_args_shows_current_effort(self):
        bot = make_bot(effort="high")
        update = make_update()
        context = make_context()
        context.args = []

        await bot.handle_effort(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "当前思考强度: high" in reply
        assert "xhigh" in reply
        assert "ultracode" in reply
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "low"
        assert keyboard.inline_keyboard[0][1].text == "medium"
        assert keyboard.inline_keyboard[2][1].text == "ultracode"
        assert bot.pending_replies.get(222, 321) is None

    @pytest.mark.asyncio
    async def test_effort_sets_chat_override(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = ["x-high"]

        await bot.handle_effort(update, context)

        assert bot.effort_overrides[222] == "xhigh"
        reply = update.message.reply_text.call_args[0][0]
        assert "xhigh" in reply
        data = json.loads(status_file.read_text())
        assert data["effort_overrides_full"]["222"] == "xhigh"

    @pytest.mark.asyncio
    async def test_effort_rejects_invalid_level(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["extreme"]

        await bot.handle_effort(update, context)

        assert bot.effort_overrides == {}
        assert "无效" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_effort_reset_uses_default_effort(self):
        bot = make_bot(effort="medium")
        bot.effort_overrides[222] = "max"
        update = make_update()
        context = make_context()
        context.args = ["reset"]

        await bot.handle_effort(update, context)

        assert 222 not in bot.effort_overrides
        assert "medium" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_effort_callback_sets_chat_override(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:effort:222:ultracode"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert bot.effort_overrides[222] == "ultracode"
        query.edit_message_text.assert_called_once_with(
            "思考强度已设置为 ultracode，下一条消息生效。",
            reply_markup=None,
        )
        data = json.loads(status_file.read_text())
        assert data["effort_overrides_full"]["222"] == "ultracode"

    @pytest.mark.asyncio
    async def test_effort_callback_reset_uses_default_effort(self):
        bot = make_bot(effort="high")
        bot.effort_overrides[222] = "max"
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "setting:effort:222:reset"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_setting_callback(update, context)

        assert 222 not in bot.effort_overrides
        query.edit_message_text.assert_called_once_with(
            "思考强度已重置为: high",
            reply_markup=None,
        )


class TestAttachCommand:
    @pytest.mark.asyncio
    async def test_attach_valid_session(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = [VALID_SESSION_ID.upper()]

        await bot.handle_attach(update, context)

        assert bot.sessions[222] == VALID_SESSION_ID
        assert bot._session_versions[222] == 1
        reply = update.message.reply_text.call_args[0][0]
        assert "已接管 session 123e4567..." in reply

        data = json.loads(status_file.read_text())
        assert data["sessions_full"]["222"] == VALID_SESSION_ID

    @pytest.mark.asyncio
    async def test_attach_then_next_message_resumes_session(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = [VALID_SESSION_ID]

        await bot.handle_attach(update, context)

        result = ExecutionResult(text="continued", session_id=VALID_SESSION_ID)
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ) as mock_run:
            await bot.handle_message(make_update(text="continue"), make_context())

        assert mock_run.call_args.kwargs["session_id"] == VALID_SESSION_ID

    @pytest.mark.asyncio
    async def test_attach_without_args_shows_usage(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        await bot.handle_attach(update, context)

        assert bot.sessions == {}
        reply = update.message.reply_text.call_args[0][0]
        assert "用法" in reply
        assert "/status" in reply
        assert "/resume" in reply
        assert "完整 session_id" in reply

    @pytest.mark.asyncio
    async def test_attach_invalid_session_rejected(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["not-a-session-id"]

        await bot.handle_attach(update, context)

        assert bot.sessions == {}
        assert "无效" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_attach_unauthorized_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999)
        context = make_context()
        context.args = [VALID_SESSION_ID]

        await bot.handle_attach(update, context)

        assert bot.sessions == {}
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_attach_while_busy_stops_and_clears_queue(self):
        bot = make_bot()
        bot.sessions[222] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "queued")])
        update = make_update()
        context = make_context()
        context.args = [VALID_SESSION_ID]

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ) as mock_stop:
            await bot.handle_attach(update, context)

        mock_stop.assert_called_once_with(222)
        assert bot.sessions[222] == VALID_SESSION_ID
        assert bot._session_versions[222] == 1
        assert 222 not in bot.queues
        assert "当前任务已停止" in update.message.reply_text.call_args[0][0]


class TestSessionsCommand:
    @pytest.mark.asyncio
    async def test_resume_with_session_id_attaches_session(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = [VALID_SESSION_ID]

        await bot.handle_resume(update, context)

        assert bot.sessions[222] == VALID_SESSION_ID
        assert bot._session_versions[222] == 1
        assert "已接管" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_resume_without_args_lists_project_sessions(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert VALID_SESSION_ID not in text
        assert "1. Current title" in text
        assert "   123e4567 ·" in text
        assert "点按钮接管" in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text.startswith("接管 Current title")
        assert keyboard.inline_keyboard[0][0].callback_data.startswith("resume:222:")
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_sessions_lists_project_sessions(self):
        bot = make_bot()
        bot.sessions[222] = VALID_SESSION_ID
        update = make_update()
        context = make_context()
        other_session = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                    git_branch="main",
                    size_bytes=2048,
                ),
                ClaudeSessionInfo(
                    session_id=other_session,
                    updated_at=50,
                    path=Path("/tmp/other.jsonl"),
                    title="Other title",
                ),
            ],
        ) as discover:
            await bot.handle_sessions(update, context)

        discover.assert_called_once_with("/tmp", include_headless=True)
        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert VALID_SESSION_ID not in text
        assert other_session not in text
        assert "1. Current title" in text
        assert "   123e4567 ·" in text
        assert "2. Other title" in text
        assert "   aaaaaaaa ·" in text
        assert "Current title" in text
        assert "main" in text
        assert "2.0KB" in text
        assert "点按钮接管" in text
        assert "当前 chat" in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text.startswith("当前 Current title")
        assert keyboard.inline_keyboard[1][0].text.startswith("接管 Other title")
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_default_limits_visible_sessions(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []
        sessions = [
            ClaudeSessionInfo(
                session_id=f"00000000-0000-0000-0000-{index:012d}",
                updated_at=float(100 - index),
                path=Path(f"/tmp/{index}.jsonl"),
                title=f"Session {index}",
            )
            for index in range(10)
        ]

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=sessions,
        ):
            await bot.handle_resume(update, context)

        text = context.bot.send_message.call_args.kwargs["text"]
        assert "最近 8 / 共 10" in text
        assert "搜索示例：/resume 模型；显示全部：/resume --all" in text
        assert "1. Session 0" in text
        assert "Session 7" in text
        assert "Session 8" not in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        assert len(keyboard.inline_keyboard) == 8

    @pytest.mark.asyncio
    async def test_resume_default_truncates_long_session_titles(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []
        long_title = (
            "Run this shell command and keep it running: python3 -c "
            "\"import time; print('tick')\""
        )

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title=long_title,
                    git_branch="HEAD",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        text = context.bot.send_message.call_args.kwargs["text"]
        assert "1. Run this shell command and keep it running:..." in text
        assert "\"import time; print('tick')\"" not in text
        assert "\n   123e4567 ·" in text

    @pytest.mark.asyncio
    async def test_resume_with_keyword_filters_project_sessions(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["second-user"]
        other_session = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Check project commit status",
                    git_branch="feature/second-user-fixes",
                ),
                ClaudeSessionInfo(
                    session_id=other_session,
                    updated_at=50,
                    path=Path("/tmp/other.jsonl"),
                    title="Other title",
                    git_branch="main",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        text = context.bot.send_message.call_args.kwargs["text"]
        assert "搜索：second-user" in text
        assert VALID_SESSION_ID in text
        assert other_session not in text
        assert "Other title" not in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        assert len(keyboard.inline_keyboard) == 1

    @pytest.mark.asyncio
    async def test_resume_all_shows_all_session_rows(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["--all"]
        sessions = [
            ClaudeSessionInfo(
                session_id=f"00000000-0000-0000-0000-{index:012d}",
                updated_at=float(100 - index),
                path=Path(f"/tmp/{index}.jsonl"),
                title=f"Session {index}",
            )
            for index in range(9)
        ]

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=sessions,
        ):
            await bot.handle_resume(update, context)

        text = context.bot.send_message.call_args.kwargs["text"]
        assert "Claude Code sessions（全部）" in text
        assert "共 9 个" in text
        assert "Session 8" in text
        assert "00000000-0000-0000-0000-000000000008" in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        assert len(keyboard.inline_keyboard) == 9

    @pytest.mark.asyncio
    async def test_resume_keyword_reports_no_matches(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["missing"]

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        assert "未找到匹配“missing”" in update.message.reply_text.call_args.args[0]
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_reports_empty_result_without_force_reply(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[],
        ):
            await bot.handle_resume(update, context)

        reply = update.message.reply_text.call_args.args[0]
        assert "未发现" in reply
        assert "发送 /resume <session_id>" in reply
        assert update.message.reply_text.call_args.kwargs == {}
        assert bot.pending_replies.get(222, update.message.message_id) is None
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_callback_attaches_session(self, tmp_path):
        status_file = tmp_path / "status.json"
        bot = make_bot(status_file=status_file)
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_data = keyboard.inline_keyboard[0][0].callback_data
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        await bot.handle_resume_callback(callback_update, make_context())

        assert bot.sessions[222] == VALID_SESSION_ID
        assert bot._session_versions[222] == 1
        query.edit_message_text.assert_called_once_with(
            "🔗 已接管 session 123e4567...，下一条消息会继续该会话。"
        )
        data = json.loads(status_file.read_text())
        assert data["sessions_full"]["222"] == VALID_SESSION_ID

    @pytest.mark.asyncio
    async def test_resume_callback_stops_busy_chat(self):
        bot = make_bot()
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "queued")])
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        with patch.object(
            bot.executor, "stop", new_callable=AsyncMock, return_value=True
        ) as mock_stop:
            await bot.handle_resume_callback(callback_update, make_context())

        mock_stop.assert_called_once_with(222)
        assert bot.sessions[222] == VALID_SESSION_ID
        assert 222 not in bot.queues
        assert "当前任务已停止" in query.edit_message_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_resume_callback_reports_expired_picker(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "resume:222:missing:token"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        await bot.handle_resume_callback(update, make_context())

        query.answer.assert_any_call("session 列表已过期")
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_callback_rejects_cross_chat(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        await bot.handle_resume_callback(callback_update, make_context())

        assert bot.sessions == {}
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_callback_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[
                ClaudeSessionInfo(
                    session_id=VALID_SESSION_ID,
                    updated_at=100,
                    path=Path("/tmp/current.jsonl"),
                    title="Current title",
                ),
            ],
        ):
            await bot.handle_resume(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 999
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        await bot.handle_resume_callback(callback_update, make_context())

        assert bot.sessions == {}
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_sessions_reports_empty_result(self):
        bot = make_bot()
        update = make_update()
        context = make_context()

        with patch(
            "claude_code_tg.bot_commands.discover_project_sessions",
            return_value=[],
        ):
            await bot.handle_sessions(update, context)

        assert "未发现" in update.message.reply_text.call_args[0][0]
        assert "发送 /resume <session_id>" in update.message.reply_text.call_args[0][0]
        assert update.message.reply_text.call_args.kwargs == {}
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_sessions_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999)
        context = make_context()

        with patch("claude_code_tg.bot_commands.discover_project_sessions") as discover:
            await bot.handle_sessions(update, context)

        discover.assert_not_called()
        update.message.reply_text.assert_not_called()
        context.bot.send_message.assert_not_called()


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_content(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        await bot.handle_help(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "/new" in reply
        assert "/resume" in reply
        assert "/attach" not in reply
        assert "/sessions" not in reply
        assert not any(
            line.startswith(("/mode ", "/mode —")) for line in reply.splitlines()
        )
        assert "/model" in reply
        assert "/permissions" in reply
        assert "/clear" in reply
        assert "/context" in reply
        assert "/usage" in reply
        assert "/cost" in reply
        assert "/reload_skills" in reply
        assert "/stop" in reply
        assert "附件模式" in reply
        assert "/commands" in reply
        assert "/run" in reply

    @pytest.mark.asyncio
    async def test_help_does_not_list_claude_command_map(self):
        bot = make_bot()
        bot.claude_command_map = {"verify": "verify", "code_review": "code-review"}
        update = make_update()
        context = make_context()

        await bot.handle_help(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "项目命令" not in reply
        assert "/verify" not in reply
        assert "/code_review" not in reply
        assert "/commands" in reply


class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start_response(self):
        bot = make_bot(permission_mode="bypassPermissions", effort="high")
        update = make_update()
        context = make_context()
        await bot.handle_start(update, context)
        update.message.reply_text.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "已就绪" in reply
        assert "当前权限模式: bypassPermissions" in reply
        assert "当前思考强度: high" in reply


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_run_no_args(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []
        await bot.handle_run(update, context)
        assert "回复这条消息" in update.message.reply_text.call_args[0][0]
        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert isinstance(markup, ForceReply)
        pending = bot.pending_replies.get(222, 321)
        assert pending is not None
        assert pending.intent == "run"
        assert pending.user_id == 222

    @pytest.mark.asyncio
    async def test_run_with_args(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["/compact"]

        result = ExecutionResult(text="Compacted.", session_id="s1")
        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ):
            await bot.handle_run(update, context)

        context.bot.send_message.assert_called()


class TestForceReply:
    def _reply_update(self, text: str, *, reply_markup=None, from_user_id: int = 999):
        update = make_update(text=text)
        update.message.reply_to_message = MagicMock(
            message_id=321,
            reply_markup=reply_markup,
            from_user=MagicMock(id=from_user_id),
        )
        return update

    @pytest.mark.asyncio
    async def test_forced_run_reply_normalizes_command(self):
        bot = make_bot()
        bot.pending_replies.create(222, 321, 222, "run")
        update = self._reply_update("/run compact")
        context = make_context()

        with (
            patch.object(bot, "_process_message", new_callable=AsyncMock) as process,
            pytest.raises(ApplicationHandlerStop),
        ):
            await bot.handle_forced_reply(update, context)

        process.assert_awaited_once_with(222, 222, "/compact", context)
        assert bot.pending_replies.get(222, 321) is None

    @pytest.mark.asyncio
    async def test_forced_reply_reports_expired_force_reply_prompt(self):
        bot = make_bot()
        update = self._reply_update("compact", reply_markup=ForceReply())
        context = make_context()

        with pytest.raises(ApplicationHandlerStop):
            await bot.handle_forced_reply(update, context)

        assert "已过期" in update.message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_forced_reply_ignores_non_bot_reply_target(self):
        bot = make_bot()
        bot.pending_replies.create(222, 321, 222, "run")
        update = self._reply_update(
            "compact",
            reply_markup=ForceReply(),
            from_user_id=333,
        )
        context = make_context()

        await bot.handle_forced_reply(update, context)

        assert bot.pending_replies.get(222, 321) is not None
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_forced_reply_rejects_other_authorized_user(self):
        bot = make_bot(allowed_ids={222, 333})
        bot.pending_replies.create(-100222, 321, 222, "permissions")
        update = self._reply_update(
            "plan",
            reply_markup=ForceReply(),
            from_user_id=999,
        )
        update.effective_user.id = 333
        update.effective_chat.id = -100222
        update.effective_chat.type = "group"
        context = make_context(bot_id=999)

        with pytest.raises(ApplicationHandlerStop):
            await bot.handle_forced_reply(update, context)

        assert bot.pending_replies.get(-100222, 321) is not None
        assert -100222 not in bot.permission_modes
        assert "只对发起命令的用户有效" in update.message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_forced_model_reply_sets_override(self):
        bot = make_bot()
        bot.pending_replies.create(222, 321, 222, "model")
        update = self._reply_update("opus")
        context = make_context()

        with pytest.raises(ApplicationHandlerStop):
            await bot.handle_forced_reply(update, context)

        assert bot.model_overrides[222] == "opus"
        assert "opus" in update.message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_forced_permissions_reply_sets_mode(self):
        bot = make_bot()
        bot.pending_replies.create(222, 321, 222, "permissions")
        update = self._reply_update("plan")
        context = make_context()

        with pytest.raises(ApplicationHandlerStop):
            await bot.handle_forced_reply(update, context)

        assert bot.permission_modes[222] == "plan"

    @pytest.mark.asyncio
    async def test_forced_resume_reply_attaches_session(self):
        bot = make_bot()
        bot.pending_replies.create(222, 321, 222, "resume")
        update = self._reply_update(VALID_SESSION_ID)
        context = make_context()

        with pytest.raises(ApplicationHandlerStop):
            await bot.handle_forced_reply(update, context)

        assert bot.sessions[222] == VALID_SESSION_ID


class TestCommandsCommand:
    @pytest.mark.asyncio
    async def test_commands_lists_runnable_claude_commands(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=[
                "verify",
                "run",
                "help",
                "model",
                "code-review",
                "foo:bar",
                "verify",
            ],
        ) as load_or_probe:
            await bot.handle_commands(update, context)

        load_or_probe.assert_awaited_once_with(
            "/tmp",
            bot.command_menu_cache_file,
            refresh=False,
        )
        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "/run /code-review" in text
        assert "/run /foo:bar" in text
        assert "/run /verify" in text
        assert "/help" not in text
        assert "/model" not in text
        assert "点按钮执行" in text
        assert "->" not in text
        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        assert "/code-review" in labels
        assert "/foo:bar" in labels
        assert "/verify" in labels

    @pytest.mark.asyncio
    async def test_commands_refreshes_cache(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = ["refresh"]

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ) as load_or_probe:
            await bot.handle_commands(update, context)

        load_or_probe.assert_awaited_once_with(
            "/tmp",
            bot.command_menu_cache_file,
            refresh=True,
        )
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "缓存已刷新" in text
        assert "/run /verify" in text

    @pytest.mark.asyncio
    async def test_commands_reports_empty_result(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["help", "model"],
        ):
            await bot.handle_commands(update, context)

        assert "未发现" in update.message.reply_text.call_args[0][0]
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_reports_probe_error(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await bot.handle_commands(update, context)

        assert "探测失败" in update.message.reply_text.call_args[0][0]
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999)
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
        ) as load_or_probe:
            await bot.handle_commands(update, context)

        load_or_probe.assert_not_awaited()
        update.message.reply_text.assert_not_called()
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_callback_runs_selected_command(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ):
            await bot.handle_commands(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query
        callback_context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_command_callback(callback_update, callback_context)

        process.assert_awaited_once_with(222, 222, "/verify", callback_context)
        query.answer.assert_any_call("执行 /verify")

    @pytest.mark.asyncio
    async def test_command_callback_queues_when_busy(self):
        bot = make_bot()
        bot.busy.add(222)
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ):
            await bot.handle_commands(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query
        callback_context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_command_callback(callback_update, callback_context)

        process.assert_not_awaited()
        assert bot.queues[222][0].user_id == 222
        assert bot.queues[222][0].prompt == "/verify"
        query.answer.assert_any_call("📋 已排队 (1/3)")
        callback_context.bot.send_message.assert_called_once_with(
            chat_id=222,
            text="📋 已排队 (1/3)",
        )

    @pytest.mark.asyncio
    async def test_command_callback_reports_expired_picker(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "cmd:222:missing:token"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        await bot.handle_command_callback(update, make_context())

        query.answer.assert_any_call("命令列表已过期")
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_callback_rejects_cross_chat(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ):
            await bot.handle_commands(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_command_callback(callback_update, make_context())

        process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_command_callback_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update()
        context = make_context()
        context.args = []

        with patch(
            "claude_code_tg.bot_commands.load_or_probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ):
            await bot.handle_commands(update, context)

        keyboard = context.bot.send_message.call_args.kwargs["reply_markup"]
        callback_update = MagicMock()
        query = MagicMock()
        query.from_user.id = 999
        query.data = keyboard.inline_keyboard[0][0].callback_data
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        callback_update.callback_query = query

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_command_callback(callback_update, make_context())

        process.assert_not_awaited()


class TestResultCallback:
    @pytest.mark.asyncio
    async def test_result_callback_reruns_prompt(self):
        bot = make_bot()
        action = bot.result_actions.create(222, "run tests")
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"result:rerun:222:{action.token}"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_result_callback(update, context)

        process.assert_awaited_once_with(222, 222, "run tests", context)
        query.answer.assert_any_call("重新执行")

    @pytest.mark.asyncio
    async def test_result_callback_queues_rerun_when_busy(self):
        bot = make_bot()
        bot.busy.add(222)
        action = bot.result_actions.create(222, "run tests")
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"result:rerun:222:{action.token}"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_result_callback(update, context)

        process.assert_not_awaited()
        assert bot.queues[222][0].user_id == 222
        assert bot.queues[222][0].prompt == "run tests"
        query.answer.assert_any_call("📋 已排队 (1/3)")
        context.bot.send_message.assert_called_once_with(
            chat_id=222,
            text="📋 已排队 (1/3)",
        )

    @pytest.mark.asyncio
    async def test_result_callback_sends_status(self):
        bot = make_bot(model="sonnet")
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "result:status:222"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_result_callback(update, context)

        query.answer.assert_any_call("当前状态")
        context.bot.send_message.assert_called_once()
        assert "模型: sonnet" in context.bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_result_callback_starts_new_session(self):
        bot = make_bot()
        bot.sessions[222] = VALID_SESSION_ID
        bot.permission_modes[222] = "bypassPermissions"
        bot.model_overrides[222] = "opus"
        bot.effort_overrides[222] = "max"
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "result:new:222"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()

        await bot.handle_result_callback(update, context)

        assert 222 not in bot.sessions
        # /new is a full reset: stale per-chat overrides must not survive.
        assert 222 not in bot.permission_modes
        assert 222 not in bot.model_overrides
        assert 222 not in bot.effort_overrides
        query.answer.assert_any_call("已开始新会话")
        context.bot.send_message.assert_called_once_with(
            chat_id=222,
            text=(
                "🆕 已开始新会话。\n"
                "权限模式、模型和思考强度已重置为默认。\n"
                "当前权限模式: Claude Code 默认\n"
                "当前模型: Claude Code 默认\n"
                "当前思考强度: Claude Code 默认"
            ),
        )

    @pytest.mark.asyncio
    async def test_result_callback_reports_expired_rerun(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "result:rerun:222:missing"
        query.message.chat_id = 222
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        await bot.handle_result_callback(update, make_context())

        query.answer.assert_any_call("结果操作已过期")
        query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_result_callback_rejects_cross_chat(self):
        bot = make_bot()
        action = bot.result_actions.create(222, "run tests")
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = f"result:rerun:222:{action.token}"
        query.message.chat_id = 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
            await bot.handle_result_callback(update, make_context())

        process.assert_not_awaited()


class TestClaudeCommand:
    @pytest.mark.asyncio
    async def test_forwards_mapped_command_with_args(self):
        bot = make_bot()
        bot.claude_command_map = {"code_review": "code-review"}
        update = make_update(text="/code_review fix the bug")
        context = make_context()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_claude_command(update, context)
        proc.assert_awaited_once()
        assert proc.await_args[0][2] == "/code-review fix the bug"

    @pytest.mark.asyncio
    async def test_forwards_command_without_args(self):
        bot = make_bot()
        bot.claude_command_map = {"verify": "verify"}
        update = make_update(text="/verify")
        context = make_context()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_claude_command(update, context)
        proc.assert_awaited_once()
        assert proc.await_args[0][2] == "/verify"

    @pytest.mark.asyncio
    async def test_strips_botname_suffix(self):
        bot = make_bot()
        bot.claude_command_map = {"verify": "verify"}
        update = make_update(text="/verify@mybot do it")
        context = make_context()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_claude_command(update, context)
        proc.assert_awaited_once()
        assert proc.await_args[0][2] == "/verify do it"

    @pytest.mark.asyncio
    async def test_ignores_unknown_command(self):
        bot = make_bot()
        update = make_update(text="/nope")
        context = make_context()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_claude_command(update, context)
        proc.assert_not_called()

    @pytest.mark.asyncio
    async def test_unauthorized_user_ignored(self):
        bot = make_bot()
        bot.claude_command_map = {"verify": "verify"}
        update = make_update(user_id=999, text="/verify")
        context = make_context()
        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_claude_command(update, context)
        proc.assert_not_called()


class TestBuiltinClaudeCommand:
    @pytest.mark.asyncio
    async def test_clear_resets_current_chat_session(self):
        bot = make_bot()
        bot.sessions[222] = VALID_SESSION_ID
        update = make_update(text="/clear")
        context = make_context()

        await bot.handle_clear(update, context)

        assert 222 not in bot.sessions
        assert "已开始新会话" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_forwards_builtin_context_command(self):
        bot = make_bot()
        update = make_update(text="/context")
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_builtin_claude_command(update, context)

        proc.assert_awaited_once()
        assert proc.await_args[0][2] == "/context"

    @pytest.mark.asyncio
    async def test_forwards_builtin_with_args_and_botname_suffix(self):
        bot = make_bot()
        update = make_update(text="/reload_skills@mybot now")
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_builtin_claude_command(update, context)

        proc.assert_awaited_once()
        assert proc.await_args[0][2] == "/reload-skills now"

    @pytest.mark.asyncio
    async def test_builtin_command_ignores_unknown_command(self):
        bot = make_bot()
        update = make_update(text="/heapdump")
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_builtin_claude_command(update, context)

        proc.assert_not_called()

    @pytest.mark.asyncio
    async def test_builtin_command_unauthorized_user_ignored(self):
        bot = make_bot()
        update = make_update(user_id=999, text="/context")
        context = make_context()

        with patch.object(bot, "_process_message", new_callable=AsyncMock) as proc:
            await bot.handle_builtin_claude_command(update, context)

        proc.assert_not_called()


class TestBuildApp:
    def test_build_app_returns_application(self):
        bot = make_bot()
        app = bot.build_app()
        assert app is not None

    def test_build_app_has_job_queue(self):
        bot = make_bot()
        app = bot.build_app()
        assert app.job_queue is not None

    def test_build_app_has_handlers(self):
        bot = make_bot()
        app = bot.build_app()
        # Detailed handler/job wiring lives with bot_app.py.
        assert len(app.handlers[0]) > 0


class TestWriteStatus:
    def test_write_status_creates_file(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        bot.status_file = status_file
        bot.sessions[222] = "abc12345-xxxx"
        bot._write_status()
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["sessions"] == 1
        assert "222" in data["sessions_full"]
        assert data["sessions_full"]["222"] == "abc12345-xxxx"
        assert "last_prompt" not in data

    def test_write_status_no_file(self):
        bot = make_bot()
        bot.status_file = None
        bot._write_status()  # Should not raise

    def test_write_status_atomic_with_tmp(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        bot.status_file = status_file
        bot.sessions[222] = "abc12345-xxxx"
        bot._write_status()
        assert status_file.exists()
        assert not (tmp_path / "status.tmp").exists()  # tmp cleaned up
        data = json.loads(status_file.read_text())
        assert data["sessions"] == 1

    def test_write_status_creates_parent_dir(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "nested" / "status.json"
        bot.status_file = status_file
        bot._write_status()
        assert status_file.exists()
        assert not (status_file.parent / "status.tmp").exists()

    @pytest.mark.skipif(os.name == "nt", reason="owner-only modes are POSIX-only")
    def test_write_status_uses_owner_only_modes(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "nested" / "status.json"
        bot.status_file = status_file
        bot._write_status()

        assert status_file.parent.stat().st_mode & 0o777 == 0o700
        assert status_file.stat().st_mode & 0o777 == 0o600

    @pytest.mark.skipif(os.name == "nt", reason="symlink checks are POSIX-only")
    def test_write_status_rejects_symlink_parent(self, tmp_path, caplog):
        bot = make_bot()
        outside = tmp_path / "outside"
        outside.mkdir()
        link_dir = tmp_path / "instance"
        try:
            link_dir.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        bot.status_file = link_dir / "status.json"

        with caplog.at_level(logging.DEBUG, logger="claude_code_tg.bot"):
            bot._write_status()

        assert not (outside / "status.json").exists()
        assert "Failed to write status file" in caplog.text


class TestHeartbeat:
    def test_record_periodic_status_logs_every_tenth_tick(self, caplog):
        bot = make_bot()
        bot.sessions[222] = "abc12345-xxxx"
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "queued")])
        bot._start_time = time.time() - 3661

        with caplog.at_level(logging.INFO, logger="claude_code_tg.bot"):
            for _ in range(9):
                bot._record_periodic_status()
            assert "Heartbeat" not in caplog.text

            bot._record_periodic_status()

        assert bot._heartbeat_counter == 0
        assert "Heartbeat | sessions=1 busy=1 queue=1 uptime=1h1m" in caplog.text


class TestRestoreSessions:
    def test_restore_sessions_from_file(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(
            json.dumps(
                {"sessions_full": {"222": "abc12345-xxxx", "333": "def67890-yyyy"}}
            )
        )
        bot.status_file = status_file
        bot._restore_sessions()
        assert bot.sessions[222] == "abc12345-xxxx"
        assert bot.sessions[333] == "def67890-yyyy"

    def test_restore_sessions_missing_file(self):
        bot = make_bot()
        bot.status_file = Path("/nonexistent/status.json")
        bot._restore_sessions()  # Should not raise
        assert len(bot.sessions) == 0

    def test_restore_sessions_corrupt_json(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text("not valid json {{{")
        bot.status_file = status_file
        bot._restore_sessions()  # Should not raise
        assert len(bot.sessions) == 0

    @pytest.mark.skipif(os.name == "nt", reason="symlink status checks are POSIX-only")
    def test_restore_sessions_ignores_symlinked_status_file(self, tmp_path):
        bot = make_bot()
        outside = tmp_path / "outside-status.json"
        outside.write_text(
            json.dumps({"sessions_full": {"222": "abc12345-xxxx"}}),
            encoding="utf-8",
        )
        status_file = tmp_path / "status.json"
        try:
            status_file.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        bot.status_file = status_file

        bot._restore_sessions()

        assert bot.sessions == {}
        assert status_file.is_symlink()

    @pytest.mark.skipif(os.name == "nt", reason="symlink status checks are POSIX-only")
    def test_restore_sessions_ignores_symlinked_status_parent(self, tmp_path):
        bot = make_bot()
        real_dir = tmp_path / "real-instance"
        real_dir.mkdir()
        (real_dir / "status.json").write_text(
            json.dumps({"sessions_full": {"222": "abc12345-xxxx"}}),
            encoding="utf-8",
        )
        linked_dir = tmp_path / "linked-instance"
        try:
            linked_dir.symlink_to(real_dir, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        bot.status_file = linked_dir / "status.json"

        bot._restore_sessions()

        assert bot.sessions == {}

    def test_restore_sessions_ignores_malformed_mapping(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(json.dumps({"sessions_full": ["not", "a", "dict"]}))
        bot.status_file = status_file
        bot._restore_sessions()  # Should not raise
        assert bot.sessions == {}

    def test_restore_sessions_skips_non_string_session_ids(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(
            json.dumps({"sessions_full": {"222": "abc12345-xxxx", "333": 123}})
        )
        bot.status_file = status_file
        bot._restore_sessions()
        assert bot.sessions == {222: "abc12345-xxxx"}

    def test_restore_permission_modes_from_file(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(
            json.dumps(
                {
                    "sessions_full": {},
                    "permission_modes_full": {
                        "222": "acceptEdits",
                        "333": "not-valid",
                    },
                }
            )
        )
        bot.status_file = status_file

        bot._restore_sessions()

        assert bot.permission_modes == {222: "acceptEdits"}

    def test_restore_model_overrides_from_file(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(
            json.dumps(
                {
                    "sessions_full": {},
                    "model_overrides_full": {
                        "222": "sonnet",
                        "333": "bad model",
                    },
                }
            )
        )
        bot.status_file = status_file

        bot._restore_sessions()

        assert bot.model_overrides == {222: "sonnet"}

    def test_restore_effort_overrides_from_file(self, tmp_path):
        bot = make_bot()
        status_file = tmp_path / "status.json"
        status_file.write_text(
            json.dumps(
                {
                    "sessions_full": {},
                    "effort_overrides_full": {
                        "222": "xhigh",
                        "333": "extreme",
                    },
                }
            )
        )
        bot.status_file = status_file

        bot._restore_sessions()

        assert bot.effort_overrides == {222: "xhigh"}


class TestTryEnqueue:
    @pytest.mark.asyncio
    async def test_try_enqueue_busy_chat(self):
        bot = make_bot()
        bot.busy.add(222)
        reply_fn = AsyncMock()
        result = await bot._try_enqueue(222, 222, "hello", reply_fn)
        assert result is True
        assert 222 in bot.queues
        assert len(bot.queues[222]) == 1
        assert bot.queues[222][0].user_id == 222
        assert bot.queues[222][0].prompt == "hello"
        reply_fn.assert_called_once()
        assert "已排队" in reply_fn.call_args[0][0]

    @pytest.mark.asyncio
    async def test_try_enqueue_idle_chat(self):
        bot = make_bot()
        reply_fn = AsyncMock()
        result = await bot._try_enqueue(222, 222, "hello", reply_fn)
        assert result is False
        reply_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_try_enqueue_full_queue(self):
        bot = make_bot(queue_max_size=1)
        bot.busy.add(222)
        bot.queues[222] = deque([(222, "existing")], maxlen=1)
        reply_fn = AsyncMock()
        result = await bot._try_enqueue(222, 222, "overflow", reply_fn)
        assert result is True
        assert len(bot.queues[222]) == 1  # Not appended
        assert bot.queues[222][0] == (222, "existing")
        reply_fn.assert_called_once()
        assert "队列已满" in reply_fn.call_args[0][0]


class TestHandleRunQueue:
    @pytest.mark.asyncio
    async def test_handle_run_queue_branch(self):
        bot = make_bot()
        bot.busy.add(222)
        bot.queues[222] = deque()
        update = make_update()
        context = make_context()
        context.args = ["/compact"]
        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_run(update, context)
            mock_run.assert_not_called()
        assert len(bot.queues[222]) == 1


class TestStopCallbackSecurity:
    @pytest.mark.asyncio
    async def test_stop_callback_cross_chat_rejected(self):
        bot = make_bot()
        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 222
        query.data = "stop:222"  # targets chat 222
        query.message.chat_id = 999  # but callback comes from chat 999
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = make_context()
        with patch.object(bot.executor, "stop", new_callable=AsyncMock) as mock_stop:
            await bot.handle_stop_callback(update, context)
            mock_stop.assert_not_called()
        query.edit_message_text.assert_not_called()
