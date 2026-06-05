"""Optional Telegram Mini App web console."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import parse_qsl

MINI_APP_AUTH_MAX_AGE_SECONDS = 24 * 60 * 60


class MiniAppAuthError(ValueError):
    """Raised when Telegram Mini App initData cannot be trusted."""


class MiniAppBot(Protocol):
    token: str

    def _is_authorized(self, user_id: int) -> bool: ...

    def mini_app_status(self, chat_id: int) -> dict[str, object]: ...

    async def handle_mini_app_action(
        self,
        chat_id: int,
        user_id: int,
        action: str,
        payload: dict[str, object],
        telegram_bot: Any,
    ) -> dict[str, object]: ...


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    now: int | None = None,
    max_age_seconds: int = MINI_APP_AUTH_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    values = dict(pairs)
    provided_hash = values.pop("hash", "")
    if not provided_hash:
        raise MiniAppAuthError("missing hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise MiniAppAuthError("invalid hash")

    auth_date_raw = values.get("auth_date", "")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise MiniAppAuthError("invalid auth_date") from exc
    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + 60:
        raise MiniAppAuthError("auth_date is in the future")
    if current_time - auth_date > max_age_seconds:
        raise MiniAppAuthError("initData expired")

    try:
        user = json.loads(values.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise MiniAppAuthError("invalid user payload") from exc
    user_id = user.get("id")
    if not isinstance(user_id, int):
        raise MiniAppAuthError("missing user id")

    return {"user": user, "user_id": user_id, "auth_date": auth_date}


def build_web_console_app(bot: MiniAppBot, telegram_bot: Any) -> object:
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import HTMLResponse, JSONResponse
        from starlette.routing import Route
    except ImportError as exc:
        raise ImportError(
            "Mini App support requires starlette; install the mini-app extra."
        ) from exc

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    async def status(request: Request) -> JSONResponse:
        auth = _authenticate_request(request, bot)
        chat_id = auth["user_id"]
        return JSONResponse({"ok": True, "status": bot.mini_app_status(chat_id)})

    async def action(request: Request) -> JSONResponse:
        auth = _authenticate_request(request, bot)
        user_id = auth["user_id"]
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"ok": False, "error": "invalid_payload"}, status_code=400
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {"ok": False, "error": "invalid_payload"}, status_code=400
            )
        action_name = str(payload.get("action", ""))
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            return JSONResponse(
                {"ok": False, "error": "invalid_payload"}, status_code=400
            )
        result = await bot.handle_mini_app_action(
            user_id,
            user_id,
            action_name,
            action_payload,
            telegram_bot,
        )
        status_code = 200 if result.get("ok") else 400
        return JSONResponse(result, status_code=status_code)

    return Starlette(
        routes=[
            Route("/", index, methods=["GET"]),
            Route("/api/status", _guard(status), methods=["GET"]),
            Route("/api/action", _guard(action), methods=["POST"]),
        ]
    )


def _authenticate_request(request: Any, bot: MiniAppBot) -> dict[str, Any]:
    init_data = request.headers.get("x-telegram-init-data", "")
    auth = validate_init_data(init_data, bot.token)
    user_id = auth["user_id"]
    if not bot._is_authorized(user_id):
        raise MiniAppAuthError("unauthorized")
    return auth


def _guard(
    handler: Callable[[Any], Awaitable[Any]],
) -> Callable[[Any], Awaitable[Any]]:
    async def wrapped(request: Any) -> Any:
        try:
            return await handler(request)
        except MiniAppAuthError as exc:
            from starlette.responses import JSONResponse

            return JSONResponse({"ok": False, "error": str(exc)}, status_code=401)

    return wrapped


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>tgcc</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { margin: 0; font: 15px/1.4 system-ui, -apple-system, sans-serif; background: #d5e5bd; color: #111827; }
    main { max-width: 720px; margin: 0 auto; padding: 16px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    h1 { font-size: 22px; margin: 0; }
    section { background: white; border: 0; border-radius: 18px; margin-top: 12px; padding: 12px; }
    button { border: 0; background: #7e9d6d; color: white; border-radius: 18px; padding: 8px 14px; margin: 4px 4px 0 0; font-weight: 600; }
    button.primary { background: #5d9fc8; color: white; }
    button.reset { background: #d6a35f; color: white; }
    button.danger { background: #c95f5a; color: white; }
    input { box-sizing: border-box; width: 100%; border: 0; border-radius: 18px; padding: 10px 14px; margin-top: 8px; background: white; }
    .message { min-height: 20px; margin-top: 10px; color: #374151; }
    .message.error { color: #991b1b; }
    .message.ok { color: #166534; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f3f4f6; border-radius: 6px; padding: 10px; }
  </style>
</head>
<body>
<main>
  <header><h1>tgcc</h1><button class="primary" id="refresh">Refresh</button></header>
  <div class="message" id="message" role="status"></div>
  <section><pre id="status">Loading...</pre></section>
  <section>
    <button class="danger" data-action="stop">Stop</button>
    <button class="reset" data-action="new">New Session</button>
    <button class="primary" data-action="rerun">Rerun Last</button>
    <input id="session" placeholder="session_id">
    <button data-action="resume">Resume</button>
    <input id="model" placeholder="model, e.g. sonnet">
    <button data-action="set_model">Set Model</button>
    <input id="mode" placeholder="permission mode, e.g. plan">
    <button data-action="set_permissions">Set Permissions</button>
    <input id="effort" placeholder="effort: low, medium, high, xhigh, max, ultracode">
    <button data-action="set_effort">Set Effort</button>
  </section>
</main>
<script>
const tg = window.Telegram && window.Telegram.WebApp;
const initData = tg ? tg.initData : "";
if (tg) tg.ready();
function apiUrl(path) {
  const pathname = window.location.pathname.endsWith("/") ? window.location.pathname : window.location.pathname + "/";
  return new URL(path, window.location.origin + pathname).toString();
}
async function api(path, options = {}) {
  const headers = Object.assign({"X-Telegram-Init-Data": initData}, options.headers || {});
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(apiUrl(path), Object.assign({}, options, {headers}));
  const data = await response.json().catch(() => ({ok: false, error: "invalid_response"}));
  if (!response.ok && !data.error) data.error = `HTTP ${response.status}`;
  if (!response.ok) data.ok = false;
  return data;
}
function showMessage(text, kind = "") {
  const node = document.getElementById("message");
  node.textContent = text || "";
  node.className = `message ${kind}`.trim();
}
async function refresh() {
  const data = await api("api/status");
  document.getElementById("status").textContent = JSON.stringify(data, null, 2);
  if (!data.ok) showMessage(data.error || "Refresh failed", "error");
}
async function postAction(action) {
  const payload = {};
  if (action === "resume") payload.session_id = document.getElementById("session").value;
  if (action === "set_model") payload.model = document.getElementById("model").value;
  if (action === "set_permissions") payload.mode = document.getElementById("mode").value;
  if (action === "set_effort") payload.effort = document.getElementById("effort").value;
  const result = await api("api/action", {method: "POST", body: JSON.stringify({action, payload})});
  if (result.ok) {
    showMessage(result.message || "Action completed", "ok");
  } else {
    showMessage(result.error || "Action failed", "error");
  }
  await refresh();
}
document.getElementById("refresh").addEventListener("click", refresh);
document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => postAction(button.dataset.action));
});
refresh();
</script>
</body>
</html>
"""
