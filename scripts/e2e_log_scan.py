"""Run sanitized Telegram E2E log scans."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from claude_code_tg.file_security import open_rejecting_symlink_read
from claude_code_tg.instance_store import instance_paths

DEFAULT_ZERO_PATTERNS = (
    "traceback",
    "telegram.error",
    "Button_copy_text_invalid",
    "ASGI",
    "Task exception was never retrieved",
)


@dataclass(frozen=True)
class PatternResult:
    pattern: str
    count: int
    must_be_zero: bool


def count_lines(text: str, pattern: str) -> int:
    needle = pattern.casefold()
    return sum(1 for line in text.splitlines() if needle in line.casefold())


def scan_text(
    text: str,
    *,
    zero_patterns: Iterable[str] = DEFAULT_ZERO_PATTERNS,
    count_patterns: Iterable[str] = (),
) -> list[PatternResult]:
    results = [
        PatternResult(pattern, count_lines(text, pattern), True)
        for pattern in zero_patterns
    ]
    results.extend(
        PatternResult(pattern, count_lines(text, pattern), False)
        for pattern in count_patterns
    )
    return results


def scan_log_file(
    logfile: Path,
    *,
    zero_patterns: Iterable[str] = DEFAULT_ZERO_PATTERNS,
    count_patterns: Iterable[str] = (),
) -> list[PatternResult]:
    with open_rejecting_symlink_read(logfile, errors="replace") as handle:
        return scan_text(
            handle.read(),
            zero_patterns=zero_patterns,
            count_patterns=count_patterns,
        )


def print_results(results: Iterable[PatternResult]) -> int:
    failed = 0
    for result in results:
        ok = not result.must_be_zero or result.count == 0
        if result.must_be_zero and not ok:
            failed += 1
            label = "FAIL"
        elif result.must_be_zero:
            label = "PASS"
        else:
            label = "COUNT"
        print(f"{label} {result.pattern}: {result.count}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Ignored E2E env file")
    parser.add_argument(
        "--zero",
        action="append",
        default=[],
        help="Additional case-insensitive pattern that must have zero matching lines",
    )
    parser.add_argument(
        "--count",
        action="append",
        default=[],
        help="Additional case-insensitive pattern to count without failing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, logfile = instance_paths(str(args.env), create=False)
    if not logfile.exists():
        print("FAIL log file: missing")
        return 1
    results = scan_log_file(
        logfile,
        zero_patterns=(*DEFAULT_ZERO_PATTERNS, *args.zero),
        count_patterns=args.count,
    )
    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
