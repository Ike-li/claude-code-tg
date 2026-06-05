"""Telegram command handlers for TGBot."""

import logging
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import cast

from telegram import ForceReply, Message, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from claude_code_tg.claude_sessions import ClaudeSessionInfo, discover_project_sessions
from claude_code_tg.command_menu import (
    build_runnable_claude_commands,
    load_or_probe_slash_commands,
)
from claude_code_tg.command_view import (
    CommandPickerStore,
    build_command_keyboard,
    parse_command_callback,
)
from claude_code_tg.executor import (
    VALID_PERMISSION_MODES,
    Executor,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.message_output import send_pages
from claude_code_tg.pending_reply import PendingReplyIntent, PendingReplyStore
from claude_code_tg.result_view import ResultActionStore, parse_result_callback
from claude_code_tg.resume_view import (
    RESUME_BUTTON_LIMIT,
    ResumePickerStore,
    build_resume_keyboard,
    parse_resume_callback,
)
from claude_code_tg.run_view import (
    DetailFilter,
    RunViewStore,
    parse_run_view_callback,
    render_run_view,
)
from claude_code_tg.sessions import (
    ChatSessionStore,
    ClaudeRuntimeStatus,
    QueuedPrompt,
    ReplyCallback,
)
from claude_code_tg.telegram_ui import (
    EFFORT_CHOICES,
    HTML_PARSE_MODE,
    build_setting_keyboard,
    build_status_keyboard,
    parse_setting_callback,
)

BYTES_PER_MIB = 1024 * 1024

# Bot control commands published to the Telegram menu (name, description).
# Source of truth for the static part of the menu; Claude project commands are
# appended dynamically after probing.
BOT_CONTROL_COMMANDS: list[tuple[str, str]] = [
    ("new", "开始新会话"),
    ("resume", "列出/接管 Claude session（/resume <id>）"),
    ("clear", "Claude /clear：清空当前上下文"),
    ("model", "Claude /model：设置模型"),
    ("effort", "Claude --effort：设置思考强度"),
    ("permissions", "Claude /permissions：设置权限模式"),
    ("context", "Claude /context：查看上下文"),
    ("usage", "Claude /usage：查看用量"),
    ("cost", "Claude /cost：查看成本"),
    ("reload_skills", "Claude /reload-skills：刷新技能"),
    ("stop", "停止当前执行"),
    ("status", "查看状态和附件模式"),
    ("run", "透传任意 Claude Code 命令（/run <cmd>）"),
    ("commands", "列出可透传的 Claude Code 命令"),
    ("help", "显示帮助"),
]
BOT_COMMAND_ALIASES = frozenset({"attach", "mode", "sessions"})
RESERVED_BOT_COMMAND_NAMES = frozenset(
    {name for name, _ in BOT_CONTROL_COMMANDS} | BOT_COMMAND_ALIASES
)

COMMAND_REFRESH_ARGS = {"refresh", "--refresh", "-r"}
RESUME_ALL_ARGS = frozenset({"--all", "-a"})
RESUME_DEFAULT_LIMIT = RESUME_BUTTON_LIMIT
RESUME_BODY_TITLE_LIMIT = 46
logger = logging.getLogger(__name__)

HEADLESS_BUILTIN_CLAUDE_COMMANDS = {
    "cost": "cost",
    "context": "context",
    "reload_skills": "reload-skills",
    "usage": "usage",
}


def _message_context(update: Update) -> tuple[int, int, Message] | None:
    user = update.effective_user
    chat = update.effective_chat
    message = update.message
    if user is None or chat is None or message is None:
        return None
    return user.id, chat.id, message


def _parse_stop_callback_chat_id(data: str) -> int | None:
    prefix, sep, raw_chat_id = data.partition(":")
    if prefix != "stop" or sep != ":" or not raw_chat_id:
        return None
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    if raw_chat_id != str(chat_id):
        return None
    return chat_id


def _is_force_reply_message(message: Message | None) -> bool:
    return isinstance(getattr(message, "reply_markup", None), ForceReply)


def _is_reply_to_this_bot(
    message: Message | None,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    from_user = getattr(message, "from_user", None)
    from_user_id = getattr(from_user, "id", None)
    bot_id = getattr(context.bot, "id", None)
    return isinstance(bot_id, int) and from_user_id == bot_id


def _normalize_forced_run_command(text: str) -> str:
    command = text.strip()
    if command.lower().startswith("/run "):
        command = command[5:].strip()
    if not command.startswith("/"):
        command = f"/{command}"
    return command


class BotCommandHandlers:
    attachment_max_bytes: int
    attachment_mode: str
    busy: set[int]
    claude_command_map: dict[str, str]
    command_pickers: CommandPickerStore
    command_menu_cache_file: Path | None
    executor: Executor
    effort_overrides: dict[int, str]
    model_overrides: dict[int, str]
    permission_modes: dict[int, str]
    pending_replies: PendingReplyStore
    result_actions: ResultActionStore
    run_views: RunViewStore
    queue_max_size: int
    queues: dict[int, deque[QueuedPrompt]]
    project_dir: str
    resume_pickers: ResumePickerStore
    sessions: dict[int, str]
    state: ChatSessionStore
    _is_authorized: Callable[[int], bool]
    _effort_label: Callable[[int], str]
    _model_label: Callable[[int], str]
    _normalize_session_id: Callable[[str], str | None]
    _permission_mode_label: Callable[[int], str]
    _process_message: Callable[
        [int, int, str, ContextTypes.DEFAULT_TYPE],
        Awaitable[None],
    ]
    _try_enqueue: Callable[[int, int, str, ReplyCallback], Awaitable[bool]]
    _write_status: Callable[[], None]

    async def handle_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        dropped = self.state.reset_chat(chat_id)
        stopped = await self.executor.stop(chat_id) if chat_id in self.busy else False
        logger.info(
            "New session | chat_id=%s permission_mode=%s stopped=%s dropped=%s",
            chat_id,
            self._permission_mode_label(chat_id),
            stopped,
            dropped,
        )
        await message.reply_text(
            self._new_session_text(chat_id, stopped=stopped, dropped=dropped)
        )
        self._write_status()

    async def handle_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Telegram wrapper for Claude's /clear semantics."""
        await self.handle_new(update, context)

    async def handle_attach(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        if not context.args:
            await self._send_force_reply_prompt(
                message,
                chat_id,
                user_id,
                "resume",
                "用法: /resume <session_id>\n"
                "/attach 是兼容别名。\n"
                "当前 chat 的完整 session_id 可用 /status 查看；"
                "当前项目的本地 Claude 历史可用 /resume 列出。\n"
                "回复这条消息输入完整 session_id。",
                placeholder="session_id",
            )
            return

        await self._attach_session_id(chat_id, message, context.args[0])

    async def handle_resume(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return

        if context.args:
            if len(context.args) == 1 and self._normalize_session_id(context.args[0]):
                await self._attach_session_id(chat_id, message, context.args[0])
                return
            await self._send_resume_history(
                user_id, chat_id, message, context, resume_args=context.args
            )
            return

        await self._send_resume_history(user_id, chat_id, message, context)

    async def _attach_session_id(
        self,
        chat_id: int,
        message: Message,
        raw_session_id: str,
    ) -> None:
        session_id = self._normalize_session_id(raw_session_id)
        if not session_id:
            await message.reply_text("无效的 session_id：请提供 Claude Code UUID。")
            return

        await message.reply_text(await self._attach_session_text(chat_id, session_id))

    async def handle_sessions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return

        await self._send_resume_history(user_id, chat_id, message, context)

    async def _send_resume_history(
        self,
        user_id: int,
        chat_id: int,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        resume_args: Sequence[str] = (),
    ) -> None:
        query, show_all = _parse_resume_history_args(resume_args)
        sessions = discover_project_sessions(self.project_dir, include_headless=True)
        if not sessions:
            await message.reply_text(
                "未发现当前项目的本地 Claude Code session。\n"
                "直接发送消息会创建新会话；已有 session 后可用 /status 查看当前 chat 的完整 session_id。\n"
                "发送 /resume <session_id> 可手动接管。"
            )
            return

        matched_sessions = _filter_resume_sessions(sessions, query)
        if not matched_sessions:
            await message.reply_text(
                f"未找到匹配“{query}”的 session。\n"
                f"发送 /resume 查看最近 {RESUME_DEFAULT_LIMIT} 个，"
                "或 /resume --all 查看全部。"
            )
            return

        visible_sessions = (
            matched_sessions if show_all else matched_sessions[:RESUME_DEFAULT_LIMIT]
        )
        hidden_count = len(matched_sessions) - len(visible_sessions)
        current_session = self.sessions.get(chat_id)
        keyboard = build_resume_keyboard(
            chat_id,
            visible_sessions,
            current_session,
            self.resume_pickers,
        )
        heading = "🧵 Claude Code sessions（本地/tgcc）"
        if query:
            heading = f"🧵 Claude Code sessions（搜索：{query}）"
        elif show_all:
            heading = "🧵 Claude Code sessions（全部）"

        lines = [
            heading,
        ]
        if hidden_count:
            if query:
                lines.extend(
                    [
                        f"匹配 {len(visible_sessions)} / {len(matched_sessions)}。"
                        "点按钮接管，复制ID备用。",
                        f"显示全部结果：/resume {query} --all。",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"最近 {len(visible_sessions)} / 共 {len(sessions)}。"
                        "点按钮接管，复制ID备用。",
                        "搜索示例：/resume 模型；显示全部：/resume --all。",
                    ]
                )
        elif query:
            lines.append(f"匹配 {len(matched_sessions)} 个。点按钮接管，复制ID备用。")
        elif show_all:
            lines.append(f"共 {len(matched_sessions)} 个。点按钮接管，复制ID备用。")
        else:
            lines.append(f"共 {len(matched_sessions)} 个。点按钮接管，复制ID备用。")
        lines.append("")

        compact = not show_all and query is None
        for index, item in enumerate(visible_sessions, start=1):
            lines.append(
                _format_resume_session(
                    item,
                    index=index,
                    current_session=current_session,
                    compact=compact,
                )
            )
        await send_pages(chat_id, "\n".join(lines), context, reply_markup=keyboard)

    async def handle_stop_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        stopped = await self.executor.stop(chat_id)
        if stopped:
            await message.reply_text("⏹ 已停止。")
        else:
            await message.reply_text("没有正在执行的任务。")

    async def handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        text = self._status_text(chat_id)
        await message.reply_text(
            text,
            reply_markup=build_status_keyboard(text, self.sessions.get(chat_id)),
        )

    async def handle_mode(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._handle_permission_mode(update, context, "/mode")

    async def handle_permissions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Telegram wrapper for Claude's interactive /permissions command."""
        await self._handle_permission_mode(update, context, "/permissions")

    async def _handle_permission_mode(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        command_name: str,
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        if not context.args:
            await self._send_force_reply_prompt(
                message,
                chat_id,
                user_id,
                "permissions",
                "回复这条消息输入自定义权限模式，或输入 reset 重置。",
                placeholder="plan",
            )
            modes = ", ".join(sorted(VALID_PERMISSION_MODES))
            await message.reply_text(
                f"当前权限模式: {self._permission_mode_label(chat_id)}\n"
                f"可选: {modes}\n"
                f"用法: {command_name} <mode> 或 {command_name} reset",
                reply_markup=build_setting_keyboard("perm", chat_id),
            )
            return

        raw_mode = context.args[0]
        if raw_mode.lower() == "reset":
            self.permission_modes.pop(chat_id, None)
            self._write_status()
            await message.reply_text(
                f"权限模式已重置为: {self._permission_mode_label(chat_id)}"
            )
            return

        try:
            mode = normalize_permission_mode(raw_mode)
        except ValueError:
            modes = ", ".join(sorted(VALID_PERMISSION_MODES))
            await message.reply_text(f"无效的权限模式。可选: {modes}")
            return
        assert mode is not None
        self.permission_modes[chat_id] = mode
        self._write_status()
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        await message.reply_text(f"权限模式已设置为 {mode}，{suffix}")

    async def handle_model(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        if not context.args:
            await self._send_force_reply_prompt(
                message,
                chat_id,
                user_id,
                "model",
                "回复这条消息输入自定义 Claude 模型，或输入 reset 重置。",
                placeholder="sonnet",
            )
            await message.reply_text(
                f"当前模型: {self._model_label(chat_id)}\n"
                "可用 Claude Code alias 或完整模型名，例如: sonnet, opus\n"
                "用法: /model <model> 或 /model reset",
                reply_markup=build_setting_keyboard("model", chat_id),
            )
            return

        raw_model = context.args[0]
        if raw_model.lower() == "reset":
            self.model_overrides.pop(chat_id, None)
            self._write_status()
            await message.reply_text(f"模型已重置为: {self._model_label(chat_id)}")
            return

        try:
            model = normalize_model(raw_model)
        except ValueError:
            await message.reply_text(
                "无效的模型名。请使用 Claude Code alias 或完整模型名，例如: sonnet, opus"
            )
            return
        if model is None:
            self.model_overrides.pop(chat_id, None)
            self._write_status()
            await message.reply_text(f"模型已重置为: {self._model_label(chat_id)}")
            return

        self.model_overrides[chat_id] = model
        self._write_status()
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        await message.reply_text(f"模型已设置为 {model}，{suffix}")

    async def handle_effort(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        if not context.args:
            levels = ", ".join(EFFORT_CHOICES)
            await message.reply_text(
                f"当前思考强度: {self._effort_label(chat_id)}\n"
                f"可选: {levels}\n"
                "用法: /effort <level> 或 /effort reset",
                reply_markup=build_setting_keyboard("effort", chat_id),
            )
            return

        raw_effort = context.args[0]
        if raw_effort.lower() == "reset":
            self.effort_overrides.pop(chat_id, None)
            self._write_status()
            await message.reply_text(f"思考强度已重置为: {self._effort_label(chat_id)}")
            return

        try:
            effort = normalize_effort(raw_effort)
        except ValueError:
            levels = ", ".join(EFFORT_CHOICES)
            await message.reply_text(f"无效的思考强度。可选: {levels}")
            return
        if effort is None:
            self.effort_overrides.pop(chat_id, None)
            self._write_status()
            await message.reply_text(f"思考强度已重置为: {self._effort_label(chat_id)}")
            return

        self.effort_overrides[chat_id] = effort
        self._write_status()
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        await message.reply_text(f"思考强度已设置为 {effort}，{suffix}")

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        permission_mode = self._permission_mode_label(chat_id)
        effort = self._effort_label(chat_id)
        logger.info(
            "Start command | chat_id=%s permission_mode=%s effort=%s",
            chat_id,
            permission_mode,
            effort,
        )
        await message.reply_text(
            "👋 Claude Code TG Bot 已就绪。\n"
            f"当前权限模式: {permission_mode}\n"
            f"当前思考强度: {effort}\n"
            "直接发送文本开始对话，输入 /help 查看命令列表。"
        )

    async def handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, _chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        help_text = (
            "📖 命令列表\n\n"
            "/new — 开始新会话\n"
            "/resume [session_id|关键词|--all] — 查找或接管本地 Claude session\n"
            "/clear — 清空当前 Claude 上下文\n"
            "/model <model> — 设置 Claude 模型\n"
            "/effort <level> — 设置 Claude 思考强度\n"
            "/permissions <mode> — 设置 Claude 权限模式\n"
            "/context — 查看 Claude 上下文\n"
            "/usage — 查看 Claude 用量\n"
            "/cost — 查看 Claude 成本\n"
            "/reload_skills — 刷新 Claude 技能\n"
            "/stop — 停止当前执行\n"
            "/status — 查看状态和附件模式\n"
            "/commands — 列出可透传的 Claude Code 命令\n"
            "/run <cmd> — 透传 Claude Code 命令\n"
            "/help — 显示帮助\n"
        )
        help_text += (
            "\nClaude Code 命令请用 /commands 查看，再用 /run 透传。\n"
            "直接发送文本即可与 Claude Code 对话。\n群聊中需 @bot 或回复 bot 消息。"
        )
        await message.reply_text(help_text)

    def _attachment_config_label(self) -> str:
        return (
            f"{self.attachment_mode}, "
            f"单个附件≤{_format_mib_limit(self.attachment_max_bytes)}"
        )

    def _status_text(self, chat_id: int) -> str:
        session_id = self.sessions.get(chat_id)
        status = "🟢 空闲" if chat_id not in self.busy else "🔴 执行中"
        session_info = f"会话: {session_id}" if session_id else "会话: 无"
        queue_len = len(self.queues.get(chat_id, []))
        runtime_status = self.state.runtime_status(chat_id)
        return (
            f"📊 状态\n{status}\n{session_info}\n"
            f"权限模式: {self._permission_mode_label(chat_id)}\n"
            f"模型: {self._model_label(chat_id)}\n"
            f"思考强度: {self._effort_label(chat_id)}\n"
            f"队列: {queue_len}/{self.queue_max_size}\n"
            f"附件: {self._attachment_config_label()}\n"
            f"{_runtime_status_text(runtime_status)}"
        )

    async def handle_run(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        if not context.args:
            await self._send_force_reply_prompt(
                message,
                chat_id,
                user_id,
                "run",
                "回复这条消息输入 Claude Code 命令，例如 /compact 或 /verify。",
                placeholder="/compact",
            )
            return
        prompt = " ".join(context.args)

        if await self._try_enqueue(chat_id, user_id, prompt, message.reply_text):
            return

        await self._process_message(chat_id, user_id, prompt, context)

    async def handle_builtin_claude_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Forward a verified headless-safe Claude built-in slash command."""
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        head, _, rest = (message.text or "").partition(" ")
        token = head.lstrip("/").split("@", 1)[0].lower()
        claude_command = HEADLESS_BUILTIN_CLAUDE_COMMANDS.get(token)
        if not claude_command:
            return
        prompt = f"/{claude_command} {rest.strip()}".rstrip()

        if await self._try_enqueue(chat_id, user_id, prompt, message.reply_text):
            return

        await self._process_message(chat_id, user_id, prompt, context)

    async def handle_commands(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return

        raw_args = getattr(context, "args", []) or []
        args = raw_args if isinstance(raw_args, (list, tuple)) else []
        refresh = any(str(arg).lower() in COMMAND_REFRESH_ARGS for arg in args)
        try:
            probed = await load_or_probe_slash_commands(
                self.project_dir,
                self.command_menu_cache_file,
                refresh=refresh,
            )
        except Exception as exc:
            await message.reply_text(f"❌ Claude 命令探测失败: {type(exc).__name__}")
            return

        commands = build_runnable_claude_commands(
            probed, reserved_names=set(RESERVED_BOT_COMMAND_NAMES)
        )
        if not commands:
            await message.reply_text(
                "未发现可透传的 Claude Code 命令。\n"
                "可继续用 /run /命令 手动尝试已知命令。"
            )
            return

        lines = [
            "🔧 Claude Code 命令",
            "点按钮执行，或复制整行执行；用 /commands refresh 可刷新缓存。",
        ]
        if refresh:
            lines.append("缓存已刷新。")
        lines.append("")
        lines.extend(f"/run /{command}" for command in commands)
        keyboard = build_command_keyboard(chat_id, commands, self.command_pickers)
        await send_pages(chat_id, "\n".join(lines), context, reply_markup=keyboard)

    async def handle_claude_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Forward a probed Claude slash command tapped from the Telegram menu.

        Reverse-maps the Telegram-safe command name back to its Claude name and
        feeds ``/<command> <args>`` to the executor, mirroring ``handle_run``.
        """
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        head, _, rest = (message.text or "").partition(" ")
        token = head.lstrip("/").split("@", 1)[0].lower()
        claude_command = self.claude_command_map.get(token)
        if not claude_command:
            return
        prompt = f"/{claude_command} {rest.strip()}".rstrip()

        if await self._try_enqueue(chat_id, user_id, prompt, message.reply_text):
            return

        await self._process_message(chat_id, user_id, prompt, context)

    async def handle_stop_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        if not self._is_authorized(query.from_user.id):
            return

        chat_id = _parse_stop_callback_chat_id(query.data)
        if chat_id is None:
            return

        # Security: only allow stopping tasks in the same chat
        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            return

        stopped = await self.executor.stop(chat_id)
        if stopped:
            await query.edit_message_text("⏹ 已停止。")
        else:
            await query.edit_message_text("✅ 已完成。")

    async def handle_run_view_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        if not self._is_authorized(query.from_user.id):
            return

        parsed = parse_run_view_callback(query.data)
        if parsed is None:
            return
        action, chat_id, run_id, value = parsed

        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            return

        view = self.run_views.get(chat_id, run_id)
        if view is None:
            await query.answer("详情已过期")
            return

        if action == "detail":
            view.expanded = True
            view.detail_filter = "all"
            view.detail_page = 0
        elif action == "compact":
            view.expanded = False
        elif action == "filter":
            view.expanded = True
            view.detail_filter = cast(DetailFilter, value)
            view.detail_page = 0
        elif action == "page":
            view.expanded = True
            try:
                view.detail_page = int(value)
            except ValueError:
                await query.answer("无效的页码")
                return
        text, keyboard = render_run_view(view)
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=HTML_PARSE_MODE,
        )

    async def handle_resume_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        if not self._is_authorized(query.from_user.id):
            return

        parsed = parse_resume_callback(query.data)
        if parsed is None:
            return
        chat_id, picker_id, token = parsed

        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            return

        if token == "noop":
            await query.answer("请发送 /resume 查看完整 session_id")
            return

        session_id = self.resume_pickers.resolve(chat_id, picker_id, token)
        if session_id is None:
            await query.answer("session 列表已过期")
            return

        text = await self._attach_session_text(chat_id, session_id)
        await query.edit_message_text(text)

    async def handle_command_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return

        if not self._is_authorized(query.from_user.id):
            await query.answer()
            return

        parsed = parse_command_callback(query.data)
        if parsed is None:
            await query.answer()
            return
        chat_id, picker_id, token = parsed

        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            await query.answer()
            return

        if token == "noop":
            await query.answer("可复制文本列表里的完整命令")
            return

        command = self.command_pickers.resolve(chat_id, picker_id, token)
        if command is None:
            await query.answer("命令列表已过期")
            return

        prompt = f"/{command.strip().lstrip('/')}"

        async def reply_enqueue(text: str) -> None:
            await query.answer(text)
            await context.bot.send_message(chat_id=chat_id, text=text)

        if await self._try_enqueue(chat_id, query.from_user.id, prompt, reply_enqueue):
            return

        await query.answer(f"执行 {prompt}")
        await self._process_message(chat_id, query.from_user.id, prompt, context)

    async def handle_result_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return

        if not self._is_authorized(query.from_user.id):
            await query.answer()
            return

        parsed = parse_result_callback(query.data)
        if parsed is None:
            await query.answer()
            return
        action, chat_id, token = parsed

        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            await query.answer()
            return

        if action == "status":
            await query.answer("当前状态")
            text = self._status_text(chat_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=build_status_keyboard(text, self.sessions.get(chat_id)),
            )
            return

        if action == "new":
            dropped = self.state.reset_chat(chat_id)
            stopped = (
                await self.executor.stop(chat_id) if chat_id in self.busy else False
            )
            logger.info(
                "New session | chat_id=%s permission_mode=%s stopped=%s dropped=%s",
                chat_id,
                self._permission_mode_label(chat_id),
                stopped,
                dropped,
            )
            self._write_status()
            text = self._new_session_text(chat_id, stopped=stopped, dropped=dropped)
            await query.answer("已开始新会话")
            await context.bot.send_message(chat_id=chat_id, text=text)
            return

        prompt = self.result_actions.resolve(chat_id, token)
        if prompt is None:
            await query.answer("结果操作已过期")
            return

        async def reply_enqueue(text: str) -> None:
            await query.answer(text)
            await context.bot.send_message(chat_id=chat_id, text=text)

        if await self._try_enqueue(chat_id, query.from_user.id, prompt, reply_enqueue):
            return

        await query.answer("重新执行")
        await self._process_message(chat_id, query.from_user.id, prompt, context)

    async def handle_setting_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        if not self._is_authorized(query.from_user.id):
            return

        parsed = parse_setting_callback(query.data)
        if parsed is None:
            return
        kind, chat_id, value = parsed

        if not query.message or getattr(query.message, "chat_id", None) != chat_id:
            return

        if kind == "model":
            text = self._apply_model_choice(chat_id, value)
        elif kind == "effort":
            text = self._apply_effort_choice(chat_id, value)
        else:
            text = self._apply_permission_choice(chat_id, value)
        if text is None:
            await query.answer("选项已失效")
            return

        self._write_status()
        await query.edit_message_text(text, reply_markup=None)

    async def _attach_session_text(self, chat_id: int, session_id: str) -> str:
        self.state.attach_session(chat_id, session_id)
        stopped = await self.executor.stop(chat_id) if chat_id in self.busy else False
        self._write_status()
        if stopped:
            return (
                f"🔗 已接管 session {session_id[:8]}...，当前任务已停止，队列已清空。"
            )
        return f"🔗 已接管 session {session_id[:8]}...，下一条消息会继续该会话。"

    def _apply_model_choice(self, chat_id: int, value: str) -> str | None:
        value = value.strip()
        if value.lower() == "reset":
            self.model_overrides.pop(chat_id, None)
            return f"模型已重置为: {self._model_label(chat_id)}"
        try:
            model = normalize_model(value)
        except ValueError:
            return None
        if model is None:
            self.model_overrides.pop(chat_id, None)
            return f"模型已重置为: {self._model_label(chat_id)}"
        self.model_overrides[chat_id] = model
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        return f"模型已设置为 {model}，{suffix}"

    def _apply_permission_choice(self, chat_id: int, value: str) -> str | None:
        value = value.strip()
        if value.lower() == "reset":
            self.permission_modes.pop(chat_id, None)
            return f"权限模式已重置为: {self._permission_mode_label(chat_id)}"
        try:
            mode = normalize_permission_mode(value)
        except ValueError:
            return None
        if mode is None:
            self.permission_modes.pop(chat_id, None)
            return f"权限模式已重置为: {self._permission_mode_label(chat_id)}"
        self.permission_modes[chat_id] = mode
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        return f"权限模式已设置为 {mode}，{suffix}"

    def _apply_effort_choice(self, chat_id: int, value: str) -> str | None:
        value = value.strip()
        if value.lower() == "reset":
            self.effort_overrides.pop(chat_id, None)
            return f"思考强度已重置为: {self._effort_label(chat_id)}"
        try:
            effort = normalize_effort(value)
        except ValueError:
            return None
        if effort is None:
            self.effort_overrides.pop(chat_id, None)
            return f"思考强度已重置为: {self._effort_label(chat_id)}"
        self.effort_overrides[chat_id] = effort
        suffix = (
            "当前任务不受影响，下一条消息生效。"
            if chat_id in self.busy
            else "下一条消息生效。"
        )
        return f"思考强度已设置为 {effort}，{suffix}"

    def _new_session_text(
        self, chat_id: int, *, stopped: bool, dropped: int = 0
    ) -> str:
        parts = ["🆕 已开始新会话。"]
        if stopped:
            parts.append("当前任务已停止。")
        if dropped:
            parts.append(f"已丢弃 {dropped} 条排队消息。")
        return (
            f"{' '.join(parts)}\n"
            f"权限模式、模型和思考强度已重置为默认。\n"
            f"当前权限模式: {self._permission_mode_label(chat_id)}\n"
            f"当前模型: {self._model_label(chat_id)}\n"
            f"当前思考强度: {self._effort_label(chat_id)}"
        )

    async def _send_force_reply_prompt(
        self,
        message: Message,
        chat_id: int,
        user_id: int,
        intent: PendingReplyIntent,
        text: str,
        *,
        placeholder: str,
    ) -> None:
        sent = await message.reply_text(
            text,
            reply_markup=ForceReply(
                selective=True,
                input_field_placeholder=placeholder,
            ),
        )
        message_id = getattr(sent, "message_id", None)
        if isinstance(message_id, int):
            self.pending_replies.create(chat_id, message_id, user_id, intent)

    async def handle_forced_reply(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        resolved = _message_context(update)
        if resolved is None:
            return
        user_id, chat_id, message = resolved
        if not self._is_authorized(user_id):
            return
        reply_to = message.reply_to_message
        message_id = getattr(reply_to, "message_id", None)
        if not isinstance(message_id, int):
            return
        if not _is_reply_to_this_bot(reply_to, context):
            return
        pending = self.pending_replies.get(chat_id, message_id)
        if pending is None:
            if _is_force_reply_message(reply_to):
                await message.reply_text("回复入口已过期，请重新发送对应命令。")
                raise ApplicationHandlerStop
            return
        if pending.user_id != user_id:
            await message.reply_text("这个回复入口只对发起命令的用户有效。")
            raise ApplicationHandlerStop
        self.pending_replies.pop(chat_id, message_id)

        text = (message.text or message.caption or "").strip()
        if not text:
            await message.reply_text("未收到文本，请重新发送对应命令。")
            raise ApplicationHandlerStop

        if pending.intent == "run":
            prompt = _normalize_forced_run_command(text)
            if await self._try_enqueue(chat_id, user_id, prompt, message.reply_text):
                raise ApplicationHandlerStop
            await self._process_message(chat_id, user_id, prompt, context)
            raise ApplicationHandlerStop

        if pending.intent == "resume":
            await self._attach_session_id(chat_id, message, text)
            raise ApplicationHandlerStop

        if pending.intent == "model":
            result = self._apply_model_choice(chat_id, text)
        elif pending.intent == "effort":
            result = self._apply_effort_choice(chat_id, text)
        else:
            result = self._apply_permission_choice(chat_id, text)
        if result is None:
            await message.reply_text("无效选项，请重新发送对应命令。")
        else:
            self._write_status()
            await message.reply_text(result)
        raise ApplicationHandlerStop


def _format_mib_limit(byte_count: int) -> str:
    mib = byte_count / BYTES_PER_MIB
    if mib.is_integer():
        return f"{int(mib)} MB"
    return f"{mib:.1f} MB"


def _runtime_status_text(runtime_status: ClaudeRuntimeStatus | None) -> str:
    if runtime_status is None:
        return "Claude CLI 回传: 暂无"
    lines = ["Claude CLI 回传:"]
    if runtime_status.claude_code_version:
        lines.append(f"claude_code_version: {runtime_status.claude_code_version}")
    if runtime_status.cwd:
        lines.append(f"cwd: {runtime_status.cwd}")
    if runtime_status.model:
        lines.append(f"model: {runtime_status.model}")
    if runtime_status.permission_mode:
        lines.append(f"permissionMode: {runtime_status.permission_mode}")
    if runtime_status.mcp_servers:
        lines.append(f"mcp_servers: {_format_mcp_servers(runtime_status.mcp_servers)}")
    if runtime_status.context_window is not None:
        lines.append(f"contextWindow: {runtime_status.context_window}")
    if runtime_status.max_output_tokens is not None:
        lines.append(f"maxOutputTokens: {runtime_status.max_output_tokens}")
    if runtime_status.speed:
        lines.append(f"speed: {runtime_status.speed}")
    return "\n".join(lines)


def _format_mcp_servers(servers: tuple[tuple[str, str], ...]) -> str:
    summary = ", ".join(f"{name}={status}" for name, status in servers)
    if len(summary) <= 600:
        return summary
    return summary[:597].rstrip() + "..."


def _parse_resume_history_args(args: Sequence[str]) -> tuple[str | None, bool]:
    show_all = any(arg in RESUME_ALL_ARGS for arg in args)
    query_parts = [arg for arg in args if arg not in RESUME_ALL_ARGS]
    query = " ".join(query_parts).strip()
    return query or None, show_all


def _filter_resume_sessions(
    sessions: Sequence[ClaudeSessionInfo], query: str | None
) -> list[ClaudeSessionInfo]:
    if not query:
        return list(sessions)
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return list(sessions)
    return [
        item
        for item in sessions
        if all(term in _resume_search_text(item) for term in terms)
    ]


def _resume_search_text(item: ClaudeSessionInfo) -> str:
    return "\n".join(
        part.casefold()
        for part in (
            item.session_id,
            item.title,
            item.cwd,
            item.git_branch,
            str(item.path),
        )
        if part
    )


def _format_resume_session(
    item: ClaudeSessionInfo,
    *,
    index: int,
    current_session: str | None,
    compact: bool,
) -> str:
    updated = _format_resume_mtime(item.updated_at, compact=compact)
    branch = f" · {item.git_branch}" if item.git_branch else ""
    size = f" · {_format_session_size(item.size_bytes)}" if item.size_bytes else ""
    suffix = " · 当前 chat" if item.session_id == current_session else ""
    title = _short_resume_title(item.title)
    metadata_id = item.session_id[:8] if compact else item.session_id
    if compact:
        return f"{index}. {title}{suffix}\n   {metadata_id} · {updated}{branch}{size}"
    return f"{index}. {title}{suffix}\n   {metadata_id}\n   {updated}{branch}{size}"


def _short_resume_title(title: str | None) -> str:
    value = " ".join((title or "（无标题）").split())
    if not value:
        value = "（无标题）"
    if len(value) <= RESUME_BODY_TITLE_LIMIT:
        return value
    return value[: RESUME_BODY_TITLE_LIMIT - 3].rstrip() + "..."


def _format_resume_mtime(timestamp: float, *, compact: bool) -> str:
    from datetime import datetime

    pattern = "%m-%d %H:%M" if compact else "%Y-%m-%d %H:%M"
    return datetime.fromtimestamp(timestamp).strftime(pattern)


def _format_session_mtime(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _format_session_size(byte_count: int) -> str:
    if byte_count < 1024:
        return f"{byte_count}B"
    kib = byte_count / 1024
    if kib < 1024:
        return f"{kib:.1f}KB"
    mib = kib / 1024
    return f"{mib:.1f}MB"
