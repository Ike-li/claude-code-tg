"""Telegram message-to-Claude prompt helpers."""

from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from claude_code_tg.attachments import (
    DEFAULT_ATTACHMENT_PROMPT,
    AttachmentInfo,
    copy_attachment_to_project,
    normalize_attachment_mode,
    unique_attachment_path,
)
from claude_code_tg.file_security import write_owner_only_bytes
from claude_code_tg.sanitizer import strip_control_sequences


def format_attachment_prompt(prompt: str, attachment: AttachmentInfo) -> str:
    user_text = prompt.strip() or DEFAULT_ATTACHMENT_PROMPT
    size_text = f"\n- size: {attachment.size} bytes" if attachment.size else ""
    # original_name is attacker-controlled (any Telegram client). Strip control
    # sequences and keep it on a single line so it can't forge extra metadata
    # fields or inject terminal escapes into the prompt context.
    safe_name = strip_control_sequences(attachment.original_name).replace("\n", " ")
    return (
        f"{user_text}\n\n"
        "Telegram 附件已准备好，请在需要时读取这个本地文件：\n"
        f"- type: {attachment.kind}\n"
        f"- attachment_mode: {attachment.mode}\n"
        f"- original_name: {safe_name}{size_text}\n"
        f"- local_path: {attachment.path}"
    )


class TelegramInputBuilder:
    """Download Telegram attachments and build the final Claude prompt."""

    def __init__(
        self,
        *,
        attachment_dir: Path,
        project_dir: str,
        attachment_max_bytes: int,
        attachment_mode: str,
    ) -> None:
        self.attachment_dir = attachment_dir
        self.project_dir = project_dir
        self.attachment_max_bytes = max(1, attachment_max_bytes)
        self.attachment_mode = normalize_attachment_mode(attachment_mode)

    def attachment_path(self, chat_id: int, filename: str) -> Path:
        return unique_attachment_path(self.attachment_dir, chat_id, filename)

    async def download_attachment(
        self,
        chat_id: int,
        message: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> AttachmentInfo | None:
        kind = ""
        file_id = ""
        original_name = ""
        size = None

        if getattr(message, "photo", None):
            photo = message.photo[-1]
            kind = "photo"
            file_id = photo.file_id
            unique = getattr(photo, "file_unique_id", "") or file_id
            original_name = f"photo-{unique}.jpg"
            size = getattr(photo, "file_size", None)
        elif getattr(message, "document", None):
            document = message.document
            kind = "document"
            file_id = document.file_id
            unique = getattr(document, "file_unique_id", "") or file_id
            original_name = getattr(document, "file_name", None) or f"document-{unique}"
            size = getattr(document, "file_size", None)
        else:
            return None

        if self.attachment_mode == "reject":
            raise ValueError(
                "当前实例已禁用 Telegram 附件处理（ATTACHMENT_MODE=reject）。"
            )

        if size and size > self.attachment_max_bytes:
            max_mb = self.attachment_max_bytes / 1024 / 1024
            raise ValueError(f"附件过大（最大 {max_mb:.0f} MB）。")

        target = self.attachment_path(chat_id, original_name)
        telegram_file = await context.bot.get_file(file_id)
        buf = BytesIO()
        await telegram_file.download_to_memory(buf)
        content = buf.getvalue()
        if len(content) > self.attachment_max_bytes:
            max_mb = self.attachment_max_bytes / 1024 / 1024
            raise ValueError(f"附件过大（最大 {max_mb:.0f} MB）。")
        write_owner_only_bytes(target, content, exclusive=True)

        effective_path = target
        if self.attachment_mode == "copy-to-project":
            try:
                effective_path = copy_attachment_to_project(
                    target,
                    self.project_dir,
                    chat_id,
                )
            except OSError as exc:
                # The download itself succeeded; only the project-dir copy
                # failed. Remove the instance-cache file we just wrote so it
                # does not orphan on disk, and report what actually failed
                # instead of a misleading "download failed".
                with suppress(OSError):
                    target.unlink()
                raise ValueError(
                    f"附件已下载，但复制到项目目录失败：{exc}。"
                    "请检查 CLAUDE_PROJECT_DIR 是否存在且可写。"
                ) from exc

        return AttachmentInfo(
            kind=kind,
            path=effective_path,
            original_name=original_name,
            size=size,
            mode=self.attachment_mode,
        )

    async def prompt_from_update(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> str:
        message = update.message
        chat = update.effective_chat
        if message is None or chat is None:
            raise ValueError("Telegram update must include a message and chat.")
        prompt = (message.text or message.caption or "").strip()
        if context.bot.username:
            prompt = prompt.replace(f"@{context.bot.username}", "").strip()

        attachment = await self.download_attachment(chat.id, message, context)
        if attachment:
            return format_attachment_prompt(prompt, attachment)
        return prompt
