"""In-memory rendering state for Telegram run progress cards."""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from claude_code_tg.executor import RunEvent
from claude_code_tg.telegram_ui import copy_text_value, html_escape, html_escape_limited

COMPACT_TEXT_LIMIT = 1500
DETAIL_TEXT_LIMIT = 3500
RECENT_TOOL_LIMIT = 50
RUNS_PER_CHAT_LIMIT = 3
DETAIL_PAGE_SIZE = 4
DETAIL_FILTERS = ("all", "input", "output", "error")
CLI_DEFAULT_LABEL = "Claude Code 默认"

DetailFilter = Literal["all", "input", "output", "error"]


class RunViewCallback(NamedTuple):
    action: str
    chat_id: int
    run_id: str
    value: str = ""


@dataclass
class ToolView:
    index: int
    name: str
    summary: str = ""
    output: str = ""
    is_error: bool = False


@dataclass
class RunView:
    chat_id: int
    run_id: str
    draft_id: int = field(default_factory=lambda: _new_draft_id())
    task_summary: str = ""
    session_id: str = ""
    is_existing_session: bool = False
    git_branch: str = ""
    permission_mode: str = CLI_DEFAULT_LABEL
    model: str = CLI_DEFAULT_LABEL
    effort: str = CLI_DEFAULT_LABEL
    cli_args: tuple[str, ...] = ()
    runtime_model: str = ""
    runtime_permission_mode: str = ""
    runtime_fast_mode_state: str = ""
    ctx_input_tokens: int | None = None
    ctx_output_tokens: int | None = None
    ctx_cache_creation_tokens: int | None = None
    ctx_cache_read_tokens: int | None = None
    ctx_context_window: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    expanded: bool = False
    status: str = "running"
    current_tool_index: int | None = None
    current_text: str = ""
    total_tool_count: int = 0
    finished_at: float | None = None
    detail_filter: DetailFilter = "all"
    detail_page: int = 0
    tools: OrderedDict[int, ToolView] = field(default_factory=OrderedDict)

    @property
    def tool_count(self) -> int:
        return self.total_tool_count

    @property
    def latest_output(self) -> str:
        for tool in reversed(self.tools.values()):
            if tool.output:
                return tool.output
        return ""

    @property
    def current_tool(self) -> ToolView | None:
        if self.current_tool_index is None:
            return None
        return self.tools.get(self.current_tool_index)


class RunViewStore:
    """Small process-local store for run progress detail callbacks."""

    def __init__(self, *, per_chat_limit: int = RUNS_PER_CHAT_LIMIT) -> None:
        self._per_chat_limit = per_chat_limit
        self._views: dict[tuple[int, str], RunView] = {}
        self._chat_runs: dict[int, deque[str]] = {}

    def create(
        self,
        chat_id: int,
        *,
        prompt: str = "",
        session_id: str = "",
        is_existing_session: bool = False,
        git_branch: str = "",
        permission_mode: str = CLI_DEFAULT_LABEL,
        model: str = CLI_DEFAULT_LABEL,
        effort: str = CLI_DEFAULT_LABEL,
        cli_args: tuple[str, ...] = (),
    ) -> RunView:
        run_id = uuid.uuid4().hex[:10]
        view = RunView(
            chat_id=chat_id,
            run_id=run_id,
            task_summary=summarize_task(prompt),
            session_id=session_id,
            is_existing_session=is_existing_session,
            git_branch=git_branch,
            permission_mode=permission_mode,
            model=model,
            effort=effort,
            cli_args=cli_args,
        )
        key = (chat_id, run_id)
        self._views[key] = view
        runs = self._chat_runs.setdefault(chat_id, deque())
        runs.append(run_id)
        while len(runs) > self._per_chat_limit:
            old_run_id = runs.popleft()
            self._views.pop((chat_id, old_run_id), None)
        return view

    def get(self, chat_id: int, run_id: str) -> RunView | None:
        return self._views.get((chat_id, run_id))

    def latest(self, chat_id: int) -> RunView | None:
        runs = self._chat_runs.get(chat_id)
        if not runs:
            return None
        return self._views.get((chat_id, runs[-1]))


def apply_run_event(view: RunView, event: RunEvent) -> None:
    _apply_runtime(view, event)
    _apply_usage(view, event)
    if event.kind in {"runtime", "usage"}:
        return

    if event.kind == "tool_started":
        index = event.tool_index or (view.total_tool_count + 1)
        view.total_tool_count = max(view.total_tool_count, index)
        view.tools[index] = ToolView(
            index=index,
            name=event.tool_name or "tool",
            summary=event.summary,
        )
        view.current_tool_index = index
        view.current_text = ""
        _trim_tools(view)
        return

    if event.kind == "tool_result":
        tool = _resolve_tool(view, event.tool_index)
        if tool:
            tool.output = event.output
            tool.is_error = event.is_error
            view.current_tool_index = tool.index
        view.current_text = ""
        return

    if event.kind == "assistant_text":
        view.current_text = event.text
        return

    if event.kind == "run_completed":
        view.status = "completed"
        view.current_text = event.text
        view.finished_at = view.finished_at or time.monotonic()
        return

    if event.kind == "run_error":
        view.status = "failed"
        view.current_text = event.text
        view.finished_at = view.finished_at or time.monotonic()


def render_run_view(view: RunView) -> tuple[str, InlineKeyboardMarkup | None]:
    text = render_detail(view) if view.expanded else render_compact(view)
    return text, build_run_keyboard(view)


def render_compact(view: RunView) -> str:
    status_label = _status_label(view.status)
    elapsed = _format_elapsed(_elapsed_seconds(view))
    lines = [
        f"<b>{status_label}</b> {elapsed}",
    ]
    if view.task_summary:
        task_summary = summarize_task(view.task_summary, limit=180)
        lines.append(f"任务: {html_escape_limited(task_summary, 180)}")
    lines.append(_session_line(view))
    if view.git_branch:
        lines.append(f"分支: {html_escape_limited(view.git_branch, 80)}")
    lines.append(f"权限模式: {html_escape_limited(_permission_label(view), 80)}")
    lines.append(f"模型: {html_escape_limited(_model_label(view), 140)}")
    lines.append(f"思考强度: {html_escape_limited(_effort_label(view), 120)}")
    lines.append(_cli_args_line(view))
    lines.append(_ctx_line(view))
    lines.append(f"工具: {view.tool_count}")
    current = view.current_tool
    if current:
        name = html_escape_limited(current.name, 80)
        if current.output:
            state = "错误输出" if current.is_error or _has_error(current) else "已返回"
            lines.append(f"最近: #{current.index} {name} {state}")
        else:
            lines.append(f"当前: #{current.index} {name}")
    elif view.current_text and view.status == "running":
        lines.append("当前: 模型回复中")
    elif view.current_text and view.status == "failed":
        lines.append(_block("错误", view.current_text, limit=420))

    if view.tools:
        lines.append("工具输入/输出已折叠，点详情查看。")

    return "\n".join(lines)


def render_detail(view: RunView) -> str:
    status_label = _status_label(view.status)
    elapsed = _format_elapsed(_elapsed_seconds(view))
    tools = _filtered_tools(view)
    page_count = _page_count(len(tools))
    page = _clamp_page(view.detail_page, page_count)
    page_tools = _page_tools(tools, page)
    lines = [
        f"<b>{status_label}</b> {elapsed}",
    ]
    if view.task_summary:
        task_summary = summarize_task(view.task_summary, limit=180)
        lines.append(f"任务: {html_escape_limited(task_summary, 180)}")
    lines.append(_session_line(view))
    if view.git_branch:
        lines.append(f"分支: {html_escape_limited(view.git_branch, 80)}")
    lines.extend(
        [
            f"权限模式: {html_escape_limited(_permission_label(view), 80)}",
            f"模型: {html_escape_limited(_model_label(view), 140)}",
            f"思考强度: {html_escape_limited(_effort_label(view), 120)}",
            _cli_args_line(view),
            _ctx_line(view),
            f"工具: {view.tool_count}",
            "",
            f"详情: {_filter_label(view.detail_filter)} {page + 1}/{page_count}",
        ]
    )
    if not view.tools:
        lines.append("暂无工具调用。")
    elif not page_tools:
        lines.append("暂无匹配工具。")
    else:
        summary_limit, output_limit = _detail_block_limits(len(page_tools))
        for tool in page_tools:
            name = html_escape_limited(tool.name, 80)
            lines.append(f"#{tool.index} {name}")
            if view.detail_filter in {"all", "input"} and tool.summary:
                lines.append(_block("输入", tool.summary, limit=summary_limit))
            if view.detail_filter in {"all", "output", "error"} and tool.output:
                label = "错误输出" if tool.is_error else "输出尾部"
                lines.append(_block(label, tool.output, limit=output_limit))
            lines.append("")
    if view.current_text and not view.tools and view.status == "failed":
        lines.append(_block("错误", view.current_text, limit=500))
    return "\n".join(lines).rstrip()


def build_run_keyboard(view: RunView) -> InlineKeyboardMarkup | None:
    if view.status == "expired":
        return None
    has_details = bool(view.tools) or (
        view.status == "failed" and bool(view.current_text)
    )
    first_row = []
    if has_details:
        toggle_label = "收起" if view.expanded else "详情"
        toggle_action = "compact" if view.expanded else "detail"
        first_row.append(
            InlineKeyboardButton(
                toggle_label,
                callback_data=f"run:{toggle_action}:{view.chat_id}:{view.run_id}",
                style="primary",
            )
        )
    copy_text = _copy_text(view)
    if copy_text:
        first_row.append(
            InlineKeyboardButton(
                "复制",
                copy_text=CopyTextButton(copy_text),
            )
        )
    if view.status == "running":
        first_row.append(
            InlineKeyboardButton(
                "⏹ Stop",
                callback_data=f"stop:{view.chat_id}",
                style="danger",
            )
        )
    if not first_row:
        return None
    rows = [first_row]
    if view.expanded and has_details and view.tools:
        rows.append(_filter_row(view))
        page_row = _page_row(view)
        if page_row:
            rows.append(page_row)
    return InlineKeyboardMarkup(rows)


def parse_run_view_callback(data: str) -> RunViewCallback | None:
    parts = data.split(":")
    if len(parts) < 4 or parts[0] != "run":
        return None
    action, raw_chat_id, run_id = parts[1], parts[2], parts[3]
    if action not in {"detail", "compact", "page", "filter"} or not run_id:
        return None
    if action in {"detail", "compact"} and len(parts) != 4:
        return None
    if action in {"page", "filter"} and len(parts) != 5:
        return None
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    if raw_chat_id != str(chat_id):
        return None
    value = parts[4] if len(parts) == 5 else ""
    if action == "page" and not _valid_page_value(value):
        return None
    if action == "filter" and value not in DETAIL_FILTERS:
        return None
    return RunViewCallback(action, chat_id, run_id, value)


def _resolve_tool(view: RunView, index: int | None) -> ToolView | None:
    if index is not None and index in view.tools:
        return view.tools[index]
    if view.current_tool_index is not None:
        return view.tools.get(view.current_tool_index)
    if view.tools:
        return next(reversed(view.tools.values()))
    return None


def _trim_tools(view: RunView) -> None:
    while len(view.tools) > RECENT_TOOL_LIMIT:
        view.tools.popitem(last=False)


def _apply_usage(view: RunView, event: RunEvent) -> None:
    if event.input_tokens is not None:
        view.ctx_input_tokens = event.input_tokens
    if event.output_tokens is not None:
        view.ctx_output_tokens = event.output_tokens
    if event.cache_creation_input_tokens is not None:
        view.ctx_cache_creation_tokens = event.cache_creation_input_tokens
    if event.cache_read_input_tokens is not None:
        view.ctx_cache_read_tokens = event.cache_read_input_tokens
    if event.context_window is not None:
        view.ctx_context_window = event.context_window


def _apply_runtime(view: RunView, event: RunEvent) -> None:
    if event.runtime_model:
        view.runtime_model = event.runtime_model
    if event.runtime_permission_mode:
        view.runtime_permission_mode = event.runtime_permission_mode
    if event.runtime_fast_mode_state:
        view.runtime_fast_mode_state = event.runtime_fast_mode_state


def summarize_task(prompt: str, *, limit: int = 120) -> str:
    summary = " ".join(prompt.strip().split())
    if not summary:
        return "（空）"
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3].rstrip() + "..."


def _filtered_tools(view: RunView) -> list[ToolView]:
    if view.detail_filter == "input":
        return [tool for tool in view.tools.values() if tool.summary]
    if view.detail_filter == "output":
        return [tool for tool in view.tools.values() if tool.output]
    if view.detail_filter == "error":
        return [
            tool for tool in view.tools.values() if tool.is_error or _has_error(tool)
        ]
    return list(view.tools.values())


def _has_error(tool: ToolView) -> bool:
    if tool.is_error:
        return True
    return "error" in tool.output.lower() or "traceback" in tool.output.lower()


def _page_count(item_count: int) -> int:
    if item_count <= 0:
        return 1
    return ((item_count - 1) // DETAIL_PAGE_SIZE) + 1


def _clamp_page(page: int, page_count: int) -> int:
    return min(max(0, page), max(0, page_count - 1))


def _page_tools(tools: list[ToolView], page: int) -> list[ToolView]:
    start = page * DETAIL_PAGE_SIZE
    return tools[start : start + DETAIL_PAGE_SIZE]


def _filter_label(detail_filter: DetailFilter) -> str:
    labels = {
        "all": "全部",
        "input": "输入",
        "output": "输出",
        "error": "错误",
    }
    return labels[detail_filter]


def _filter_row(view: RunView) -> list[InlineKeyboardButton]:
    labels = {
        "all": "全部",
        "input": "输入",
        "output": "输出",
        "error": "错误",
    }
    return [
        InlineKeyboardButton(
            f"✓ {label}" if key == view.detail_filter else label,
            callback_data=f"run:filter:{view.chat_id}:{view.run_id}:{key}",
            style="primary" if key == view.detail_filter else None,
        )
        for key, label in labels.items()
    ]


def _page_row(view: RunView) -> list[InlineKeyboardButton]:
    tools = _filtered_tools(view)
    page_count = _page_count(len(tools))
    if page_count <= 1:
        return []
    page = _clamp_page(view.detail_page, page_count)
    previous_page = max(0, page - 1)
    next_page = min(page_count - 1, page + 1)
    return [
        InlineKeyboardButton(
            "‹ 上页",
            callback_data=f"run:page:{view.chat_id}:{view.run_id}:{previous_page}",
        ),
        InlineKeyboardButton(
            f"{page + 1}/{page_count}",
            callback_data=f"run:page:{view.chat_id}:{view.run_id}:{page}",
        ),
        InlineKeyboardButton(
            "下页 ›",
            callback_data=f"run:page:{view.chat_id}:{view.run_id}:{next_page}",
        ),
    ]


def _valid_page_value(value: str) -> bool:
    if not value or value.startswith(("+", "-")):
        return False
    try:
        int(value)
    except ValueError:
        return False
    return True


def _new_draft_id() -> int:
    value = int(uuid.uuid4().hex[:8], 16) & 0x7FFFFFFF
    return value or 1


def _session_line(view: RunView) -> str:
    action = "继续" if view.is_existing_session else "新建"
    if not view.session_id:
        return f"会话: {action}"
    short_id = (
        view.session_id[:8] + "..." if len(view.session_id) > 8 else view.session_id
    )
    return f"会话: {action} {html_escape_limited(short_id, 80)}"


def _permission_label(view: RunView) -> str:
    return view.runtime_permission_mode or view.permission_mode


def _model_label(view: RunView) -> str:
    if view.runtime_model:
        if view.model not in {"", CLI_DEFAULT_LABEL, view.runtime_model}:
            return f"{view.runtime_model} (由 {view.model})"
        return view.runtime_model
    if view.model == CLI_DEFAULT_LABEL:
        return f"{CLI_DEFAULT_LABEL} (等待 CLI 回传)"
    return view.model


def _effort_label(view: RunView) -> str:
    if view.effort == CLI_DEFAULT_LABEL:
        return f"{CLI_DEFAULT_LABEL} (CLI 未回传具体档位)"
    return view.effort


def _cli_args_line(view: RunView) -> str:
    if not view.cli_args:
        return "CLI 参数: 使用 Claude 默认"
    return f"CLI 参数: {html_escape_limited(' '.join(view.cli_args), 220)}"


def _ctx_line(view: RunView) -> str:
    if (
        view.ctx_input_tokens is None
        and view.ctx_output_tokens is None
        and view.ctx_cache_creation_tokens is None
        and view.ctx_cache_read_tokens is None
    ):
        if view.ctx_context_window is not None:
            return f"ctx: 0 / win {_format_token_count(view.ctx_context_window)}"
        return "ctx: 等待 CLI 回传"
    parts: list[str] = []
    if view.ctx_input_tokens is not None:
        parts.append(f"in {_format_token_count(view.ctx_input_tokens)}")
    if view.ctx_output_tokens is not None:
        parts.append(f"out {_format_token_count(view.ctx_output_tokens)}")
    cache_tokens = (view.ctx_cache_creation_tokens or 0) + (
        view.ctx_cache_read_tokens or 0
    )
    if cache_tokens:
        parts.append(f"cache {_format_token_count(cache_tokens)}")
    if view.ctx_context_window is not None:
        used_tokens = (view.ctx_input_tokens or 0) + cache_tokens
        percentage = _format_percentage(used_tokens, view.ctx_context_window)
        parts.append(f"win {_format_token_count(view.ctx_context_window)} {percentage}")
    return "ctx: " + " / ".join(parts)


def _format_percentage(value: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{min(100, round((value / total) * 100))}%"


def _format_token_count(value: int) -> str:
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}m"
    elif value >= 1_000:
        text = f"{value / 1_000:.1f}k"
    else:
        return str(value)
    return text.replace(".0", "")


def _block(label: str, text: str, *, limit: int) -> str:
    body = html_escape_limited(text, limit)
    return f"{html_escape(label)}:\n<pre>{body}</pre>"


def _copy_text(view: RunView) -> str:
    if not view.expanded and view.tools:
        return ""
    current = view.current_tool
    if current and current.summary:
        return copy_text_value(current.summary)
    latest_output = view.latest_output
    if latest_output:
        return copy_text_value(latest_output)
    return ""


def _detail_block_limits(tool_count: int) -> tuple[int, int]:
    if tool_count <= 0:
        return 500, 700
    per_tool = max(180, (DETAIL_TEXT_LIMIT - 600) // tool_count)
    summary_limit = max(60, min(220, per_tool // 3))
    output_limit = max(100, min(420, per_tool - summary_limit - 80))
    return summary_limit, output_limit


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"0:{secs:02d}"


def _elapsed_seconds(view: RunView) -> float:
    return (view.finished_at or time.monotonic()) - view.started_at


def _status_label(status: str) -> str:
    if status == "completed":
        return "✅ 完成"
    if status == "stopped":
        return "⏹ 已停止"
    if status == "failed":
        return "❌ 结束"
    return "⏳ 执行中"
