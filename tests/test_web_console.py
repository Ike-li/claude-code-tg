"""Tests for the optional Telegram Mini App console."""

from __future__ import annotations

import builtins
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest

from claude_code_tg.bot import TGBot
from claude_code_tg.web_console import (
    MiniAppAuthError,
    build_web_console_app,
    validate_init_data,
)
from tests.bot_helpers import VALID_SESSION_ID, make_bot


def _signed_init_data(
    token: str,
    *,
    user_id: int = 222,
    auth_date: int = 1000,
) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query",
        "user": json.dumps(
            {"id": user_id, "first_name": "Ray"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    values["hash"] = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(values)


def test_validate_init_data_accepts_signed_payload() -> None:
    init_data = _signed_init_data("123:fake")

    auth = validate_init_data(init_data, "123:fake", now=1000)

    assert auth["user_id"] == 222


def test_validate_init_data_rejects_expired_payload() -> None:
    init_data = _signed_init_data("123:fake", auth_date=1000)

    with pytest.raises(MiniAppAuthError, match="expired"):
        validate_init_data(init_data, "123:fake", now=1000 + 24 * 60 * 60 + 1)


def test_validate_init_data_rejects_bad_hash() -> None:
    init_data = _signed_init_data("123:fake").replace("hash=", "hash=bad")

    with pytest.raises(MiniAppAuthError, match="invalid hash"):
        validate_init_data(init_data, "123:fake", now=1000)


def test_web_console_status_and_action_routes() -> None:
    testclient = pytest.importorskip("starlette.testclient")

    class FakeBot:
        token = "123:fake"

        def _is_authorized(self, user_id: int) -> bool:
            return user_id == 222

        def mini_app_status(self, chat_id: int) -> dict[str, object]:
            return {"chat_id": chat_id, "busy": False}

        async def handle_mini_app_action(
            self,
            chat_id: int,
            user_id: int,
            action: str,
            payload: dict[str, object],
            telegram_bot,
        ) -> dict[str, object]:
            return {
                "ok": True,
                "chat_id": chat_id,
                "user_id": user_id,
                "action": action,
                "payload": payload,
            }

    app = build_web_console_app(FakeBot(), MagicMock())
    client = testclient.TestClient(app)
    headers = {
        "X-Telegram-Init-Data": _signed_init_data(
            "123:fake",
            auth_date=int(time.time()),
        )
    }

    status = client.get("/api/status", headers=headers)
    action = client.post(
        "/api/action",
        headers=headers,
        json={"action": "stop", "payload": {"reason": "test"}},
    )

    assert status.status_code == 200
    assert status.json()["status"]["chat_id"] == 222
    assert action.status_code == 200
    assert action.json()["action"] == "stop"


def test_web_console_action_rejects_malformed_json() -> None:
    testclient = pytest.importorskip("starlette.testclient")

    class FakeBot:
        token = "123:fake"

        def _is_authorized(self, user_id: int) -> bool:
            return user_id == 222

        def mini_app_status(self, chat_id: int) -> dict[str, object]:
            return {"chat_id": chat_id}

        async def handle_mini_app_action(
            self,
            chat_id: int,
            user_id: int,
            action: str,
            payload: dict[str, object],
            telegram_bot,
        ) -> dict[str, object]:
            return {"ok": True}

    app = build_web_console_app(FakeBot(), MagicMock())
    client = testclient.TestClient(app)
    headers = {
        "X-Telegram-Init-Data": _signed_init_data(
            "123:fake",
            auth_date=int(time.time()),
        )
    }

    response = client.post(
        "/api/action",
        headers=headers,
        content=b"{",
    )

    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "invalid_payload"}


def test_web_console_index_loads_telegram_js_and_relative_api_paths() -> None:
    testclient = pytest.importorskip("starlette.testclient")

    class FakeBot:
        token = "123:fake"

        def _is_authorized(self, user_id: int) -> bool:
            return user_id == 222

        def mini_app_status(self, chat_id: int) -> dict[str, object]:
            return {"chat_id": chat_id}

        async def handle_mini_app_action(
            self,
            chat_id: int,
            user_id: int,
            action: str,
            payload: dict[str, object],
            telegram_bot,
        ) -> dict[str, object]:
            return {"ok": True}

    app = build_web_console_app(FakeBot(), MagicMock())
    client = testclient.TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "https://telegram.org/js/telegram-web-app.js" in response.text
    assert 'id="message"' in response.text
    assert "Action failed" in response.text
    assert "!response.ok" in response.text
    assert 'api("api/status")' in response.text
    assert 'api("api/action"' in response.text
    assert "button { border: 0; background: #7e9d6d;" in response.text
    assert "button.primary { background: #5d9fc8;" in response.text
    assert "button.reset { background: #d6a35f;" in response.text
    assert "button.danger { background: #c95f5a;" in response.text
    assert "border-radius: 18px" in response.text
    assert (
        '<button class="reset" data-action="new">New Session</button>' in response.text
    )
    assert (
        '<button class="primary" data-action="rerun">Rerun Last</button>'
        in response.text
    )
    assert "effort: low, medium, high, xhigh, max, ultracode" in response.text


@pytest.mark.asyncio
async def test_mini_app_new_clears_permission_model_and_effort_overrides() -> None:
    # Mini App "new" goes through reset_chat, so it must also drop stale
    # per-chat overrides (a leftover bypassPermissions is a safety concern).
    bot = make_bot()
    bot.sessions[222] = "old-session"
    bot.permission_modes[222] = "bypassPermissions"
    bot.model_overrides[222] = "opus"
    bot.effort_overrides[222] = "max"

    result = await bot.handle_mini_app_action(222, 222, "new", {}, MagicMock())

    assert result["ok"] is True
    assert 222 not in bot.sessions
    assert 222 not in bot.permission_modes
    assert 222 not in bot.model_overrides
    assert 222 not in bot.effort_overrides


@pytest.mark.asyncio
async def test_mini_app_bot_actions_manage_state_and_settings() -> None:
    bot = make_bot()
    bot.sessions[222] = "old-session"
    bot.busy.add(222)
    bot.executor.stop = AsyncMock(return_value=True)

    stop = await bot.handle_mini_app_action(222, 222, "stop", {}, MagicMock())
    new = await bot.handle_mini_app_action(222, 222, "new", {}, MagicMock())
    resume = await bot.handle_mini_app_action(
        222,
        222,
        "resume",
        {"session_id": VALID_SESSION_ID},
        MagicMock(),
    )
    model = await bot.handle_mini_app_action(
        222,
        222,
        "set_model",
        {"model": "opus"},
        MagicMock(),
    )
    permissions = await bot.handle_mini_app_action(
        222,
        222,
        "set_permissions",
        {"mode": "plan"},
        MagicMock(),
    )
    effort = await bot.handle_mini_app_action(
        222,
        222,
        "set_effort",
        {"effort": "ultra-code"},
        MagicMock(),
    )

    assert stop == {"ok": True, "stopped": True}
    assert new == {"ok": True, "stopped": True, "dropped": 0}
    assert bot.sessions[222] == VALID_SESSION_ID
    assert resume["ok"] is True
    assert bot.model_overrides[222] == "opus"
    assert model["ok"] is True
    assert bot.permission_modes[222] == "plan"
    assert permissions["ok"] is True
    assert bot.effort_overrides[222] == "ultracode"
    assert effort["ok"] is True


@pytest.mark.asyncio
async def test_mini_app_rerun_last_prompt_uses_normal_processing_path() -> None:
    bot = make_bot()
    bot.last_prompts[222] = "hello"
    telegram_bot = MagicMock()
    telegram_bot.send_message = AsyncMock()

    with patch.object(bot, "_process_message", new_callable=AsyncMock) as process:
        result = await bot.handle_mini_app_action(
            222,
            222,
            "rerun",
            {},
            telegram_bot,
        )

    assert result == {"ok": True, "queued": False}
    process.assert_awaited_once()
    assert process.await_args.args[:3] == (222, 222, "hello")


@pytest.mark.asyncio
async def test_start_mini_app_reports_missing_optional_dependencies(
    monkeypatch,
) -> None:
    bot = TGBot(
        token="123:fake",
        admin_ids={111},
        allowed_ids={222},
        project_dir="/tmp",
        mini_app_enabled=True,
        mini_app_public_url="https://example.com/tgcc",
    )
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Mini App support requires"):
        await bot.start_mini_app(AsyncMock())
