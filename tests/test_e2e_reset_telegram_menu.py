import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "e2e_reset_telegram_menu.py"
)
SPEC = importlib.util.spec_from_file_location("e2e_reset_telegram_menu", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_reset_telegram_menu = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_reset_telegram_menu
SPEC.loader.exec_module(e2e_reset_telegram_menu)
assert isinstance(e2e_reset_telegram_menu, ModuleType)


def test_reset_payload_defaults_and_chat_specific() -> None:
    assert e2e_reset_telegram_menu.reset_payload() == {
        "menu_button": {"type": "default"}
    }
    assert e2e_reset_telegram_menu.reset_payload(222) == {
        "chat_id": 222,
        "menu_button": {"type": "default"},
    }


def test_first_configured_chat_id_prefers_admin_then_allowed() -> None:
    assert (
        e2e_reset_telegram_menu.first_configured_chat_id(
            {"ADMIN_USER_IDS": "111,222", "ALLOWED_USER_IDS": "333"}
        )
        == 111
    )
    assert (
        e2e_reset_telegram_menu.first_configured_chat_id({"ALLOWED_USER_IDS": "333"})
        == 333
    )
    assert e2e_reset_telegram_menu.first_configured_chat_id({}) is None


def test_reset_menus_resets_default_and_chat_specific(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post_json(url, payload, *, timeout):
        calls.append((url, payload))
        return {"ok": True}

    monkeypatch.setattr(e2e_reset_telegram_menu, "post_json", fake_post_json)

    results = e2e_reset_telegram_menu.reset_menus(
        {"TELEGRAM_BOT_TOKEN": "123:fake", "ADMIN_USER_IDS": "222"},
        timeout=1,
    )

    assert [result.ok for result in results] == [True, True]
    assert [call[1] for call in calls] == [
        {"menu_button": {"type": "default"}},
        {"chat_id": 222, "menu_button": {"type": "default"}},
    ]


def test_reset_menus_skips_chat_specific_without_chat_id(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_post_json(_url, payload, *, timeout):
        calls.append(payload)
        return {"ok": True}

    monkeypatch.setattr(e2e_reset_telegram_menu, "post_json", fake_post_json)

    results = e2e_reset_telegram_menu.reset_menus(
        {"TELEGRAM_BOT_TOKEN": "123:fake"},
        timeout=1,
    )

    assert calls == [{"menu_button": {"type": "default"}}]
    assert results[1].skipped is True


def test_print_results_does_not_emit_chat_id(capsys) -> None:
    exit_code = e2e_reset_telegram_menu.print_results(
        [
            e2e_reset_telegram_menu.ResetResult(
                "default menu reset",
                True,
                "ok",
            ),
            e2e_reset_telegram_menu.ResetResult(
                "chat-specific menu reset",
                True,
                "ok",
            ),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "222" not in output
    assert "PASS default menu reset: ok" in output
    assert "PASS chat-specific menu reset: ok" in output
