import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from claude_code_tg.web_console import validate_init_data

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e2e_mini_app_api.py"
SPEC = importlib.util.spec_from_file_location("e2e_mini_app_api", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_mini_app_api = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_mini_app_api
SPEC.loader.exec_module(e2e_mini_app_api)
assert isinstance(e2e_mini_app_api, ModuleType)


def test_signed_init_data_matches_web_console_validator() -> None:
    init_data = e2e_mini_app_api.signed_init_data("123:fake", 222, now=1000)

    auth = validate_init_data(init_data, "123:fake", now=1000)

    assert auth["user_id"] == 222


def test_first_allowed_user_id_prefers_allowed_then_admin() -> None:
    assert (
        e2e_mini_app_api.first_allowed_user_id(
            {"ALLOWED_USER_IDS": " 222,333 ", "ADMIN_USER_IDS": "111"}
        )
        == 222
    )
    assert e2e_mini_app_api.first_allowed_user_id({"ADMIN_USER_IDS": "111"}) == 111


def test_evaluate_response_checks_status_and_error() -> None:
    check = e2e_mini_app_api.ApiCheck(
        "bad hash",
        "GET",
        "/api/status",
        401,
        "invalid hash",
    )

    ok = e2e_mini_app_api.evaluate_response(
        check,
        401,
        {"ok": False, "error": "invalid hash"},
    )
    bad = e2e_mini_app_api.evaluate_response(
        check,
        500,
        {"ok": False, "error": "invalid hash"},
    )

    assert ok.ok is True
    assert bad.ok is False


def test_run_checks_includes_valid_resume_and_no_last_prompt(monkeypatch) -> None:
    seen: list[str] = []

    def fake_request_json(_base_url, check, *, timeout):
        seen.append(check.name)
        if check.name == "initial status":
            return 200, {"ok": True, "status": {"last_prompt_available": False}}
        if check.expected_error is not None:
            return check.expected_status, {"ok": False, "error": check.expected_error}
        return check.expected_status, {"ok": True}

    monkeypatch.setattr(e2e_mini_app_api, "request_json", fake_request_json)

    results = e2e_mini_app_api.run_checks(
        {"TELEGRAM_BOT_TOKEN": "123:fake", "ALLOWED_USER_IDS": "222"},
        now=1000,
    )

    assert all(result.ok for result in results)
    assert "valid resume accepted" in seen
    assert "rerun without last prompt rejected" in seen


def test_request_json_with_retries_waits_for_ready_server(monkeypatch) -> None:
    check = e2e_mini_app_api.ApiCheck("ready", "GET", "/api/status", 200)
    calls = 0
    sleeps: list[float] = []

    def fake_request_json(_base_url, _check, *, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 0, {"error": "URLError"}
        return 200, {"ok": True}

    monkeypatch.setattr(e2e_mini_app_api, "request_json", fake_request_json)
    monkeypatch.setattr(e2e_mini_app_api.time, "sleep", sleeps.append)

    status, payload = e2e_mini_app_api.request_json_with_retries(
        "http://127.0.0.1:8787",
        check,
        retries=2,
        retry_delay=0.25,
    )

    assert status == 200
    assert payload == {"ok": True}
    assert calls == 2
    assert sleeps == [0.25]


def test_run_checks_skips_no_last_prompt_when_last_prompt_exists(monkeypatch) -> None:
    seen: list[str] = []

    def fake_request_json(_base_url, check, *, timeout):
        seen.append(check.name)
        if check.name == "initial status":
            return 200, {"ok": True, "status": {"last_prompt_available": True}}
        if check.expected_error is not None:
            return check.expected_status, {"ok": False, "error": check.expected_error}
        return check.expected_status, {"ok": True}

    monkeypatch.setattr(e2e_mini_app_api, "request_json", fake_request_json)

    results = e2e_mini_app_api.run_checks(
        {"TELEGRAM_BOT_TOKEN": "123:fake", "ALLOWED_USER_IDS": "222"},
        now=1000,
    )

    assert all(result.ok for result in results)
    assert any(
        result.name == "rerun without last prompt rejected" and result.skipped
        for result in results
    )
    assert "rerun without last prompt rejected" not in seen
