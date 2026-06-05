from types import SimpleNamespace

import pytest

from claude_code_tg.message_input import TelegramInputBuilder


def _builder(tmp_path):
    return TelegramInputBuilder(
        attachment_dir=tmp_path / "attachments",
        project_dir=str(tmp_path / "project"),
        attachment_max_bytes=1024,
        attachment_mode="path",
    )


@pytest.mark.asyncio
async def test_prompt_from_update_strips_bot_mention(tmp_path):
    builder = _builder(tmp_path)
    update = SimpleNamespace(
        message=SimpleNamespace(
            text="@tgccbot hello",
            caption=None,
            photo=None,
            document=None,
        ),
        effective_chat=SimpleNamespace(id=123),
    )
    context = SimpleNamespace(bot=SimpleNamespace(username="tgccbot"))

    assert await builder.prompt_from_update(update, context) == "hello"


@pytest.mark.asyncio
async def test_prompt_from_update_rejects_message_less_update(tmp_path):
    builder = _builder(tmp_path)
    update = SimpleNamespace(message=None, effective_chat=SimpleNamespace(id=123))
    context = SimpleNamespace(bot=SimpleNamespace(username="tgccbot"))

    with pytest.raises(ValueError, match="message and chat"):
        await builder.prompt_from_update(update, context)
