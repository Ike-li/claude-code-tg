"""Telegram Bot handlers."""

import asyncio
import logging
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from telegram import Update
from telegram.ext import Application, ContextTypes

from claude_code_tg.attachments import (
    DEFAULT_ATTACHMENT_MAX_BYTES,
    DEFAULT_ATTACHMENT_MODE,
    PROJECT_ATTACHMENT_DIRNAME,
    prune_attachment_tree,
)
from claude_code_tg.bot_app import build_telegram_app
from claude_code_tg.bot_commands import BotCommandHandlers
from claude_code_tg.bot_processing import BotMessageProcessor
from claude_code_tg.command_view import CommandPickerStore
from claude_code_tg.container import ServiceContainer
from claude_code_tg.executor import (
    Executor,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.message_input import TelegramInputBuilder
from claude_code_tg.message_output import MAX_TG_MESSAGE_LENGTH
from claude_code_tg.pending_reply import PendingReplyStore
from claude_code_tg.result_view import ResultActionStore
from claude_code_tg.resume_view import ResumePickerStore
from claude_code_tg.run_view import RunViewStore
from claude_code_tg.services import AttachmentService
from claude_code_tg.sessions import ChatSessionStore, ReplyCallback
from claude_code_tg.utils import _format_uptime

logger = logging.getLogger(__name__)

__all__ = ["MAX_TG_MESSAGE_LENGTH", "TGBot"]

HEARTBEAT_LOG_INTERVAL = 10


class TGBot(BotMessageProcessor, BotCommandHandlers):
    def __init__(
        self,
        token: str,
        admin_ids: set[int],
        allowed_ids: set[int],
        project_dir: str | None = None,
        container: ServiceContainer | None = None,
        allowed_chat_ids: set[int] | None = None,
        timeout: int = 300,
        queue_max_size: int = 3,
        permission_mode: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        attachment_dir: Path | None = None,
        attachment_max_bytes: int = DEFAULT_ATTACHMENT_MAX_BYTES,
        attachment_mode: str = DEFAULT_ATTACHMENT_MODE,
        attachment_retention_days: float | None = None,
        command_menu_enabled: bool = False,
        draft_preview_enabled: bool = False,
        mini_app_enabled: bool = False,
        mini_app_public_url: str = "",
        mini_app_host: str = "127.0.0.1",
        mini_app_port: int = 8787,
        mini_app_menu_text: str = "tgcc",
        cli_resume_compat: bool = False,
        status_file: Path | None = None,
    ) -> None:
        # 依赖注入：如果没有传入容器，使用传统参数创建
        if container is None:
            if project_dir is None:
                raise ValueError("project_dir is required when container is not provided")
            container = ServiceContainer.create_default(
                project_dir=project_dir,
                timeout=timeout,
                queue_max_size=queue_max_size,
                permission_mode=permission_mode,
                model=model,
                effort=effort,
                status_file=status_file,
                cli_resume_compat=cli_resume_compat,
                draft_preview_enabled=draft_preview_enabled,
            )

        # 从容器获取核心服务
        self.container = container
        self.executor = container.executor
        self.state = container.session_store
        self.project_dir = container.project_dir
        self.timeout = container.timeout
        self.cli_resume_compat_enabled = container.cli_resume_compat
        self.draft_preview_enabled = container.draft_preview_enabled

        # 保留向后兼容：如果传入了 project_dir 参数，覆盖容器中的值
        if project_dir is not None:
            self.project_dir = project_dir

        # Bot 特定配置
        self.token = token
        self.admin_ids = admin_ids
        self.allowed_ids = allowed_ids | admin_ids
        self.allowed_chat_ids = allowed_chat_ids or set()
        # Bot 特定配置
        self.token = token
        self.admin_ids = admin_ids
        self.allowed_ids = allowed_ids | admin_ids
        self.allowed_chat_ids = allowed_chat_ids or set()

        # 附件处理配置
        default_attachment_dir = (
            status_file.parent / "attachments"
            if status_file
            else Path.home() / ".tgcc" / "attachments"
        )
        self.input_builder = TelegramInputBuilder(
            attachment_dir=attachment_dir or default_attachment_dir,
            project_dir=self.project_dir,
            attachment_max_bytes=attachment_max_bytes,
            attachment_mode=attachment_mode,
        )
        self.attachment_dir = self.input_builder.attachment_dir
        self.attachment_max_bytes = self.input_builder.attachment_max_bytes
        self.attachment_mode = self.input_builder.attachment_mode
        self.attachment_retention_days = attachment_retention_days

        # 附件服务
        self.attachment_service = AttachmentService(
            attachment_dir=self.attachment_dir,
            project_dir=self.project_dir,
            retention_days=attachment_retention_days,
        )

        # 功能开关
        self.command_menu_enabled = command_menu_enabled
        self.mini_app_enabled = mini_app_enabled
        self.mini_app_public_url = mini_app_public_url
        self.mini_app_host = mini_app_host
        self.mini_app_port = mini_app_port
        self.mini_app_menu_text = mini_app_menu_text
        self._mini_app_server: object | None = None
        self._mini_app_task: asyncio.Task[Any] | None = None

        # 状态和缓存
        self.command_menu_cache_file = (
            status_file.parent / "command-menu.json" if status_file else None
        )
        self.run_views = RunViewStore()
        self.resume_pickers = ResumePickerStore()
        self.command_pickers = CommandPickerStore()
        self.result_actions = ResultActionStore()
        self.pending_replies = PendingReplyStore()
        self.last_prompts: dict[int, str] = {}

        # tg-safe command name -> Claude slash command; filled in post_init.
        self.claude_command_map: dict[str, str] = {}

        # 向后兼容的属性别名（指向 state 中的数据）
        self.queue_max_size = self.state.queue_max_size
        self.default_permission_mode = self.state.default_permission_mode
        self.default_model = self.state.default_model
        self.default_effort = self.state.default_effort
        self.sessions = self.state.sessions
        self.permission_modes = self.state.permission_modes
        self.model_overrides = self.state.model_overrides
        self.effort_overrides = self.state.effort_overrides
        self._session_versions = self.state.session_versions
        self.busy = self.state.busy
        self.queues = self.state.queues

    @property
    def queue_max_size(self) -> int:
        return self.state.queue_max_size

    @queue_max_size.setter
    def queue_max_size(self, value: int) -> None:
        self.state.queue_max_size = max(value, 1)

    @property
    def default_permission_mode(self) -> str | None:
        return self.state.default_permission_mode

    @default_permission_mode.setter
    def default_permission_mode(self, value: str | None) -> None:
        self.state.default_permission_mode = normalize_permission_mode(value)

    @property
    def default_model(self) -> str | None:
        return self.state.default_model

    @default_model.setter
    def default_model(self, value: str | None) -> None:
        self.state.default_model = normalize_model(value)

    @property
    def default_effort(self) -> str | None:
        return self.state.default_effort

    @default_effort.setter
    def default_effort(self, value: str | None) -> None:
        self.state.default_effort = normalize_effort(value)

    @property
    def status_file(self) -> Path | None:
        return self.state.status_file

    @status_file.setter
    def status_file(self, value: Path | None) -> None:
        self.state.status_file = value

    @property
    def _start_time(self) -> float:
        return self.state.start_time

    @_start_time.setter
    def _start_time(self, value: float) -> None:
        self.state.start_time = value

    @property
    def _heartbeat_counter(self) -> int:
        return self.state.heartbeat_counter

    @_heartbeat_counter.setter
    def _heartbeat_counter(self, value: int) -> None:
        self.state.heartbeat_counter = value

    def _is_authorized(self, user_id: int) -> bool:
        return user_id in self.allowed_ids

    def _is_chat_allowed(self, chat_id: int, chat_type: str | None) -> bool:
        """Whether the bot may operate in this chat.

        Private chats are governed solely by per-user authorization (the chat
        belongs to the user). Group/supergroup/channel chats are default-deny:
        the chat id must be explicitly listed in ``allowed_chat_ids``, because
        bot output is visible to every member, not just the authorized sender.
        """
        if chat_type == "private":
            return True
        return chat_id in self.allowed_chat_ids

    def _write_status(self) -> None:
        """Write current bot status to JSON file for `tgcc status` consumption."""
        error = self.state.write_status()
        if error:
            logger.debug("Failed to write status file: %s", error)

    def _restore_sessions(self) -> None:
        """Restore sessions from status.json after restart."""
        restored = self.state.restore_sessions()
        if restored:
            logger.info(f"Restored {restored} session(s) from status file")

    def _record_periodic_status(self) -> None:
        """Write status and periodically emit a lightweight heartbeat log."""
        self._write_status()
        self._heartbeat_counter += 1
        if self._heartbeat_counter < HEARTBEAT_LOG_INTERVAL:
            return
        self._heartbeat_counter = 0
        queue_total = self.state.queue_total()
        uptime = int(time.time() - self._start_time)
        logger.info(
            "Heartbeat | sessions=%d busy=%d queue=%d uptime=%s",
            len(self.sessions),
            len(self.busy),
            queue_total,
            _format_uptime(uptime),
        )

    def _attachment_cleanup_roots(self) -> list[tuple[str, Path]]:
        """返回需要清理的根目录列表（委托给 AttachmentService）。"""
        return self.attachment_service.cleanup_roots()

    def _run_attachment_retention_cleanup(self) -> tuple[int, int, int]:
        """执行保留期清理（委托给 AttachmentService）。"""
        return self.attachment_service.run_retention_cleanup()

    def _get_or_create_session(self, chat_id: int) -> tuple[str | None, bool]:
        """Returns (session_id, is_existing). None means new session."""
        return self.state.get_or_create_session(chat_id)

    def _effective_permission_mode(self, chat_id: int) -> str | None:
        return self.state.effective_permission_mode(chat_id)

    def _permission_mode_label(self, chat_id: int) -> str:
        return self.state.permission_mode_label(chat_id)

    def _effective_model(self, chat_id: int) -> str | None:
        return self.state.effective_model(chat_id)

    def _model_label(self, chat_id: int) -> str:
        return self.state.model_label(chat_id)

    def _effective_effort(self, chat_id: int) -> str | None:
        return self.state.effective_effort(chat_id)

    def _effort_label(self, chat_id: int) -> str:
        return self.state.effort_label(chat_id)

    def _normalize_and_validate_session_id(
        self, session_id: str, chat_id: int
    ) -> str | None:
        """Return a canonical Claude session UUID with ownership validation.

        Returns None if the UUID is invalid or belongs to another chat.
        """
        return self.state.normalize_and_validate_session_id(session_id, chat_id)

    @staticmethod
    def _normalize_session_id(session_id: str) -> str | None:
        """Return a canonical Claude session UUID, or None if invalid.

        DEPRECATED: Use _normalize_and_validate_session_id for security.
        This method only validates format, not ownership.
        """
        try:
            return str(uuid.UUID(session_id.strip()))
        except (AttributeError, ValueError):
            return None

    async def _try_enqueue(
        self,
        chat_id: int,
        user_id: int,
        prompt: str,
        reply_fn: ReplyCallback,
    ) -> bool:
        """Try to enqueue a message. Returns True if enqueued, False if should process immediately."""
        result = await self.state.try_enqueue(chat_id, user_id, prompt, reply_fn)
        self._write_status()
        return result

    async def _prompt_from_update(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> str:
        return await self.input_builder.prompt_from_update(update, context)

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.message or not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        chat = update.effective_chat
        chat_id = chat.id

        if not self._is_authorized(user_id):
            return

        if not self._is_chat_allowed(chat_id, chat.type):
            return

        # Group chat: only respond to @bot or reply-to-bot
        if chat.type != "private":
            bot_username = context.bot.username
            msg = update.message
            msg_text = msg.text or msg.caption or ""
            is_mention = bot_username and f"@{bot_username}" in msg_text
            is_reply_to_bot = (
                msg.reply_to_message
                and msg.reply_to_message.from_user
                and msg.reply_to_message.from_user.id == context.bot.id
            )
            if not is_mention and not is_reply_to_bot:
                return

        try:
            prompt = await self._prompt_from_update(update, context)
        except ValueError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return
        except Exception:
            logger.exception("Failed to download Telegram attachment")
            await update.message.reply_text("❌ 附件下载失败，请稍后重试。")
            return

        if not prompt:
            return

        if await self._try_enqueue(chat_id, user_id, prompt, update.message.reply_text):
            return

        await self._process_message(chat_id, user_id, prompt, context)

    def build_app(self) -> Application:
        return build_telegram_app(self)

    async def start_mini_app(self, telegram_bot: Any) -> None:
        """Start the optional Mini App web console alongside polling."""
        if not self.mini_app_enabled:
            return
        try:
            import uvicorn

            from claude_code_tg.web_console import build_web_console_app
        except ImportError as exc:
            raise RuntimeError(
                "Mini App support requires `uvicorn` and `starlette`; "
                "install with `uv sync --extra mini-app`."
            ) from exc

        app = build_web_console_app(self, telegram_bot)
        config = uvicorn.Config(
            cast(Any, app),
            host=self.mini_app_host,
            port=self.mini_app_port,
            log_level="info",
            lifespan="off",
        )
        server = uvicorn.Server(config)
        self._mini_app_server = server
        self._mini_app_task = asyncio.create_task(server.serve())

    async def stop_mini_app(self) -> None:
        task = self._mini_app_task
        server = self._mini_app_server
        if server is not None and hasattr(server, "should_exit"):
            cast(Any, server).should_exit = True
        if task is not None:
            from contextlib import suppress

            with suppress(asyncio.CancelledError):
                await task
        self._mini_app_task = None
        self._mini_app_server = None

    def mini_app_status(self, chat_id: int) -> dict[str, object]:
        queue_len = len(self.queues.get(chat_id, []))
        session_id = self.sessions.get(chat_id)
        latest = self.run_views.latest(chat_id)
        current_tool = latest.current_tool if latest else None
        return {
            "chat_id": chat_id,
            "busy": chat_id in self.busy,
            "session_id": session_id,
            "queue": {"current": queue_len, "max": self.queue_max_size},
            "permission_mode": self._permission_mode_label(chat_id),
            "model": self._model_label(chat_id),
            "effort": self._effort_label(chat_id),
            "attachment": self._attachment_config_label(),
            "last_prompt_available": chat_id in self.last_prompts,
            "latest_run": None
            if latest is None
            else {
                "run_id": latest.run_id,
                "status": latest.status,
                "task": latest.task_summary,
                "tool_count": latest.tool_count,
                "current_tool": None
                if current_tool is None
                else {
                    "index": current_tool.index,
                    "name": current_tool.name,
                    "summary": current_tool.summary,
                    "output": current_tool.output,
                    "is_error": current_tool.is_error,
                },
                "latest_output": latest.latest_output,
            },
        }

    async def handle_mini_app_action(
        self,
        chat_id: int,
        user_id: int,
        action: str,
        payload: dict[str, object],
        telegram_bot: Any,
    ) -> dict[str, object]:
        if not self._is_authorized(user_id):
            return {"ok": False, "error": "unauthorized"}
        if action == "stop":
            return {"ok": True, "stopped": await self.executor.stop(chat_id)}
        if action == "new":
            dropped = self.state.reset_chat(chat_id)
            stopped = (
                await self.executor.stop(chat_id) if chat_id in self.busy else False
            )
            self._write_status()
            return {"ok": True, "stopped": stopped, "dropped": dropped}
        if action == "resume":
            session_id = self._normalize_and_validate_session_id(
                str(payload.get("session_id", "")), chat_id
            )
            if not session_id:
                return {"ok": False, "error": "invalid_session_id_or_unauthorized"}
            message_text = await self._attach_session_text(chat_id, session_id)
            return {"ok": True, "message": message_text}
        if action == "set_model":
            model_text = self._apply_model_choice(
                chat_id, str(payload.get("model", ""))
            )
            if model_text is None:
                return {"ok": False, "error": "invalid_model"}
            self._write_status()
            return {"ok": True, "message": model_text}
        if action == "set_permissions":
            permission_text = self._apply_permission_choice(
                chat_id, str(payload.get("mode", ""))
            )
            if permission_text is None:
                return {"ok": False, "error": "invalid_permission_mode"}
            self._write_status()
            return {"ok": True, "message": permission_text}
        if action == "set_effort":
            effort_text = self._apply_effort_choice(
                chat_id, str(payload.get("effort", ""))
            )
            if effort_text is None:
                return {"ok": False, "error": "invalid_effort"}
            self._write_status()
            return {"ok": True, "message": effort_text}
        if action == "rerun":
            prompt = self.last_prompts.get(chat_id)
            if not prompt:
                return {"ok": False, "error": "no_last_prompt"}

            async def reply_enqueue(text: str) -> None:
                await telegram_bot.send_message(chat_id=chat_id, text=text)

            if await self._try_enqueue(chat_id, user_id, prompt, reply_enqueue):
                return {"ok": True, "queued": True}
            context = cast(ContextTypes.DEFAULT_TYPE, SimpleNamespace(bot=telegram_bot))
            await self._process_message(chat_id, user_id, prompt, context)
            return {"ok": True, "queued": False}
        return {"ok": False, "error": "unknown_action"}

    def run(self) -> None:
        app = self.build_app()
        app.run_polling(drop_pending_updates=True)
