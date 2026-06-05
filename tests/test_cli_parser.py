"""Tests for tgcc CLI parser construction."""

import argparse
from collections.abc import Callable

import pytest

from claude_code_tg.cli_parser import CliCommandHandlers, build_parser


def _handler(_args: argparse.Namespace) -> None:
    return None


def _handlers(
    override: Callable[[argparse.Namespace], None] | None = None,
) -> CliCommandHandlers:
    handler = override or _handler
    return CliCommandHandlers(
        start=handler,
        stop=handler,
        restart=handler,
        status=handler,
        logs=handler,
        foreground=handler,
        init=handler,
        attachments=handler,
        doctor=handler,
        start_all=handler,
        stop_all=handler,
        restart_all=handler,
    )


def test_build_parser_keeps_core_command_surface() -> None:
    parser = build_parser(version="1.2.3", handlers=_handlers())

    help_text = parser.format_help()

    for command in [
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "foreground",
        "init",
        "attachments",
        "doctor",
        "start-all",
        "stop-all",
        "restart-all",
    ]:
        assert command in help_text


def test_build_parser_wires_nested_attachment_prune_options() -> None:
    parser = build_parser(version="1.2.3", handlers=_handlers())

    args = parser.parse_args(
        [
            "attachments",
            "prune",
            "--env",
            "prod.env",
            "--scope",
            "project",
            "--older-than-days",
            "0.5",
            "--dry-run",
        ]
    )

    assert args.attachments_command == "prune"
    assert args.env == "prod.env"
    assert args.scope == "project"
    assert args.older_than_days == 0.5
    assert args.dry_run is True
    assert args.func is _handler


def test_build_parser_wires_doctor_automation_options() -> None:
    parser = build_parser(version="1.2.3", handlers=_handlers())

    args = parser.parse_args(
        ["doctor", "--env", "prod.env", "--strict", "--format", "json"]
    )

    assert args.env == "prod.env"
    assert args.strict is True
    assert args.format == "json"
    assert args.func is _handler


def test_build_parser_rejects_negative_attachment_age() -> None:
    parser = build_parser(version="1.2.3", handlers=_handlers())

    with pytest.raises(SystemExit):
        parser.parse_args(["attachments", "prune", "--older-than-days", "-1"])
