"""Argument parser construction for the tgcc command surface."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from claude_code_tg.attachment_cleanup import positive_float

CommandHandler = Callable[[argparse.Namespace], None]


@dataclass(frozen=True)
class CliCommandHandlers:
    start: CommandHandler
    stop: CommandHandler
    restart: CommandHandler
    status: CommandHandler
    logs: CommandHandler
    foreground: CommandHandler
    init: CommandHandler
    attachments: CommandHandler
    doctor: CommandHandler
    start_all: CommandHandler
    stop_all: CommandHandler
    restart_all: CommandHandler


def _add_env_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", help="Path to .env file (default: .env)")


def build_parser(
    *, version: str, handlers: CliCommandHandlers
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tgcc", description="TG-Claude Code Bridge")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
    )
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Start the bot in background")
    _add_env_argument(p_start)
    p_start.set_defaults(func=handlers.start)

    p_stop = sub.add_parser("stop", help="Stop the bot")
    _add_env_argument(p_stop)
    p_stop.set_defaults(func=handlers.stop)

    p_restart = sub.add_parser("restart", help="Restart the bot")
    _add_env_argument(p_restart)
    p_restart.set_defaults(func=handlers.restart)

    p_status = sub.add_parser("status", help="Check if the bot is running")
    _add_env_argument(p_status)
    p_status.add_argument(
        "--all", action="store_true", help="Show all .env instances in this directory"
    )
    p_status.set_defaults(func=handlers.status)

    p_logs = sub.add_parser("logs", help="View bot logs")
    _add_env_argument(p_logs)
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument(
        "-n", "--lines", type=int, default=50, help="Number of lines (default: 50)"
    )
    p_logs.set_defaults(func=handlers.logs)

    p_fg = sub.add_parser(
        "foreground", help="Run the bot in foreground (for debugging)"
    )
    _add_env_argument(p_fg)
    p_fg.set_defaults(func=handlers.foreground)

    p_init = sub.add_parser("init", help="Create a tgcc .env file")
    p_init.add_argument("--env", help="Path to .env file to create (default: .env)")
    p_init.add_argument(
        "--force", action="store_true", help="Overwrite the env file if it exists"
    )
    p_init.add_argument(
        "--full",
        action="store_true",
        help="Ask every config option (default: quick setup, 3 questions)",
    )
    p_init.set_defaults(func=handlers.init)

    p_attachments = sub.add_parser("attachments", help="Manage attachment files")
    p_attachments_sub = p_attachments.add_subparsers(dest="attachments_command")
    p_attachments.set_defaults(
        func=handlers.attachments,
        attachments_command=None,
    )
    p_prune = p_attachments_sub.add_parser(
        "prune", help="Delete old Telegram attachment files"
    )
    _add_env_argument(p_prune)
    p_prune.add_argument(
        "--all-envs",
        action="store_true",
        help="Prune attachments for all *.env instances in this directory",
    )
    p_prune.add_argument(
        "--scope",
        choices=["all", "instance", "project"],
        default="all",
        help="Attachment location to prune (default: all)",
    )
    p_prune.add_argument(
        "--project-dir",
        help="Override CLAUDE_PROJECT_DIR for project attachment cleanup",
    )
    p_prune.add_argument(
        "--older-than-days",
        type=positive_float,
        default=30,
        help="Delete files older than this many days (default: 30)",
    )
    p_prune.add_argument(
        "--all-files",
        action="store_true",
        help="Delete all files in the selected attachment directories",
    )
    p_prune.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without removing files",
    )
    p_prune.set_defaults(func=handlers.attachments)

    p_doctor = sub.add_parser(
        "doctor", help="Check local tgcc configuration before starting"
    )
    _add_env_argument(p_doctor)
    p_doctor.add_argument(
        "--fix-permissions",
        action="store_true",
        help="Chmod the env file and existing runtime files to owner-only modes",
    )
    p_doctor.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when doctor reports warnings as well as failures",
    )
    p_doctor.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format for diagnostics (default: text)",
    )
    p_doctor.set_defaults(func=handlers.doctor)

    p_start_all = sub.add_parser("start-all", help="Start all .env instances")
    p_start_all.add_argument(
        "--logs",
        action="store_true",
        help="Print recent logs for every .env instance after starting",
    )
    p_start_all.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Follow logs for every .env instance after starting",
    )
    p_start_all.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Number of log lines per instance when using --logs/--follow",
    )
    p_start_all.set_defaults(func=handlers.start_all)

    p_stop_all = sub.add_parser("stop-all", help="Stop all .env instances")
    p_stop_all.set_defaults(func=handlers.stop_all)

    p_restart_all = sub.add_parser("restart-all", help="Restart all .env instances")
    p_restart_all.set_defaults(func=handlers.restart_all)

    return parser
