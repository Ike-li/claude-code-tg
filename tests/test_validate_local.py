import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_local.py"
SPEC = importlib.util.spec_from_file_location("validate_local", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
validate_local = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_local
SPEC.loader.exec_module(validate_local)
assert isinstance(validate_local, ModuleType)


def test_build_commands_runs_validation_ladder_in_order() -> None:
    commands = validate_local.build_commands()

    assert commands == [
        [
            "uv",
            "run",
            "pytest",
            "--cov=claude_code_tg",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ],
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "--extra", "dev", "mypy"],
        ["uv", "run", "ruff", "format", "--check", "."],
        ["uv", "build"],
    ]


def test_run_commands_dry_run_prints_without_executing(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    def fail_run(*_args, **_kwargs):
        raise AssertionError("dry run should not execute commands")

    monkeypatch.setattr(validate_local.subprocess, "run", fail_run)

    exit_code = validate_local.run_commands(
        [["uv", "build"]],
        cwd=tmp_path,
        dry_run=True,
    )

    assert exit_code == 0
    assert "$ uv build" in capsys.readouterr().out


def test_run_commands_runs_from_repo_root(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validate_local.subprocess, "run", fake_run)

    exit_code = validate_local.run_commands(
        [["first"], ["second"]],
        cwd=tmp_path,
        dry_run=False,
    )

    assert exit_code == 0
    assert calls == [(["first"], tmp_path), (["second"], tmp_path)]


def test_run_commands_stops_on_first_failure(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(validate_local.subprocess, "run", fake_run)

    exit_code = validate_local.run_commands(
        [["first"], ["second"]],
        dry_run=False,
    )

    assert exit_code == 7
    assert calls == [["first"]]
