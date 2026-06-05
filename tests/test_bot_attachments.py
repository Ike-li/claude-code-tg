"""Tests for bot attachment handling and retention cleanup."""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_tg.executor import ExecutionResult
from tests.bot_helpers import FakeTelegramFile, make_bot, make_context, make_update


def test_attachment_retention_cleanup_prunes_instance_and_project(tmp_path):
    project_dir = tmp_path / "project"
    instance_dir = tmp_path / "instance-attachments"
    old_instance = instance_dir / "111" / "old-instance.txt"
    new_instance = instance_dir / "111" / "new-instance.txt"
    old_project = project_dir / ".tgcc-attachments" / "111" / "old-project.txt"
    for path in (old_instance, new_instance, old_project):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("attachment", encoding="utf-8")
    os.utime(old_instance, (100, 100))
    os.utime(old_project, (100, 100))

    bot = make_bot(
        project_dir=str(project_dir),
        attachment_dir=instance_dir,
        attachment_retention_days=1,
    )

    files, byte_count, errors = bot._run_attachment_retention_cleanup()

    assert files == 2
    assert byte_count == len("attachment") * 2
    assert errors == 0
    assert not old_instance.exists()
    assert not old_project.exists()
    assert new_instance.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink cleanup checks are POSIX-only")
def test_attachment_retention_cleanup_logs_symlink_root_warning(tmp_path, caplog):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    instance_dir = tmp_path / "attachments"
    try:
        instance_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    bot = make_bot(
        project_dir=str(project_dir),
        attachment_dir=instance_dir,
        attachment_retention_days=1,
    )

    with caplog.at_level(logging.WARNING):
        files, byte_count, errors = bot._run_attachment_retention_cleanup()

    assert files == 0
    assert byte_count == 0
    assert errors == 1
    assert outside_file.exists()
    assert "symlink root skipped" in caplog.text


def test_attachment_retention_cleanup_is_disabled_by_default(tmp_path):
    instance_dir = tmp_path / "attachments"
    target = instance_dir / "111" / "old.txt"
    target.parent.mkdir(parents=True)
    target.write_text("attachment", encoding="utf-8")
    os.utime(target, (100, 100))
    bot = make_bot(attachment_dir=instance_dir)

    assert bot._run_attachment_retention_cleanup() == (0, 0, 0)
    assert target.exists()


class TestHandleAttachmentMessages:
    @pytest.mark.asyncio
    async def test_document_message_downloads_and_passes_local_path(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path)
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "notes.txt"
        document.file_size = 12
        update = make_update(text=None, caption="summarize", document=document)
        context = make_context()
        telegram_file = FakeTelegramFile()
        context.bot.get_file = AsyncMock(return_value=telegram_file)

        captured_prompt = []
        result = ExecutionResult(text="ok", session_id="s1")

        async def capture_run(**kwargs):
            captured_prompt.append(kwargs["prompt"])
            return result

        with patch.object(bot.executor, "run", side_effect=capture_run):
            await bot.handle_message(update, context)

        context.bot.get_file.assert_called_once_with("file-123")
        assert telegram_file.downloaded_to_memory == 1
        cached = list((tmp_path / "222").glob("*notes.txt"))
        assert cached and cached[0].exists()
        assert cached[0].read_bytes() == b"telegram file"
        assert str(cached[0]) in captured_prompt[0]
        assert "summarize" in captured_prompt[0]
        assert "notes.txt" in captured_prompt[0]
        assert "attachment_mode: path" in captured_prompt[0]

    @pytest.mark.skipif(os.name == "nt", reason="owner-only modes are POSIX-only")
    @pytest.mark.asyncio
    async def test_document_message_stores_cached_attachment_owner_only(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path)
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "notes.txt"
        document.file_size = 12
        update = make_update(text=None, caption="summarize", document=document)
        context = make_context()
        context.bot.get_file = AsyncMock(return_value=FakeTelegramFile())

        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(bot.executor, "run", return_value=result):
            await bot.handle_message(update, context)

        cached = list((tmp_path / "222").glob("*notes.txt"))
        assert cached and cached[0].stat().st_mode & 0o777 == 0o600

    @pytest.mark.asyncio
    async def test_copy_to_project_attachment_mode_passes_project_path(self, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        cache_dir = tmp_path / "cache"
        bot = make_bot(
            project_dir=str(project_dir),
            attachment_dir=cache_dir,
            attachment_mode="copy-to-project",
        )
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "notes.txt"
        document.file_size = 12
        update = make_update(text=None, caption="summarize", document=document)
        context = make_context()
        telegram_file = FakeTelegramFile()
        context.bot.get_file = AsyncMock(return_value=telegram_file)

        captured_prompt = []
        result = ExecutionResult(text="ok", session_id="s1")

        async def capture_run(**kwargs):
            captured_prompt.append(kwargs["prompt"])
            return result

        with patch.object(bot.executor, "run", side_effect=capture_run):
            await bot.handle_message(update, context)

        assert telegram_file.downloaded_to_memory == 1
        cached_path = list((cache_dir / "222").glob("*notes.txt"))[0]
        project_attachment_dir = project_dir / ".tgcc-attachments" / "222"
        copied = list(project_attachment_dir.glob("*notes.txt"))
        assert cached_path.exists()
        assert copied and copied[0].exists()
        assert copied[0].read_bytes() == b"telegram file"
        assert project_attachment_dir.stat().st_mode & 0o777 == 0o700
        assert copied[0].stat().st_mode & 0o777 == 0o600
        assert str(copied[0]) in captured_prompt[0]
        assert str(cached_path) not in captured_prompt[0]
        assert "attachment_mode: copy-to-project" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_copy_to_project_failure_cleans_cache_and_reports_clearly(
        self, tmp_path
    ):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        cache_dir = tmp_path / "cache"
        bot = make_bot(
            project_dir=str(project_dir),
            attachment_dir=cache_dir,
            attachment_mode="copy-to-project",
        )
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "notes.txt"
        document.file_size = 12
        update = make_update(text=None, caption="summarize", document=document)
        context = make_context()
        context.bot.get_file = AsyncMock(return_value=FakeTelegramFile())

        with (
            patch(
                "claude_code_tg.message_input.copy_attachment_to_project",
                side_effect=OSError("project dir is read-only"),
            ),
            patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run,
        ):
            await bot.handle_message(update, context)

        # The run never starts because the prompt build raised.
        mock_run.assert_not_called()
        reply = update.message.reply_text.call_args[0][0]
        # Clear, accurate message — not the misleading "download failed".
        assert "复制到项目目录失败" in reply
        assert "附件下载失败" not in reply
        # The orphaned instance-cache file must be cleaned up.
        assert list((cache_dir / "222").glob("*notes.txt")) == []

    @pytest.mark.asyncio
    async def test_reject_attachment_mode_rejects_before_download(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path, attachment_mode="reject")
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "notes.txt"
        document.file_size = 12
        update = make_update(text=None, caption="summarize", document=document)
        context = make_context()

        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)

        context.bot.get_file.assert_not_called()
        mock_run.assert_not_called()
        assert "ATTACHMENT_MODE=reject" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_photo_message_uses_largest_photo(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path)
        small = MagicMock(file_id="small", file_unique_id="small-u", file_size=1)
        large = MagicMock(file_id="large", file_unique_id="large-u", file_size=2)
        update = make_update(text=None, caption="", photo=[small, large])
        context = make_context()
        context.bot.get_file = AsyncMock(return_value=FakeTelegramFile())
        result = ExecutionResult(text="ok", session_id="s1")

        with patch.object(
            bot.executor, "run", new_callable=AsyncMock, return_value=result
        ) as mock_run:
            await bot.handle_message(update, context)

        context.bot.get_file.assert_called_once_with("large")
        prompt = mock_run.call_args.kwargs["prompt"]
        assert "请分析这个附件" in prompt
        assert "photo-large-u.jpg" in prompt

    @pytest.mark.asyncio
    async def test_oversized_document_rejected_before_download(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path, attachment_max_bytes=5)
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "big.bin"
        document.file_size = 6
        update = make_update(text=None, caption="read", document=document)
        context = make_context()

        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)

        context.bot.get_file.assert_not_called()
        mock_run.assert_not_called()
        assert "附件过大" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_unknown_size_document_rejected_after_memory_download(self, tmp_path):
        bot = make_bot(attachment_dir=tmp_path, attachment_max_bytes=5)
        document = MagicMock()
        document.file_id = "file-123"
        document.file_unique_id = "unique-123"
        document.file_name = "big.bin"
        document.file_size = None
        update = make_update(text=None, caption="read", document=document)
        context = make_context()
        telegram_file = FakeTelegramFile(content=b"too large")
        context.bot.get_file = AsyncMock(return_value=telegram_file)

        with patch.object(bot.executor, "run", new_callable=AsyncMock) as mock_run:
            await bot.handle_message(update, context)

        assert telegram_file.downloaded_to_memory == 1
        mock_run.assert_not_called()
        assert not list((tmp_path / "222").glob("*big.bin"))
        assert "附件过大" in update.message.reply_text.call_args[0][0]
