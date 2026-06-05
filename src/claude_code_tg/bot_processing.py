"""Message execution and queue draining for TGBot."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import cast

from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from claude_code_tg.executor import Executor, RunEvent, build_cli_setting_args
from claude_code_tg.interaction_log import tg_in, tg_out
from claude_code_tg.message_output import send_pages
from claude_code_tg.result_view import ResultActionStore, build_result_keyboard
from claude_code_tg.run_view import (
    RunView,
    RunViewStore,
    apply_run_event,
    render_run_view,
)
from claude_code_tg.sessions import CLI_DEFAULT_LABEL, ChatSessionStore
from claude_code_tg.telegram_ui import HTML_PARSE_MODE

logger = logging.getLogger(__name__)

# Sentinel: distinguishes "no snapshot, read the current effective value" from
# a snapshot whose value is legitimately None (Claude Code default).
_USE_EFFECTIVE: object = object()

CHAT_ACTION_INTERVAL_SECONDS = 4.0
STATUS_CARD_HEARTBEAT_SECONDS = 15.0
DRAFT_PREVIEW_INTERVAL_SECONDS = 1.0
DRAFT_PREVIEW_TEXT_LIMIT = 4096


def project_branch_label(project_dir: str) -> str:
    try:
        branch = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return "非 git"
    if branch.returncode != 0:
        return "非 git"
    label = branch.stdout.strip()
    if not label:
        return "非 git"
    if label != "HEAD":
        return label

    try:
        commit = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return "detached"
    short_sha = commit.stdout.strip()
    return (
        f"detached:{short_sha}" if commit.returncode == 0 and short_sha else "detached"
    )


def _reply_markup_fingerprint(reply_markup: object) -> str:
    if reply_markup is None:
        return ""
    to_dict = getattr(reply_markup, "to_dict", None)
    if callable(to_dict):
        try:
            return json.dumps(to_dict(), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            pass
    return repr(reply_markup)


class BotMessageProcessor:
    busy: set[int]
    executor: Executor
    project_dir: str
    cli_resume_compat_enabled: bool
    draft_preview_enabled: bool
    last_prompts: dict[int, str]
    result_actions: ResultActionStore
    run_views: RunViewStore
    state: ChatSessionStore
    timeout: int

    def _get_or_create_session(self, chat_id: int) -> tuple[str | None, bool]:
        raise NotImplementedError

    def _effective_permission_mode(self, chat_id: int) -> str | None:
        raise NotImplementedError

    def _effective_model(self, chat_id: int) -> str | None:
        raise NotImplementedError

    def _effective_effort(self, chat_id: int) -> str | None:
        raise NotImplementedError

    def _write_status(self) -> None:
        raise NotImplementedError

    async def _process_message(
        self,
        chat_id: int,
        user_id: int,
        prompt: str,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        permission_mode: str | None | object = _USE_EFFECTIVE,
        model: str | None | object = _USE_EFFECTIVE,
        effort: str | None | object = _USE_EFFECTIVE,
    ) -> None:
        tg_in(chat_id, prompt)
        self.last_prompts[chat_id] = prompt
        self.busy.add(chat_id)
        session_id, is_existing = self._get_or_create_session(chat_id)
        session_version = self.state.session_version(chat_id)
        # Queued messages carry a snapshot taken at enqueue time; a fresh
        # message reads the current effective value.
        if permission_mode is _USE_EFFECTIVE:
            permission_mode = self._effective_permission_mode(chat_id)
        if model is _USE_EFFECTIVE:
            model = self._effective_model(chat_id)
        if effort is _USE_EFFECTIVE:
            effort = self._effective_effort(chat_id)
        permission_mode = cast("str | None", permission_mode)
        model = cast("str | None", model)
        effort = cast("str | None", effort)
        permission_mode_label = permission_mode or CLI_DEFAULT_LABEL
        effort_label = effort or CLI_DEFAULT_LABEL
        logger.info(
            "Run start | chat_id=%s existing_session=%s permission_mode=%s model=%s effort=%s prompt_chars=%d",
            chat_id,
            is_existing,
            permission_mode_label,
            model or CLI_DEFAULT_LABEL,
            effort_label,
            len(prompt),
        )
        run_view = self.run_views.create(
            chat_id,
            prompt=prompt,
            session_id=session_id or "",
            is_existing_session=is_existing,
            git_branch=project_branch_label(self.project_dir),
            permission_mode=permission_mode_label,
            model=model or CLI_DEFAULT_LABEL,
            effort=effort_label,
            cli_args=build_cli_setting_args(
                permission_mode=permission_mode,
                model=model,
                effort=effort,
            ),
        )
        initial_text, initial_kb = render_run_view(run_view)
        try:
            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=initial_text,
                reply_markup=initial_kb,
                parse_mode=HTML_PARSE_MODE,
            )
        except Exception:
            self.busy.discard(chat_id)
            self._write_status()
            logger.exception("Failed to send run status card")
            raise
        await self._send_draft_preview(chat_id, run_view, context, "")

        last_update = 0.0
        last_draft_update = 0.0
        last_status_text = initial_text
        last_status_keyboard = _reply_markup_fingerprint(initial_kb)
        status_update_lock = asyncio.Lock()

        async def update_status(*, force: bool = False) -> None:
            nonlocal last_status_keyboard, last_status_text, last_update
            async with status_update_lock:
                now = time.monotonic()
                if not force and now - last_update < 2.0:
                    return
                text, keyboard = render_run_view(run_view)
                keyboard_fingerprint = _reply_markup_fingerprint(keyboard)
                if (
                    text == last_status_text
                    and keyboard_fingerprint == last_status_keyboard
                ):
                    return
                last_update = now
                try:
                    await status_msg.edit_text(
                        text,
                        reply_markup=keyboard,
                        parse_mode=HTML_PARSE_MODE,
                    )
                except TelegramError as exc:
                    logger.debug("editMessageText status update failed: %s", exc)
                else:
                    last_status_text = text
                    last_status_keyboard = keyboard_fingerprint

        async def refresh_status_card() -> None:
            await update_status(force=True)

        async def on_event(event: RunEvent) -> None:
            nonlocal last_draft_update
            self.state.record_runtime_event(chat_id, event)
            apply_run_event(run_view, event)
            await update_status()
            if event.kind != "assistant_text":
                return
            now = time.monotonic()
            if now - last_draft_update < DRAFT_PREVIEW_INTERVAL_SECONDS:
                return
            last_draft_update = now
            await self._send_draft_preview(chat_id, run_view, context, event.text)

        await self._send_chat_action_once(chat_id, context)
        chat_action_task = asyncio.create_task(
            self._chat_action_heartbeat(chat_id, context)
        )
        status_heartbeat_task = asyncio.create_task(
            self._status_card_heartbeat(refresh_status_card)
        )

        try:
            result = await self.executor.run(
                prompt=prompt,
                chat_id=chat_id,
                session_id=session_id if is_existing else None,
                project_dir=self.project_dir,
                timeout=self.timeout,
                permission_mode=permission_mode,
                model=model,
                effort=effort,
                cli_resume_compat=self.cli_resume_compat_enabled,
                on_event=on_event,
            )

            if result.session_id:
                run_view.session_id = result.session_id
                self.state.set_session_if_current(
                    chat_id, result.session_id, session_version
                )

            if result.was_stopped:
                run_view.status = "stopped"
                run_view.finished_at = run_view.finished_at or time.monotonic()
                await update_status(force=True)
                return

            run_view.status = "failed" if result.is_error else "completed"
            run_view.finished_at = run_view.finished_at or time.monotonic()

            await update_status(force=True)

            session_prefix = ""
            if result.session_id:
                session_prefix = f"📎 Session: {result.session_id[:8]}...\n"

            summary = ""
            if result.tool_count > 0:
                summary = (
                    f"🔧 {result.tool_count} 工具 | "
                    f"⏱ {result.duration_ms / 1000:.1f}s\n\n"
                )
            output_text = result.text
            if result.is_error and not output_text.startswith("❌"):
                output_text = f"❌ {output_text}"

            final_text = session_prefix + summary + output_text
            result_keyboard = build_result_keyboard(
                chat_id,
                prompt,
                final_text,
                self.result_actions,
            )
            await send_pages(
                chat_id,
                final_text,
                context,
                reply_markup=result_keyboard,
            )
            tg_out(chat_id, output_text)

        except Exception as e:
            logger.exception("Error processing message")
            err_text = f"❌ 执行出错: {type(e).__name__}: {e}"
            run_view.status = "failed"
            run_view.current_text = err_text
            run_view.finished_at = run_view.finished_at or time.monotonic()
            await update_status(force=True)
        finally:
            chat_action_task.cancel()
            status_heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await chat_action_task
            with suppress(asyncio.CancelledError):
                await status_heartbeat_task
            queued = self.state.popleft_queue(chat_id)
            if queued is None:
                self.busy.discard(chat_id)
                self._write_status()
            else:
                self._write_status()
                try:
                    await self._process_message(
                        chat_id,
                        queued.user_id,
                        queued.prompt,
                        context,
                        permission_mode=queued.permission_mode,
                        model=queued.model,
                        effort=queued.effort,
                    )
                except Exception:
                    logger.exception("drain_queue: _process_message failed, continuing")
                    await self._drain_queue(chat_id, context)

    async def _drain_queue(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        while True:
            queued = self.state.popleft_queue(chat_id)
            if queued is None:
                self.busy.discard(chat_id)
                self._write_status()
                return
            try:
                await self._process_message(
                    chat_id,
                    queued.user_id,
                    queued.prompt,
                    context,
                    permission_mode=queued.permission_mode,
                    model=queued.model,
                    effort=queued.effort,
                )
            except Exception:
                logger.exception("drain_queue: _process_message failed, continuing")

    async def _send_chat_action_once(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except (AttributeError, TelegramError) as exc:
            logger.debug("sendChatAction failed: %s", exc)

    async def _chat_action_heartbeat(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        while True:
            await asyncio.sleep(CHAT_ACTION_INTERVAL_SECONDS)
            await self._send_chat_action_once(chat_id, context)

    async def _status_card_heartbeat(
        self, refresh_status_card: Callable[[], Awaitable[None]]
    ) -> None:
        while True:
            await asyncio.sleep(STATUS_CARD_HEARTBEAT_SECONDS)
            await refresh_status_card()

    async def _send_draft_preview(
        self,
        chat_id: int,
        run_view: RunView,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ) -> None:
        if not self.draft_preview_enabled or chat_id <= 0:
            return
        try:
            await context.bot.send_message_draft(
                chat_id=chat_id,
                draft_id=run_view.draft_id,
                text=text[:DRAFT_PREVIEW_TEXT_LIMIT],
            )
        except (AttributeError, TelegramError) as exc:
            logger.debug("sendMessageDraft failed: %s", exc)
