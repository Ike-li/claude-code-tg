"""Reset Telegram Mini App menu buttons after E2E."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class ResetResult:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def first_configured_chat_id(values: dict[str, str]) -> int | None:
    raw_ids = values.get("ADMIN_USER_IDS") or values.get("ALLOWED_USER_IDS") or ""
    first = next((part.strip() for part in raw_ids.split(",") if part.strip()), "")
    if not first:
        return None
    return int(first)


def reset_payload(chat_id: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"menu_button": {"type": "default"}}
    if chat_id is not None:
        payload["chat_id"] = chat_id
    return payload


def post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode_json(response.read())
    except urllib.error.HTTPError as exc:
        return _decode_json(exc.read())
    except urllib.error.URLError as exc:
        return {"ok": False, "description": type(exc).__name__}


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "description": "invalid_response"}
    return (
        payload
        if isinstance(payload, dict)
        else {"ok": False, "description": "invalid_response"}
    )


def reset_menus(
    env_values: dict[str, str],
    *,
    include_chat_specific: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[ResetResult]:
    token = env_values.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be configured")
    endpoint = f"https://api.telegram.org/bot{token}/setChatMenuButton"
    results = [_call_reset(endpoint, "default menu reset", None, timeout=timeout)]
    if include_chat_specific:
        chat_id = first_configured_chat_id(env_values)
        if chat_id is None:
            results.append(
                ResetResult(
                    "chat-specific menu reset",
                    True,
                    "skipped because no admin/allowed chat id is configured",
                    skipped=True,
                )
            )
        else:
            results.append(
                _call_reset(
                    endpoint,
                    "chat-specific menu reset",
                    chat_id,
                    timeout=timeout,
                )
            )
    return results


def _call_reset(
    endpoint: str,
    name: str,
    chat_id: int | None,
    *,
    timeout: float,
) -> ResetResult:
    payload = reset_payload(chat_id)
    data = post_json(endpoint, payload, timeout=timeout)
    ok = data.get("ok") is True
    detail = "ok" if ok else str(data.get("description") or "failed")
    return ResetResult(name, ok, detail)


def print_results(results: Iterable[ResetResult]) -> int:
    failed = 0
    for result in results:
        if result.skipped:
            label = "SKIP"
        elif result.ok:
            label = "PASS"
        else:
            label = "FAIL"
            failed += 1
        print(f"{label} {result.name}: {result.detail}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Ignored E2E env file")
    parser.add_argument(
        "--default-only",
        action="store_true",
        help="Reset only the default bot menu, not the E2E chat-specific menu",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Bot API request timeout in seconds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = reset_menus(
        load_env_file(args.env),
        include_chat_specific=not args.default_only,
        timeout=args.timeout,
    )
    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
