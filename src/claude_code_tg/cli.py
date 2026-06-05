"""tgcc - CLI tool to manage the TG-Claude Code Bridge."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as _distribution_version
from pathlib import Path

from claude_code_tg.attachment_cleanup import (
    run_attachment_prune as _run_attachment_prune,
)
from claude_code_tg.cli_init import cmd_init
from claude_code_tg.cli_instances import (
    print_status_for_env as _print_status_for_env,
    resolve_single_env as _resolve_single_env,
    rewind_if_truncated as _rewind_if_truncated,
    show_instance_logs as _show_instance_logs,
)
from claude_code_tg.cli_parser import CliCommandHandlers, build_parser as _build_parser
from claude_code_tg.diagnostics import (
    doctor_exit_code as _doctor_exit_code,
    fix_local_permissions as _fix_local_permissions,
    render_doctor_json as _render_doctor_json,
    render_doctor_report as _render_doctor_report,
    run_doctor as _run_doctor,
)
from claude_code_tg.file_security import (
    open_owner_only_append as _open_owner_only_append,
    open_rejecting_symlink_read as _open_rejecting_symlink_read,
    rejectable_symlink_path_component as _rejectable_symlink_path_component,
    write_owner_only_text as _write_owner_only_text,
)
from claude_code_tg.instance_store import (
    instance_paths as _instance_paths,
    migrate_stale_legacy_instance as _migrate_stale_legacy_instance,
    rotate_log as _rotate_log,
    running_instances as _running_instances,
    write_instance_metadata as _write_instance_metadata,
)
from claude_code_tg.process_control import (
    send_signal_to_process_tree as _send_signal_to_process_tree,
    wait_for_exit as _wait_for_exit,
)
from claude_code_tg.sanitizer import sanitize as _sanitize
from claude_code_tg.utils import discover_env_files

STOP_TIMEOUT_SECONDS = 10
KILL_TIMEOUT_SECONDS = 5
STARTUP_CHECK_SECONDS = 0.3
STARTUP_READY_TIMEOUT_SECONDS = 10.0
STARTUP_READY_POLL_SECONDS = 0.1
DIST_NAME = "claude-code-tg"


def package_version() -> str:
    try:
        return _distribution_version(DIST_NAME)
    except PackageNotFoundError:
        return "unknown"


def _flag_enabled(args: argparse.Namespace, name: str) -> bool:
    return getattr(args, name, False) is True


def _reject_symlinked_env_file(env_file: Path) -> None:
    symlink = _rejectable_symlink_path_component(env_file)
    if not symlink:
        return
    print(f"Error: env path contains a symlink ({symlink}); refusing to use it.")
    sys.exit(1)


def _terminate_started_process(pid: int) -> None:
    try:
        _send_signal_to_process_tree(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if _wait_for_exit(pid, timeout=STOP_TIMEOUT_SECONDS):
        return
    try:
        _send_signal_to_process_tree(pid, signal.SIGKILL)
        _wait_for_exit(pid, timeout=KILL_TIMEOUT_SECONDS)
    except ProcessLookupError:
        return


def _status_file_ready(status_file: Path, launched_at: float) -> bool:
    if _rejectable_symlink_path_component(status_file) or not status_file.exists():
        return False
    try:
        with _open_rejecting_symlink_read(status_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    timestamp = data.get("timestamp")
    return (
        isinstance(timestamp, (int, float))
        and not isinstance(timestamp, bool)
        and timestamp >= launched_at
    )


def _last_error_lines(logfile: Path, *, max_lines: int = 3) -> list[str]:
    """Return the last few ``[ERROR]`` log lines, sanitized, for start failures.

    The server validates config in a detached subprocess and only writes the
    real reason (e.g. a ConfigError) to the log. Surfacing it here saves a new
    user from having to know to run ``tgcc logs`` to find why start failed.
    """
    if _rejectable_symlink_path_component(logfile) or not logfile.exists():
        return []
    try:
        with _open_rejecting_symlink_read(logfile, errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    errors = [line.rstrip("\n") for line in lines if "[ERROR]" in line]
    return [_sanitize(line) for line in errors[-max_lines:]]


def _print_start_failure_reason(logfile: Path) -> None:
    reasons = _last_error_lines(logfile)
    if reasons:
        print("Reason:")
        for line in reasons:
            print(f"  {line}")
    else:
        print("No error was logged. Run 'tgcc foreground --env <file>' to start")
        print("in the foreground and watch the output, or read the log below.")
    print(f"Logs: {logfile}")


def _wait_for_startup_ready(
    proc: subprocess.Popen,
    status_file: Path,
    *,
    launched_at: float,
) -> tuple[bool, int | None]:
    if STARTUP_CHECK_SECONDS > 0:
        time.sleep(STARTUP_CHECK_SECONDS)
    deadline = time.monotonic() + STARTUP_READY_TIMEOUT_SECONDS
    while True:
        exit_code = proc.poll()
        if exit_code is not None:
            return False, exit_code
        if _status_file_ready(status_file, launched_at):
            return True, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, None
        time.sleep(min(STARTUP_READY_POLL_SECONDS, remaining))


def cmd_start(args: argparse.Namespace) -> None:
    import shutil

    if not shutil.which("claude"):
        print("Error: Claude Code CLI not found.")
        sys.exit(1)

    env_file = _resolve_single_env(args.env, command="start")
    _reject_symlinked_env_file(env_file)
    if not env_file.exists():
        print(
            f"Error: {env_file} not found. Copy .env.example and fill in your config."
        )
        sys.exit(1)

    running = _running_instances(str(env_file))
    if running:
        pids = ", ".join(str(pid) for pid, _, _ in running)
        print(f"Already running (PID {pids}). Use 'tgcc stop --env {env_file}' first.")
        sys.exit(1)
    try:
        _migrate_stale_legacy_instance(str(env_file))
        pidfile, logfile = _instance_paths(str(env_file), create=True)
        # Archive the previous run's log so each start writes a fresh tgcc.log.
        _rotate_log(logfile, timestamp=datetime.now().strftime("%Y%m%d-%H%M%S"))
        log = _open_owner_only_append(logfile)
    except OSError as exc:
        print(f"Error: could not prepare runtime files for {env_file}: {exc}")
        sys.exit(1)

    try:
        try:
            launched_at = time.time()
            proc = subprocess.Popen(
                [sys.executable, "-m", "claude_code_tg.server"],
                env={**os.environ, "DOTENV_PATH": str(env_file.resolve())},
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        except OSError as exc:
            print(f"Error: could not launch tgcc server for {env_file}: {exc}")
            print(f"Logs: {logfile}")
            sys.exit(1)
        status_file = logfile.parent / "status.json"
        ready, exit_code = _wait_for_startup_ready(
            proc,
            status_file,
            launched_at=launched_at,
        )
        if not ready and exit_code is not None:
            print(f"Failed to start (exit code {exit_code}).")
            _print_start_failure_reason(logfile)
            sys.exit(1)
        if not ready:
            _terminate_started_process(proc.pid)
            print(
                "Failed to start: startup status was not written within "
                f"{STARTUP_READY_TIMEOUT_SECONDS:g}s."
            )
            _print_start_failure_reason(logfile)
            sys.exit(1)
        try:
            _write_instance_metadata(pidfile.parent, env_file)
            _write_owner_only_text(pidfile, str(proc.pid))
        except OSError as exc:
            _terminate_started_process(proc.pid)
            print(f"Error: could not record runtime files for {env_file}: {exc}")
            print(f"Logs: {logfile}")
            sys.exit(1)
        print(f"Started (PID {proc.pid})")
        print(f"Logs: {logfile}")
    finally:
        log.close()


def cmd_stop(args: argparse.Namespace) -> None:
    env_file = _resolve_single_env(args.env, command="stop")
    running = _running_instances(str(env_file))
    if not running:
        print("Not running.")
        return
    for pid, pidfile, _ in running:
        try:
            _send_signal_to_process_tree(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            if not _wait_for_exit(pid, timeout=STOP_TIMEOUT_SECONDS):
                print(f"Warning: PID {pid} did not exit, sending SIGKILL...")
                try:
                    _send_signal_to_process_tree(pid, signal.SIGKILL)
                    _wait_for_exit(pid, timeout=KILL_TIMEOUT_SECONDS)
                except ProcessLookupError:
                    pass
        try:
            pidfile.unlink(missing_ok=True)
        except OSError as exc:
            print(f"Warning: could not remove pid file {pidfile}: {exc}")
        print(f"Stopped (PID {pid})")


def cmd_restart(args: argparse.Namespace) -> None:
    cmd_stop(args)
    cmd_start(args)


def cmd_status(args: argparse.Namespace) -> None:
    all_instances = _flag_enabled(args, "all")
    if all_instances and args.env:
        print("Error: use either --all or --env, not both.")
        sys.exit(1)

    env_files = discover_env_files() if all_instances or not args.env else []
    if all_instances or (not args.env and len(env_files) > 1):
        if not env_files:
            print("No .env files found in current directory.")
            return
        print("Instances:")
        width = max(len(env_file.name) for env_file in env_files)
        for env_file in env_files:
            _print_status_for_env(env_file, width)
        print("Use 'tgcc logs --env <file>' to inspect one instance.")
        return

    env_file = _resolve_single_env(args.env, command="status")
    running = _running_instances(str(env_file))
    if running:
        for pid, _, logfile in running:
            print(f"Running (PID {pid})")
            print(f"Logs: {logfile}")
    else:
        _, logfile = _instance_paths(str(env_file), create=False)
        print("Not running.")
        print(f"Logs: {logfile}")


def cmd_logs(args: argparse.Namespace) -> None:
    env_file = _resolve_single_env(args.env, command="logs")
    _, logfile = _instance_paths(str(env_file), create=False)
    symlink = _rejectable_symlink_path_component(logfile)
    if symlink:
        print(f"Log path contains a symlink ({symlink}); refusing to read.")
        return
    if not logfile.exists():
        print("No log file found.")
        return
    n = max(0, args.lines)
    try:
        with _open_rejecting_symlink_read(logfile, errors="replace") as f:
            if n > 0:
                lines = f.readlines()
                for line in lines[-n:]:
                    print(line, end="")
            else:
                f.seek(0, os.SEEK_END)
            if args.follow:
                while True:
                    line = f.readline()
                    if line:
                        print(line, end="")
                    else:
                        _rewind_if_truncated(logfile, f)
                        time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def cmd_foreground(args: argparse.Namespace) -> None:
    from claude_code_tg.server import main

    env_file = _resolve_single_env(args.env, command="foreground")
    _reject_symlinked_env_file(env_file)
    if not env_file.exists():
        print(
            f"Error: {env_file} not found. Copy .env.example and fill in your config."
        )
        sys.exit(1)
    os.environ["DOTENV_PATH"] = str(env_file.resolve())
    main()


def cmd_attachments_prune(args: argparse.Namespace) -> None:
    _run_attachment_prune(
        args,
        resolve_single_env=lambda env: _resolve_single_env(
            env, command="attachments prune"
        ),
    )


def cmd_attachments(args: argparse.Namespace) -> None:
    if args.attachments_command == "prune":
        cmd_attachments_prune(args)
        return
    print("Error: missing attachments command.")
    sys.exit(1)


def cmd_doctor(args: argparse.Namespace) -> None:
    env_file = _resolve_single_env(args.env, command="doctor")
    repair_diagnostics = []
    if _flag_enabled(args, "fix_permissions"):
        repair_diagnostics.append(_fix_local_permissions(env_file))
    diagnostics = _run_doctor(env_file)
    all_diagnostics = [*repair_diagnostics, *diagnostics]
    if getattr(args, "format", "text") == "json":
        print(_render_doctor_json(all_diagnostics))
    else:
        print(_render_doctor_report(all_diagnostics))
    exit_code = _doctor_exit_code(all_diagnostics, strict=_flag_enabled(args, "strict"))
    if exit_code:
        sys.exit(exit_code)


def cmd_start_all(args: argparse.Namespace) -> None:
    env_files = discover_env_files()
    if not env_files:
        print("No .env files found in current directory.")
        return
    for env_file in env_files:
        args.env = str(env_file)
        running = _running_instances(str(env_file))
        if running:
            pids = ", ".join(str(pid) for pid, _, _ in running)
            print(f"  {env_file.name}: already running (PID {pids})")
            logfiles = ", ".join(str(logfile) for _, _, logfile in running)
            print(f"    Logs: {logfiles}")
            continue
        try:
            cmd_start(args)
        except SystemExit as e:
            if e.code != 0:
                print(f"  Failed to start {env_file.name}")

    if _flag_enabled(args, "logs") or _flag_enabled(args, "follow"):
        _show_instance_logs(
            env_files,
            lines=max(0, args.lines),
            follow=_flag_enabled(args, "follow"),
        )


def cmd_stop_all(args: argparse.Namespace) -> None:
    env_files = discover_env_files()
    if not env_files:
        print("No .env files found in current directory.")
        return
    for env_file in env_files:
        args.env = str(env_file)
        cmd_stop(args)


def cmd_restart_all(args: argparse.Namespace) -> None:
    env_files = discover_env_files()
    if not env_files:
        print("No .env files found in current directory.")
        return
    for env_file in env_files:
        args.env = str(env_file)
        try:
            cmd_restart(args)
        except SystemExit as e:
            if e.code != 0:
                print(f"  Failed to restart {env_file.name}")


def cli() -> None:
    parser = _build_parser(
        version=package_version(),
        handlers=CliCommandHandlers(
            start=cmd_start,
            stop=cmd_stop,
            restart=cmd_restart,
            status=cmd_status,
            logs=cmd_logs,
            foreground=cmd_foreground,
            init=cmd_init,
            attachments=cmd_attachments,
            doctor=cmd_doctor,
            start_all=cmd_start_all,
            stop_all=cmd_stop_all,
            restart_all=cmd_restart_all,
        ),
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    cli()
