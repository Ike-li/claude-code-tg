"""Tests for Telegram run progress view state."""

from claude_code_tg import run_view
from claude_code_tg.executor import RunEvent
from claude_code_tg.run_view import (
    RunView,
    apply_run_event,
    render_compact,
    render_detail,
    render_run_view,
)


def test_tool_count_tracks_total_after_recent_window_trim() -> None:
    view = RunView(chat_id=1, run_id="run")

    for index in range(1, 53):
        apply_run_event(
            view,
            RunEvent(
                kind="tool_started",
                tool_index=index,
                tool_name="Bash",
                summary=f"command {index}",
            ),
        )

    assert view.tool_count == 52
    assert list(view.tools) == list(range(3, 53))
    detail = render_detail(view)
    assert "工具: 52" in detail
    assert "详情: 全部 1/13" in detail
    assert "\n#2 Bash" not in detail
    assert "#3 Bash" in detail
    assert "#6 Bash" in detail
    assert "#7 Bash" not in detail

    view.detail_page = 12
    detail = render_detail(view)

    assert "详情: 全部 13/13" in detail
    assert "#51 Bash" in detail
    assert "#52 Bash" in detail


def test_run_view_has_nonzero_draft_id() -> None:
    first = RunView(chat_id=1, run_id="one")
    second = RunView(chat_id=1, run_id="two")

    assert first.draft_id != 0
    assert second.draft_id != 0
    assert first.draft_id != second.draft_id


def test_completed_run_elapsed_time_is_frozen(monkeypatch) -> None:
    view = RunView(chat_id=1, run_id="run", started_at=100.0)

    monkeypatch.setattr(run_view.time, "monotonic", lambda: 105.0)
    apply_run_event(view, RunEvent(kind="run_completed", text="done"))

    assert "<b>✅ 完成</b> 0:05" in render_compact(view)

    monkeypatch.setattr(run_view.time, "monotonic", lambda: 999.0)

    assert "<b>✅ 完成</b> 0:05" in render_compact(view)


def test_completed_text_only_run_does_not_duplicate_reply() -> None:
    view = RunView(chat_id=1, run_id="run", task_summary="/usage")

    apply_run_event(view, RunEvent(kind="assistant_text", text="Total cost: $0.0000"))
    apply_run_event(view, RunEvent(kind="run_completed", text="Total cost: $0.0000"))

    compact, keyboard = render_run_view(view)
    detail = render_detail(view)

    assert "✅ 完成" in compact
    assert "任务: /usage" in compact
    assert "Total cost" not in compact
    assert "当前: 模型回复中" not in compact
    assert "Total cost" not in detail
    assert keyboard is None


def test_tool_text_is_escaped_for_html_status_cards() -> None:
    view = RunView(chat_id=1, run_id="run")

    apply_run_event(
        view,
        RunEvent(
            kind="tool_started",
            tool_index=1,
            tool_name="Bash<unsafe>",
            summary="cat <secret> && echo ok",
        ),
    )
    apply_run_event(
        view,
        RunEvent(
            kind="tool_result",
            tool_index=1,
            output="1 < 2 && done",
        ),
    )

    compact, keyboard = render_run_view(view)
    detail = render_detail(view)

    assert "<b>⏳ 执行中</b>" in compact
    assert "Bash&lt;unsafe&gt;" in compact
    assert "工具输入/输出已折叠" in compact
    assert "<pre>cat &lt;secret&gt; &amp;&amp; echo ok</pre>" not in compact
    assert "<pre>1 &lt; 2 &amp;&amp; done</pre>" not in compact
    assert "<pre>cat &lt;secret&gt; &amp;&amp; echo ok</pre>" in detail
    assert "<pre>1 &lt; 2 &amp;&amp; done</pre>" in detail
    assert keyboard is not None
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["详情", "⏹ Stop"]

    view.expanded = True
    _, expanded_keyboard = render_run_view(view)

    assert expanded_keyboard is not None
    assert expanded_keyboard.inline_keyboard[0][1].text == "复制"
    assert (
        expanded_keyboard.inline_keyboard[0][1].copy_text.text
        == "cat <secret> && echo ok"
    )


def test_task_summary_is_one_line_and_escaped() -> None:
    view = RunView(chat_id=1, run_id="run", task_summary="fix <bug>\nnow")

    compact = render_compact(view)

    assert "任务: fix &lt;bug&gt; now" in compact


def test_default_runtime_labels_are_human_readable() -> None:
    compact = render_compact(RunView(chat_id=1, run_id="run"))

    assert "权限模式: Claude Code 默认" in compact
    assert "模型: Claude Code 默认" in compact
    assert "思考强度: Claude Code 默认" in compact


def test_runtime_event_replaces_default_model_placeholder() -> None:
    view = RunView(chat_id=1, run_id="run")

    initial = render_compact(view)

    assert "模型: Claude Code 默认 (等待 CLI 回传)" in initial
    assert "思考强度: Claude Code 默认 (CLI 未回传具体档位)" in initial

    apply_run_event(
        view,
        RunEvent(
            kind="runtime",
            runtime_model="mimo-v2.5-pro",
            runtime_permission_mode="bypassPermissions",
        ),
    )

    compact = render_compact(view)

    assert "权限模式: bypassPermissions" in compact
    assert "模型: mimo-v2.5-pro" in compact
    assert "模型: Claude Code 默认" not in compact
    assert "思考强度: Claude Code 默认 (CLI 未回传具体档位)" in compact


def test_effort_is_rendered_in_compact_and_detail_cards() -> None:
    view = RunView(
        chat_id=1,
        run_id="run",
        session_id="123e4567-e89b-12d3-a456-426614174000",
        is_existing_session=True,
        git_branch="feature/ui",
        permission_mode="plan",
        model="opus",
        effort="xhigh",
        cli_args=(
            "--permission-mode",
            "plan",
            "--model",
            "opus",
            "--effort",
            "xhigh",
        ),
        ctx_input_tokens=1234,
        ctx_output_tokens=56,
        ctx_cache_creation_tokens=1000,
        ctx_cache_read_tokens=2000,
    )

    compact = render_compact(view)
    detail = render_detail(view)

    assert "会话: 继续 123e4567..." in compact
    assert "分支: feature/ui" in compact
    assert "权限模式: plan" in compact
    assert "模型: opus" in compact
    assert "思考强度: xhigh" in compact
    assert "CLI 参数: --permission-mode plan --model opus --effort xhigh" in compact
    assert "ctx: in 1.2k / out 56 / cache 3k" in compact
    assert "会话: 继续 123e4567..." in detail
    assert "分支: feature/ui" in detail
    assert "权限模式: plan" in detail
    assert "模型: opus" in detail
    assert "思考强度: xhigh" in detail
    assert "CLI 参数: --permission-mode plan --model opus --effort xhigh" in detail
    assert "ctx: in 1.2k / out 56 / cache 3k" in detail


def test_usage_event_updates_ctx_without_changing_run_state() -> None:
    view = RunView(chat_id=1, run_id="run")

    apply_run_event(
        view,
        RunEvent(
            kind="usage",
            input_tokens=2000,
            output_tokens=300,
            cache_read_input_tokens=4000,
        ),
    )

    compact = render_compact(view)

    assert view.status == "running"
    assert view.tool_count == 0
    assert "ctx: in 2k / out 300 / cache 4k" in compact


def test_completion_event_can_update_ctx_window() -> None:
    view = RunView(chat_id=1, run_id="run")

    apply_run_event(
        view,
        RunEvent(
            kind="run_completed",
            input_tokens=43,
            output_tokens=8,
            cache_read_input_tokens=12288,
            context_window=1000000,
            runtime_model="mimo-v2.5-pro",
        ),
    )

    compact = render_compact(view)

    assert "模型: mimo-v2.5-pro" in compact
    assert "ctx: in 43 / out 8 / cache 12.3k / win 1m 1%" in compact


def test_detail_filter_limits_visible_blocks() -> None:
    view = RunView(chat_id=1, run_id="run", expanded=True)
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
    apply_run_event(
        view,
        RunEvent(
            kind="tool_started",
            tool_index=2,
            tool_name="Bash",
            summary="uv run bad",
        ),
    )
    apply_run_event(
        view,
        RunEvent(
            kind="tool_result",
            tool_index=2,
            output="error: failed",
            is_error=True,
        ),
    )

    view.detail_filter = "input"
    detail = render_detail(view)

    assert "详情: 输入 1/1" in detail
    assert "uv run pytest" in detail
    assert "passed" not in detail

    view.detail_filter = "error"
    detail = render_detail(view)

    assert "详情: 错误 1/1" in detail
    assert "#1 Bash" not in detail
    assert "#2 Bash" in detail
    assert "error: failed" in detail


def test_expanded_keyboard_has_filters_and_pagination() -> None:
    view = RunView(chat_id=1, run_id="run", expanded=True)
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

    _text, keyboard = render_run_view(view)

    assert keyboard is not None
    assert [button.text for button in keyboard.inline_keyboard[1]] == [
        "✓ 全部",
        "输入",
        "输出",
        "错误",
    ]
    assert [button.text for button in keyboard.inline_keyboard[2]] == [
        "‹ 上页",
        "1/2",
        "下页 ›",
    ]
