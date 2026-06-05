"""CLI-facing attachment cleanup helpers."""

import argparse
import math
import sys
from collections.abc import Callable
from pathlib import Path

from claude_code_tg.attachments import (
    PROJECT_ATTACHMENT_DIRNAME,
    AttachmentPruneResult,
    prune_attachment_tree,
)
from claude_code_tg.instance_store import instance_paths
from claude_code_tg.utils import discover_env_files, read_env_value


def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number") from None
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("must be a finite number")
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


def project_attachment_root(env_file: Path, project_dir: str | None) -> Path:
    if project_dir:
        root = Path(project_dir)
    else:
        env_project_dir = read_env_value(env_file, "CLAUDE_PROJECT_DIR")
        root = Path(env_project_dir or ".")
    return root.expanduser() / PROJECT_ATTACHMENT_DIRNAME


def attachment_roots_for_env(
    env_file: Path, *, scope: str, project_dir: str | None
) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    if scope in {"all", "instance"}:
        _, logfile = instance_paths(str(env_file), create=False)
        roots.append(
            (f"{env_file.name} instance attachments", logfile.parent / "attachments")
        )
    if scope in {"all", "project"}:
        roots.append(
            (
                f"{env_file.name} project attachments",
                project_attachment_root(env_file, project_dir),
            )
        )
    return roots


def print_prune_result(label: str, result: AttachmentPruneResult) -> None:
    action = "Would delete" if result.dry_run else "Deleted"
    if not result.root_exists:
        print(f"{label}: no attachment directory at {result.root}")
        for error in result.errors:
            print(f"{label}: warning: {error}")
        return
    print(
        f"{label}: {action} {result.files} files "
        f"({format_bytes(result.byte_count)}) from {result.root}"
    )
    if result.dirs_removed:
        print(f"{label}: removed {result.dirs_removed} empty directories")
    for error in result.errors:
        print(f"{label}: warning: {error}")


def run_attachment_prune(
    args: argparse.Namespace,
    *,
    resolve_single_env: Callable[[str | None], Path],
) -> None:
    if args.all_envs and args.env:
        print("Error: use either --all-envs or --env, not both.")
        sys.exit(1)

    if args.all_envs:
        env_files = discover_env_files()
        if not env_files:
            print("No .env files found in current directory.")
            return
    else:
        env_files = [resolve_single_env(args.env)]

    older_than_seconds = None if args.all_files else args.older_than_days * 86400
    seen_roots: set[str] = set()
    total_files = 0
    total_bytes = 0
    total_errors = 0
    for env_file in env_files:
        for label, root in attachment_roots_for_env(
            env_file,
            scope=args.scope,
            project_dir=args.project_dir,
        ):
            root_key = str(root.expanduser().resolve(strict=False))
            if root_key in seen_roots:
                continue
            seen_roots.add(root_key)
            result = prune_attachment_tree(
                root,
                older_than_seconds=older_than_seconds,
                dry_run=args.dry_run,
            )
            print_prune_result(label, result)
            total_files += result.files
            total_bytes += result.byte_count
            total_errors += len(result.errors)

    action = "would delete" if args.dry_run else "deleted"
    print(f"Summary: {action} {total_files} files ({format_bytes(total_bytes)})")
    if total_errors:
        print(f"Summary: {total_errors} warnings")
