"""CLI helpers for env selection and multi-instance log display."""

from __future__ import annotations

import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from claude_code_tg.file_security import (
    open_rejecting_symlink_read,
    rejectable_symlink_path_component,
)
from claude_code_tg.instance_store import (
    instance_paths,
    running_instances,
)
from claude_code_tg.utils import discover_env_files


def rewind_if_truncated(logfile: Path, handle: TextIO) -> None:
    """Seek back to the start when a followed log file was rotated/truncated."""
    try:
        if logfile.stat().st_size < handle.tell():
            handle.seek(0)
    except OSError:
        pass


def format_env_list(env_files: list[Path]) -> str:
    return ", ".join(env_file.name for env_file in env_files)


def resolve_single_env(
    env: str | None,
    *,
    command: str,
    allow_implicit_single: bool = True,
) -> Path:
    """Resolve the env file for commands that operate on one instance."""
    if env:
        return Path(env)

    default_env = Path(".env")
    if default_env.exists():
        return default_env

    env_files = discover_env_files()
    if allow_implicit_single and len(env_files) == 1:
        return env_files[0]

    if env_files:
        print(f"Multiple .env files found: {format_env_list(env_files)}")
        if command == "start":
            print("Use 'tgcc start-all' or 'tgcc start --env <file>'.")
        elif command == "logs":
            print("Use 'tgcc logs --env <file>' to inspect one instance.")
        elif command == "status":
            print("Use 'tgcc status --all' or 'tgcc status --env <file>'.")
        elif command == "foreground":
            print("Use 'tgcc foreground --env <file>' to debug one instance.")
        elif command == "doctor":
            print("Use 'tgcc doctor --env <file>' to inspect one instance.")
        elif command == "attachments prune":
            print(
                "Use 'tgcc attachments prune --all-envs' or "
                "'tgcc attachments prune --env <file>'."
            )
        elif " " in command:
            print(f"Use 'tgcc {command} --env <file>'.")
        else:
            print(f"Use 'tgcc {command} --env <file>' or 'tgcc {command}-all'.")
        sys.exit(1)

    return default_env


def print_status_for_env(env_file: Path, width: int | None = None) -> None:
    running = running_instances(str(env_file))
    _, logfile = instance_paths(str(env_file), create=False)
    label = env_file.name if width is None else f"{env_file.name:<{width}}"
    if running:
        pids = ", ".join(str(pid) for pid, _, _ in running)
        print(f"  {label}  Running (PID {pids})  Logs: {logfile}")
    else:
        print(f"  {label}  Not running.        Logs: {logfile}")


def print_prefixed_log_line(label: str, line: str) -> None:
    end = "" if line.endswith("\n") else "\n"
    print(f"[{label}] {line}", end=end)


def print_instance_log_tail(env_file: Path, lines: int) -> None:
    _, logfile = instance_paths(str(env_file), create=False)
    print(f"\n== {env_file.name} | {logfile} ==")
    symlink = rejectable_symlink_path_component(logfile)
    if symlink:
        print(
            f"[{env_file.name}] Log path contains a symlink ({symlink}); "
            "refusing to read."
        )
        return
    if not logfile.exists():
        print(f"[{env_file.name}] No log file found.")
        return
    try:
        with open_rejecting_symlink_read(logfile, errors="replace") as f:
            for line in f.readlines()[-lines:]:
                print_prefixed_log_line(env_file.name, line)
    except OSError as exc:
        print(f"[{env_file.name}] Could not read log file: {exc}")


def _open_log_followers(
    env_files: list[Path], stack: ExitStack
) -> list[tuple[str, Path, TextIO]]:
    followers: list[tuple[str, Path, TextIO]] = []
    for env_file in env_files:
        _, logfile = instance_paths(str(env_file), create=False)
        symlink = rejectable_symlink_path_component(logfile)
        if symlink:
            print(
                f"[{env_file.name}] Log path contains a symlink ({symlink}); "
                "refusing to follow."
            )
            continue
        if not logfile.exists():
            print(f"[{env_file.name}] No log file found.")
            continue
        try:
            f = stack.enter_context(
                open_rejecting_symlink_read(logfile, errors="replace")
            )
        except OSError as exc:
            print(f"[{env_file.name}] Could not follow log file: {exc}")
            continue
        f.seek(0, os.SEEK_END)
        followers.append((env_file.name, logfile, f))
    return followers


def show_instance_logs(env_files: list[Path], *, lines: int, follow: bool) -> None:
    if lines > 0:
        for env_file in env_files:
            print_instance_log_tail(env_file, lines)

    if not follow:
        return

    print("\nFollowing logs. Press Ctrl+C to stop.")
    try:
        with ExitStack() as stack:
            followers = _open_log_followers(env_files, stack)
            while followers:
                printed = False
                for label, logfile, f in followers:
                    line = f.readline()
                    if line:
                        print_prefixed_log_line(label, line)
                        printed = True
                        continue
                    rewind_if_truncated(logfile, f)
                if not printed:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
