"""Run sanitized background Telegram Mini App API checks for E2E."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRIES = 20
DEFAULT_RETRY_DELAY_SECONDS = 0.5
VALID_SESSION_ID = "00000000-0000-4000-8000-000000000001"
MISSING = object()


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


@dataclass(frozen=True)
class ApiCheck:
    name: str
    method: str
    path: str
    expected_status: int
    expected_error: str | None = None
    init_data: str | None = None
    body: object = MISSING
    raw_body: bytes | None = None


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def first_allowed_user_id(values: dict[str, str]) -> int:
    raw_ids = values.get("ALLOWED_USER_IDS") or values.get("ADMIN_USER_IDS") or ""
    first = next((part.strip() for part in raw_ids.split(",") if part.strip()), "")
    if not first:
        raise ValueError("ALLOWED_USER_IDS or ADMIN_USER_IDS must include one user id")
    return int(first)


def signed_init_data(
    bot_token: str,
    user_id: int,
    *,
    now: int | None = None,
    offset_seconds: int = 0,
    tamper_hash: bool = False,
) -> str:
    auth_date = str((int(time.time()) if now is None else now) + offset_seconds)
    values = {
        "auth_date": auth_date,
        "query_id": "e2e-query",
        "user": json.dumps(
            {"id": user_id, "first_name": "E2E"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    digest = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if tamper_hash:
        digest = ("0" if digest[0] != "0" else "1") + digest[1:]
    values["hash"] = digest
    return urllib.parse.urlencode(values)


def request_json(
    base_url: str,
    check: ApiCheck,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    headers: dict[str, str] = {}
    if check.init_data is not None:
        headers["X-Telegram-Init-Data"] = check.init_data
    data = None
    if check.raw_body is not None:
        data = check.raw_body
        headers["Content-Type"] = "application/json"
    elif check.body is not MISSING:
        data = json.dumps(check.body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", check.path.lstrip("/")),
        data=data,
        headers=headers,
        method=check.method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _decode_json(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _decode_json(exc.read())
    except urllib.error.URLError as exc:
        return 0, {"error": type(exc).__name__}


def request_json_with_retries(
    base_url: str,
    check: ApiCheck,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> tuple[int, dict[str, Any]]:
    attempts = max(1, retries)
    for attempt in range(attempts):
        status, payload = request_json(base_url, check, timeout=timeout)
        if status != 0 or attempt == attempts - 1:
            return status, payload
        time.sleep(max(0.0, retry_delay))
    return 0, {"error": "request_failed"}


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "invalid_response"}
    return payload if isinstance(payload, dict) else {"error": "invalid_response"}


def evaluate_response(
    check: ApiCheck,
    status: int,
    payload: dict[str, Any],
) -> CheckResult:
    ok = status == check.expected_status
    if check.expected_error is not None:
        ok = ok and payload.get("error") == check.expected_error
    elif check.expected_status < 400:
        ok = ok and payload.get("ok") is True
    detail = f"HTTP {status}"
    if "error" in payload:
        detail += f" error={payload['error']}"
    elif "ok" in payload:
        detail += f" ok={payload['ok']}"
    return CheckResult(name=check.name, ok=ok, detail=detail)


def build_checks(
    *,
    valid_init_data: str,
    expired_init_data: str,
    bad_hash_init_data: str,
    unauthorized_init_data: str,
    include_no_last_prompt: bool,
) -> list[ApiCheck]:
    checks = [
        ApiCheck(
            "missing initData rejected",
            "GET",
            "/api/status",
            401,
            "missing hash",
            init_data=None,
        ),
        ApiCheck(
            "expired initData rejected",
            "GET",
            "/api/status",
            401,
            "initData expired",
            init_data=expired_init_data,
        ),
        ApiCheck(
            "bad hash rejected",
            "GET",
            "/api/status",
            401,
            "invalid hash",
            init_data=bad_hash_init_data,
        ),
        ApiCheck(
            "unauthorized user rejected",
            "GET",
            "/api/status",
            401,
            "unauthorized",
            init_data=unauthorized_init_data,
        ),
        ApiCheck(
            "valid status accepted",
            "GET",
            "/api/status",
            200,
            init_data=valid_init_data,
        ),
        ApiCheck(
            "invalid top-level payload rejected",
            "POST",
            "/api/action",
            400,
            "invalid_payload",
            init_data=valid_init_data,
            body=[],
        ),
        ApiCheck(
            "invalid action payload rejected",
            "POST",
            "/api/action",
            400,
            "invalid_payload",
            init_data=valid_init_data,
            body={"action": "set_model", "payload": "bad"},
        ),
        ApiCheck(
            "unknown action rejected",
            "POST",
            "/api/action",
            400,
            "unknown_action",
            init_data=valid_init_data,
            body={"action": "unknown", "payload": {}},
        ),
        ApiCheck(
            "invalid session rejected",
            "POST",
            "/api/action",
            400,
            "invalid_session_id",
            init_data=valid_init_data,
            body={"action": "resume", "payload": {"session_id": "not-a-uuid"}},
        ),
        ApiCheck(
            "valid resume accepted",
            "POST",
            "/api/action",
            200,
            init_data=valid_init_data,
            body={"action": "resume", "payload": {"session_id": VALID_SESSION_ID}},
        ),
        ApiCheck(
            "invalid model rejected",
            "POST",
            "/api/action",
            400,
            "invalid_model",
            init_data=valid_init_data,
            body={"action": "set_model", "payload": {"model": "--bad"}},
        ),
        ApiCheck(
            "valid model accepted",
            "POST",
            "/api/action",
            200,
            init_data=valid_init_data,
            body={"action": "set_model", "payload": {"model": "sonnet"}},
        ),
        ApiCheck(
            "model reset accepted",
            "POST",
            "/api/action",
            200,
            init_data=valid_init_data,
            body={"action": "set_model", "payload": {"model": "reset"}},
        ),
        ApiCheck(
            "invalid permission rejected",
            "POST",
            "/api/action",
            400,
            "invalid_permission_mode",
            init_data=valid_init_data,
            body={"action": "set_permissions", "payload": {"mode": "wild"}},
        ),
        ApiCheck(
            "valid permission accepted",
            "POST",
            "/api/action",
            200,
            init_data=valid_init_data,
            body={"action": "set_permissions", "payload": {"mode": "plan"}},
        ),
        ApiCheck(
            "permission reset accepted",
            "POST",
            "/api/action",
            200,
            init_data=valid_init_data,
            body={"action": "set_permissions", "payload": {"mode": "reset"}},
        ),
    ]
    if include_no_last_prompt:
        checks.append(
            ApiCheck(
                "rerun without last prompt rejected",
                "POST",
                "/api/action",
                400,
                "no_last_prompt",
                init_data=valid_init_data,
                body={"action": "rerun", "payload": {}},
            )
        )
    checks.extend(
        [
            ApiCheck(
                "stop action accepted",
                "POST",
                "/api/action",
                200,
                init_data=valid_init_data,
                body={"action": "stop", "payload": {}},
            ),
            ApiCheck(
                "new action accepted",
                "POST",
                "/api/action",
                200,
                init_data=valid_init_data,
                body={"action": "new", "payload": {}},
            ),
            ApiCheck(
                "malformed JSON rejected",
                "POST",
                "/api/action",
                400,
                "invalid_payload",
                init_data=valid_init_data,
                raw_body=b"{",
            ),
        ]
    )
    return checks


def run_checks(
    env_values: dict[str, str],
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
    now: int | None = None,
) -> list[CheckResult]:
    token = env_values.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be configured")
    user_id = first_allowed_user_id(env_values)
    unauthorized_user_id = user_id + 987654321
    if unauthorized_user_id == user_id:
        unauthorized_user_id += 1
    current_time = int(time.time()) if now is None else now
    valid = signed_init_data(token, user_id, now=current_time)
    status_check = ApiCheck(
        "initial status", "GET", "/api/status", 200, init_data=valid
    )
    status, payload = request_json_with_retries(
        base_url,
        status_check,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    )
    status_result = evaluate_response(status_check, status, payload)
    include_no_last_prompt = status_result.ok and not payload.get("status", {}).get(
        "last_prompt_available", False
    )
    results = [status_result]
    if status_result.ok and not include_no_last_prompt:
        results.append(
            CheckResult(
                "rerun without last prompt rejected",
                True,
                "skipped because last_prompt_available=true",
                skipped=True,
            )
        )
    checks = build_checks(
        valid_init_data=valid,
        expired_init_data=signed_init_data(
            token,
            user_id,
            now=current_time,
            offset_seconds=-(25 * 60 * 60),
        ),
        bad_hash_init_data=signed_init_data(
            token,
            user_id,
            now=current_time,
            tamper_hash=True,
        ),
        unauthorized_init_data=signed_init_data(
            token,
            unauthorized_user_id,
            now=current_time,
        ),
        include_no_last_prompt=include_no_last_prompt,
    )
    for check in checks:
        status, payload = request_json_with_retries(
            base_url,
            check,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
        )
        results.append(evaluate_response(check, status, payload))
    return results


def print_results(results: Iterable[CheckResult]) -> int:
    passed = 0
    failed = 0
    skipped = 0
    for result in results:
        if result.skipped:
            skipped += 1
            label = "SKIP"
        elif result.ok:
            passed += 1
            label = "PASS"
        else:
            failed += 1
            label = "FAIL"
        print(f"{label} {result.name}: {result.detail}")
    print(f"SUMMARY pass={passed} fail={failed} skip={skipped}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Ignored E2E env file")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Mini App local base URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-request timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retry count for a not-yet-ready Mini App server",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY_SECONDS,
        help="Delay between readiness retries in seconds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = run_checks(
        load_env_file(args.env),
        base_url=args.base_url,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )
    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
