import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e2e_macos_click.py"
SPEC = importlib.util.spec_from_file_location("e2e_macos_click", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
e2e_macos_click = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e_macos_click
SPEC.loader.exec_module(e2e_macos_click)
assert isinstance(e2e_macos_click, ModuleType)


def completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["fake"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_coregraphics_preflight_passes(monkeypatch) -> None:
    monkeypatch.setattr(e2e_macos_click, "_run", lambda _args: completed("true\n"))

    assert e2e_macos_click.coregraphics_post_event_access() is True


def test_coregraphics_preflight_fails_on_false(monkeypatch) -> None:
    monkeypatch.setattr(e2e_macos_click, "_run", lambda _args: completed("false\n"))

    assert e2e_macos_click.coregraphics_post_event_access() is False


def test_app_window_position_parses_output(monkeypatch) -> None:
    monkeypatch.setattr(e2e_macos_click, "_run", lambda _args: completed("2839,33\n"))

    assert e2e_macos_click.app_window_position("Telegram") == (2839, 33)


def test_app_window_position_reports_osascript_error(monkeypatch) -> None:
    monkeypatch.setattr(
        e2e_macos_click,
        "_run",
        lambda _args: completed("", "not allowed", returncode=1),
    )

    try:
        e2e_macos_click.app_window_position("Telegram")
    except RuntimeError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_main_dry_run_resolves_window_relative_coordinates(monkeypatch, capsys) -> None:
    monkeypatch.setattr(e2e_macos_click, "coregraphics_post_event_access", lambda: True)
    monkeypatch.setattr(e2e_macos_click, "app_window_position", lambda _app: (10, 20))

    exit_code = e2e_macos_click.main(
        ["--app", "Telegram", "--x", "3", "--y", "4", "--dry-run"]
    )

    assert exit_code == 0
    assert "global=13,24" in capsys.readouterr().out


def test_main_requires_coordinates(capsys, monkeypatch) -> None:
    monkeypatch.setattr(e2e_macos_click, "coregraphics_post_event_access", lambda: True)

    exit_code = e2e_macos_click.main(["--app", "Telegram"])

    assert exit_code == 1
    assert "--x and --y are required" in capsys.readouterr().out


def test_main_does_not_click_when_preflight_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(e2e_macos_click, "coregraphics_post_event_access", lambda: True)

    exit_code = e2e_macos_click.main(["--preflight"])

    assert exit_code == 0
    assert "PASS CoreGraphics post-event access" in capsys.readouterr().out
