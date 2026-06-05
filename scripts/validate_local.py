"""Run the local validation ladder for tgcc contributors."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_commands() -> list[list[str]]:
    return [
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


def run_commands(
    commands: list[list[str]],
    *,
    cwd: Path = REPO_ROOT,
    dry_run: bool = False,
) -> int:
    for command in commands:
        print("$ " + shlex.join(command), flush=True)
        if dry_run:
            continue
        result = subprocess.run(command, check=False, cwd=cwd)
        if result.returncode != 0:
            return result.returncode
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root where validation commands run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print validation commands without running them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = build_commands()
    return run_commands(commands, cwd=args.repo_root.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
