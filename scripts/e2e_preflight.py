"""Run sanitized Telegram E2E environment preflight checks."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _bool_is_false(value: str | None) -> bool:
    return (value or "").strip().lower() in {"", "0", "false", "no", "off"}


def _configured_count(value: str | None) -> int:
    return len([part for part in (value or "").split(",") if part.strip()])


def check_env_exists(env_file: Path) -> CheckResult:
    return CheckResult(
        "env file", env_file.exists(), "found" if env_file.exists() else "missing"
    )


def check_env_permissions(env_file: Path) -> CheckResult:
    if os.name == "nt":
        return CheckResult(
            "env permissions",
            True,
            "skipped on non-POSIX platform",
            skipped=True,
        )
    try:
        mode = env_file.stat().st_mode & 0o777
    except OSError:
        return CheckResult("env permissions", False, "unreadable")
    ok = mode & 0o077 == 0
    return CheckResult(
        "env permissions",
        ok,
        "owner-only" if ok else f"mode is {mode:o}; run chmod 600",
    )


def _run_git(repo_root: Path, args: Sequence[str]) -> int:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode


def check_env_not_tracked_and_ignored(env_file: Path, repo_root: Path) -> CheckResult:
    env_resolved = env_file.resolve(strict=False)
    repo_resolved = repo_root.resolve(strict=False)
    if not _is_relative_to(env_resolved, repo_resolved):
        return CheckResult(
            "env git visibility",
            True,
            "outside repository",
        )

    rel = os.path.relpath(env_resolved, repo_resolved)
    if _run_git(repo_resolved, ["ls-files", "--error-unmatch", "--", rel]) == 0:
        return CheckResult("env git visibility", False, "tracked by git")
    if _run_git(repo_resolved, ["check-ignore", "-q", "--", rel]) == 0:
        return CheckResult("env git visibility", True, "ignored by git")
    return CheckResult("env git visibility", False, "not ignored by git")


def check_project_dir(values: dict[str, str], repo_root: Path) -> CheckResult:
    raw = values.get("CLAUDE_PROJECT_DIR", "").strip()
    if not raw:
        return CheckResult("CLAUDE_PROJECT_DIR", False, "not configured")
    project = Path(raw).expanduser().resolve(strict=False)
    if not project.exists():
        return CheckResult("CLAUDE_PROJECT_DIR", False, "does not exist")
    repo = repo_root.resolve(strict=False)
    if _is_relative_to(project, repo):
        return CheckResult("CLAUDE_PROJECT_DIR", False, "inside repository")
    return CheckResult("CLAUDE_PROJECT_DIR", True, "exists outside repository")


def check_required_values(values: dict[str, str]) -> list[CheckResult]:
    token_ok = bool(values.get("TELEGRAM_BOT_TOKEN", "").strip())
    admin_count = _configured_count(values.get("ADMIN_USER_IDS"))
    allowed_count = _configured_count(values.get("ALLOWED_USER_IDS"))
    return [
        CheckResult(
            "TELEGRAM_BOT_TOKEN",
            token_ok,
            "configured" if token_ok else "not configured",
        ),
        CheckResult(
            "ADMIN_USER_IDS",
            admin_count > 0,
            f"{admin_count} configured",
        ),
        CheckResult(
            "ALLOWED_USER_IDS",
            allowed_count > 0,
            f"{allowed_count} configured",
        ),
    ]


def check_cleanup_defaults(values: dict[str, str]) -> list[CheckResult]:
    draft_ok = _bool_is_false(values.get("TELEGRAM_DRAFT_PREVIEW"))
    mini_app_ok = _bool_is_false(values.get("TELEGRAM_MINI_APP_ENABLED"))
    public_url_ok = not values.get("TELEGRAM_MINI_APP_PUBLIC_URL", "").strip()
    attachment_mode = values.get("ATTACHMENT_MODE", "path").strip().lower() or "path"
    attachment_ok = attachment_mode == "path"
    return [
        CheckResult(
            "TELEGRAM_DRAFT_PREVIEW",
            draft_ok,
            "default-off" if draft_ok else "enabled",
        ),
        CheckResult(
            "TELEGRAM_MINI_APP_ENABLED",
            mini_app_ok,
            "default-off" if mini_app_ok else "enabled",
        ),
        CheckResult(
            "TELEGRAM_MINI_APP_PUBLIC_URL",
            public_url_ok,
            "empty" if public_url_ok else "configured",
        ),
        CheckResult(
            "ATTACHMENT_MODE",
            attachment_ok,
            "path" if attachment_ok else attachment_mode,
        ),
    ]


def run_preflight(
    env_file: Path,
    *,
    repo_root: Path,
    require_cleanup_defaults: bool = True,
) -> list[CheckResult]:
    results = [
        check_env_exists(env_file),
        check_env_permissions(env_file),
        check_env_not_tracked_and_ignored(env_file, repo_root),
    ]
    if not env_file.exists():
        return results
    values = load_env_file(env_file)
    results.extend(check_required_values(values))
    results.append(check_project_dir(values, repo_root))
    if require_cleanup_defaults:
        results.extend(check_cleanup_defaults(values))
    return results


def print_results(results: Iterable[CheckResult]) -> int:
    failed = 0
    for result in results:
        if result.skipped:
            label = "SKIP"
        elif result.ok:
            label = "PASS"
        else:
            label = "FAIL"
            failed += 1
        print(f"{label} {result.name}: {result.detail}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Ignored E2E env file")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used for git ignore and project-dir checks",
    )
    parser.add_argument(
        "--allow-active-experiments",
        action="store_true",
        help="Do not require Draft Preview, Mini App, and attachment mode cleanup defaults",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return print_results(
        run_preflight(
            args.env,
            repo_root=args.repo_root,
            require_cleanup_defaults=not args.allow_active_experiments,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
