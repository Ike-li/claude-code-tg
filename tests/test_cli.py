"""Tests for top-level CLI entry points."""

import os
import sys
from importlib.metadata import PackageNotFoundError
from unittest.mock import MagicMock

import pytest

from claude_code_tg.cli import (
    cli,
    cmd_foreground,
    package_version,
)


def test_cli_version_prints_package_version(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tgcc", "--version"])

    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"tgcc {package_version()}"


def test_cli_without_command_prints_help(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tgcc"])

    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "TG-Claude Code Bridge" in output
    assert "start" in output


def test_package_version_falls_back_when_distribution_missing(monkeypatch):
    def missing_distribution(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(
        "claude_code_tg.cli._distribution_version", missing_distribution
    )

    assert package_version() == "unknown"


def test_cmd_foreground_uses_resolved_env(monkeypatch, tmp_path):
    """Foreground should load the selected env through DOTENV_PATH."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    env_file = tmp_path / "cctg.env"
    env_file.write_text("TOKEN=test")

    calls = []
    monkeypatch.setattr("claude_code_tg.server.main", lambda: calls.append("main"))

    args = MagicMock()
    args.env = None
    cmd_foreground(args)

    assert calls == ["main"]
    assert os.environ["DOTENV_PATH"] == str(env_file.resolve())


def test_cmd_foreground_missing_env_exits(tmp_path, capsys):
    """Foreground should fail clearly when the selected env file is absent."""
    args = MagicMock()
    args.env = str(tmp_path / "missing.env")

    with pytest.raises(SystemExit) as exc:
        cmd_foreground(args)

    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().out


def test_cmd_foreground_rejects_symlinked_env(monkeypatch, tmp_path, capsys):
    """Foreground should not load dotenv through a user-controlled symlink."""
    monkeypatch.delenv("DOTENV_PATH", raising=False)
    real_env = tmp_path / "real.env"
    real_env.write_text("TOKEN=test", encoding="utf-8")
    link_env = tmp_path / "linked.env"
    try:
        link_env.symlink_to(real_env)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    args = MagicMock()
    args.env = str(link_env)
    with pytest.raises(SystemExit) as exc:
        cmd_foreground(args)

    assert exc.value.code == 1
    assert "env path contains a symlink" in capsys.readouterr().out
    assert "DOTENV_PATH" not in os.environ
