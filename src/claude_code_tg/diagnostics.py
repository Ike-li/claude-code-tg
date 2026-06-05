"""Local configuration diagnostics for tgcc."""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from claude_code_tg.attachments import (
    PROJECT_ATTACHMENT_DIRNAME,
    normalize_attachment_mode,
    normalize_attachment_retention_days,
)
from claude_code_tg.executor import (
    EFFORT_LEVELS,
    normalize_effort,
    normalize_model,
    normalize_permission_mode,
)
from claude_code_tg.file_security import (
    rejectable_symlink_path_component,
    set_owner_only_dir,
    set_owner_only_file,
)
from claude_code_tg.instance_store import instance_dir
from claude_code_tg.utils import parse_env_bool, parse_env_file, parse_positive_ids

RUNTIME_PERMISSION_FILENAMES = ("tgcc.log", "tgcc.pid", "status.json", "instance.json")
INSTANCE_ATTACHMENT_DIRNAME = "attachments"
_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


@dataclass(frozen=True)
class Diagnostic:
    name: str
    status: str
    detail: str

    @property
    def is_failed(self) -> bool:
        return self.status == "fail"

    @property
    def is_warning(self) -> bool:
        return self.status == "warn"


def _ok(name: str, detail: str) -> Diagnostic:
    return Diagnostic(name, "ok", detail)


def _warn(name: str, detail: str) -> Diagnostic:
    return Diagnostic(name, "warn", detail)


def _fail(name: str, detail: str) -> Diagnostic:
    return Diagnostic(name, "fail", detail)


def _check_env_permissions(env_file: Path) -> Diagnostic:
    if os.name == "nt":
        return _warn("Env permissions", "not checked on Windows")
    symlink = rejectable_symlink_path_component(env_file)
    if symlink:
        return _warn("Env permissions", f"{symlink} is a symlink in env path")
    try:
        mode = stat.S_IMODE(env_file.stat().st_mode)
    except OSError as exc:
        return _warn("Env permissions", f"could not inspect mode: {exc}")
    if mode & 0o077:
        return _warn(
            "Env permissions",
            f"mode is {mode:o}; run `chmod 600 {env_file}` before sharing logs",
        )
    return _ok("Env permissions", f"mode is {mode:o}")


def _owner_only_problem(path: Path, expected_mode: int) -> str | None:
    symlink = rejectable_symlink_path_component(path)
    if symlink:
        return f"{path}: {symlink} is a symlink in an owner-only path"
    try:
        path_info = path.lstat()
    except OSError as exc:
        return f"{path}: could not inspect mode ({exc})"
    type_problem = _owner_only_type_problem(path, expected_mode, path_info)
    if type_problem:
        return type_problem
    mode = stat.S_IMODE(path_info.st_mode)
    if mode & 0o077:
        return f"{path}: mode is {mode:o}, expected {expected_mode:o}"
    return None


def _owner_only_type_problem(
    path: Path, expected_mode: int, path_info: os.stat_result
) -> str | None:
    if expected_mode == 0o700 and not stat.S_ISDIR(path_info.st_mode):
        return f"{path}: expected directory for owner-only runtime state"
    if expected_mode == 0o600 and not stat.S_ISREG(path_info.st_mode):
        return f"{path}: expected regular file for owner-only runtime state"
    return None


def _owner_only_tree_targets(root: Path) -> list[tuple[Path, int]]:
    targets: list[tuple[Path, int]] = []
    if not root.exists() and not root.is_symlink():
        return targets
    targets.append((root, 0o700))
    if rejectable_symlink_path_component(root):
        return targets

    for path in root.rglob("*"):
        try:
            path_mode = path.lstat().st_mode
        except OSError:
            targets.append((path, 0o600))
            continue
        expected_mode = 0o700 if stat.S_ISDIR(path_mode) else 0o600
        targets.append((path, expected_mode))
    return targets


def _project_attachment_root(config: dict[str, str]) -> Path | None:
    value = config.get("CLAUDE_PROJECT_DIR", "").strip()
    if not value:
        return None
    project_dir = Path(value).expanduser()
    if not project_dir.is_absolute():
        project_dir = project_dir.resolve(strict=False)
    return project_dir / PROJECT_ATTACHMENT_DIRNAME


def _runtime_permission_targets(
    env_file: Path, config: dict[str, str] | None = None
) -> list[tuple[Path, int]]:
    targets: list[tuple[Path, int]] = []
    instance_dirs = [
        instance_dir(str(env_file), legacy=False),
        instance_dir(str(env_file), legacy=True),
    ]
    seen: set[Path] = set()
    for root in instance_dirs:
        if root in seen:
            continue
        seen.add(root)
        if not root.exists() and not root.is_symlink():
            continue
        targets.append((root, 0o700))
        if rejectable_symlink_path_component(root):
            continue
        for filename in RUNTIME_PERMISSION_FILENAMES:
            path = root / filename
            if path.exists() or path.is_symlink():
                targets.append((path, 0o600))
        targets.extend(_owner_only_tree_targets(root / INSTANCE_ATTACHMENT_DIRNAME))
    if config:
        project_attachment_root = _project_attachment_root(config)
        if project_attachment_root is not None:
            targets.extend(_owner_only_tree_targets(project_attachment_root))
    return targets


def _check_runtime_permissions(
    env_file: Path, config: dict[str, str] | None = None
) -> Diagnostic:
    if os.name == "nt":
        return _warn("Runtime permissions", "not checked on Windows")

    problems: list[str] = []
    targets = _runtime_permission_targets(env_file, config)
    for path, expected_mode in targets:
        problem = _owner_only_problem(path, expected_mode)
        if problem:
            problems.append(problem)

    if problems:
        return _warn("Runtime permissions", "; ".join(problems))
    if not targets:
        return _ok("Runtime permissions", "no local runtime files yet")
    return _ok(
        "Runtime permissions",
        "instance directory, runtime files, and attachment caches are owner-only",
    )


def fix_local_permissions(env_file: Path) -> Diagnostic:
    """Repair local env/runtime file modes where chmod is supported."""
    env_file = env_file.expanduser()
    if os.name == "nt":
        return _warn("Permission repair", "not supported on Windows")
    if not env_file.exists():
        return _fail("Permission repair", f"env file missing: {env_file}")

    fixed = 0
    already_ok = 0
    skipped_symlinks = 0
    errors: list[str] = []
    config = parse_env_file(env_file)
    targets = [(env_file, 0o600), *_runtime_permission_targets(env_file, config)]
    for path, expected_mode in targets:
        try:
            if rejectable_symlink_path_component(path):
                skipped_symlinks += 1
                continue
            path_info = path.lstat()
            type_problem = _owner_only_type_problem(path, expected_mode, path_info)
            if type_problem:
                errors.append(type_problem)
                continue
            current_mode = stat.S_IMODE(path_info.st_mode)
            if current_mode == expected_mode:
                already_ok += 1
                continue
            if expected_mode == 0o700:
                repaired = set_owner_only_dir(path)
            else:
                repaired = set_owner_only_file(path)
            if not repaired:
                raise OSError("could not set owner-only mode")
            fixed += 1
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    detail = (
        f"fixed {fixed} path(s); {already_ok} already owner-only; "
        f"{skipped_symlinks} symlink(s) skipped"
    )
    if errors:
        return _warn("Permission repair", f"{detail}; errors: {'; '.join(errors)}")
    return _ok("Permission repair", detail)


def _check_required_value(config: dict[str, str], key: str) -> Diagnostic:
    if config.get(key):
        return _ok(key, "configured")
    return _fail(key, "missing")


def _check_id_list(config: dict[str, str], key: str, *, required: bool) -> Diagnostic:
    value = config.get(key, "")
    if not value.strip():
        if required:
            return _fail(key, "missing")
        return _ok(key, "empty; only admins are allowed")
    ids, invalid = parse_positive_ids(value)
    if invalid:
        return _fail(key, "contains non-positive or non-numeric id(s)")
    if required and not ids:
        return _fail(key, "missing")
    return _ok(key, f"{len(ids)} id(s) configured")


def _check_project_dir(config: dict[str, str], env_file: Path) -> Diagnostic:
    value = config.get("CLAUDE_PROJECT_DIR", "").strip()
    if not value:
        return _warn(
            "CLAUDE_PROJECT_DIR",
            "not set; server will default to the current working directory",
        )
    project_dir = Path(value).expanduser()
    if not project_dir.is_absolute():
        project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        return _fail("CLAUDE_PROJECT_DIR", f"does not exist: {project_dir}")
    return _ok("CLAUDE_PROJECT_DIR", f"exists: {project_dir}")


def _check_int(
    config: dict[str, str], key: str, *, default: str, minimum: int | None = None
) -> Diagnostic:
    raw_value = config.get(key, default).strip()
    try:
        value = int(raw_value)
    except ValueError:
        return _fail(key, f"must be an integer, got {raw_value!r}")
    if minimum is not None and value < minimum:
        return _warn(key, f"{value} will be normalized to {minimum}")
    return _ok(key, f"{value}")


def _check_permission_mode(config: dict[str, str]) -> Diagnostic:
    raw_value = config.get("CLAUDE_PERMISSION_MODE")
    try:
        mode = normalize_permission_mode(raw_value)
    except ValueError:
        return _fail(
            "CLAUDE_PERMISSION_MODE",
            "must be one of default, acceptEdits, plan, auto, dontAsk, bypassPermissions",
        )
    return _ok("CLAUDE_PERMISSION_MODE", mode or "default")


def _check_model(config: dict[str, str]) -> Diagnostic:
    raw_value = config.get("CLAUDE_MODEL")
    try:
        model = normalize_model(raw_value)
    except ValueError:
        return _fail(
            "CLAUDE_MODEL",
            "must be a Claude Code model alias or full model name without whitespace or a leading hyphen",
        )
    return _ok("CLAUDE_MODEL", model or "claude-default")


def _check_effort(config: dict[str, str]) -> Diagnostic:
    raw_value = config.get("CLAUDE_EFFORT")
    try:
        effort = normalize_effort(raw_value)
    except ValueError:
        return _fail("CLAUDE_EFFORT", f"must be one of {', '.join(EFFORT_LEVELS)}")
    return _ok("CLAUDE_EFFORT", effort or "claude-default")


def _check_attachment_mode(config: dict[str, str]) -> Diagnostic:
    raw_value = config.get("ATTACHMENT_MODE")
    try:
        mode = normalize_attachment_mode(raw_value)
    except ValueError:
        return _fail("ATTACHMENT_MODE", "must be one of copy-to-project, path, reject")
    return _ok("ATTACHMENT_MODE", mode)


def _check_attachment_retention_days(config: dict[str, str]) -> Diagnostic:
    raw_value = config.get("ATTACHMENT_RETENTION_DAYS")
    try:
        days = normalize_attachment_retention_days(raw_value)
    except ValueError:
        return _fail(
            "ATTACHMENT_RETENTION_DAYS",
            "must be a non-negative number of days, or empty/0 to disable",
        )
    if days is None:
        return _ok("ATTACHMENT_RETENTION_DAYS", "disabled")
    return _ok("ATTACHMENT_RETENTION_DAYS", f"{days:g} day(s)")


def _check_skip_permissions(config: dict[str, str]) -> Diagnostic:
    enabled = parse_env_bool(config.get("CLAUDE_SKIP_PERMISSIONS"), default=False)
    if enabled:
        return _warn(
            "CLAUDE_SKIP_PERMISSIONS",
            "true; use only in trusted project directories",
        )
    return _ok("CLAUDE_SKIP_PERMISSIONS", "false")


def _check_bool(config: dict[str, str], key: str, *, default: bool) -> Diagnostic:
    raw_value = config.get(key)
    if raw_value is None or not raw_value.strip():
        return _ok(key, str(default).lower())
    normalized = raw_value.strip().lower()
    if normalized not in _TRUE_VALUES | _FALSE_VALUES:
        return _warn(key, f"invalid value {raw_value!r}; server will use default")
    return _ok(key, str(normalized in _TRUE_VALUES).lower())


def _check_mini_app(config: dict[str, str]) -> list[Diagnostic]:
    enabled = parse_env_bool(config.get("TELEGRAM_MINI_APP_ENABLED"), default=False)
    diagnostics = [
        _check_bool(config, "TELEGRAM_MINI_APP_ENABLED", default=False),
    ]
    public_url = config.get("TELEGRAM_MINI_APP_PUBLIC_URL", "").strip()
    if enabled:
        parsed = urlparse(public_url)
        if parsed.scheme != "https" or not parsed.netloc:
            diagnostics.append(
                _fail(
                    "TELEGRAM_MINI_APP_PUBLIC_URL",
                    "must be an HTTPS URL when Mini App is enabled",
                )
            )
        else:
            diagnostics.append(_ok("TELEGRAM_MINI_APP_PUBLIC_URL", public_url))
    else:
        diagnostics.append(
            _ok("TELEGRAM_MINI_APP_PUBLIC_URL", public_url or "not configured")
        )
    host = config.get("TELEGRAM_MINI_APP_HOST", "127.0.0.1").strip()
    diagnostics.append(
        _ok("TELEGRAM_MINI_APP_HOST", host)
        if host
        else _fail("TELEGRAM_MINI_APP_HOST", "must not be empty")
    )
    raw_port = config.get("TELEGRAM_MINI_APP_PORT", "8787").strip()
    try:
        port = int(raw_port)
    except ValueError:
        diagnostics.append(_fail("TELEGRAM_MINI_APP_PORT", "must be an integer"))
    else:
        if not 1 <= port <= 65535:
            diagnostics.append(
                _fail("TELEGRAM_MINI_APP_PORT", "must be between 1 and 65535")
            )
        else:
            diagnostics.append(_ok("TELEGRAM_MINI_APP_PORT", str(port)))
    menu_text = config.get("TELEGRAM_MINI_APP_MENU_TEXT", "tgcc").strip()
    diagnostics.append(
        _ok("TELEGRAM_MINI_APP_MENU_TEXT", menu_text)
        if menu_text
        else _fail("TELEGRAM_MINI_APP_MENU_TEXT", "must not be empty")
    )
    return diagnostics


def _check_claude_cli() -> Diagnostic:
    claude = shutil.which("claude")
    if not claude:
        # FAIL, not WARN: `tgcc start` hard-fails without the CLI, so doctor
        # must agree on severity instead of reporting a passable run.
        return _fail(
            "Claude Code CLI",
            "not found on PATH; install and authenticate before `tgcc start`",
        )
    return _ok("Claude Code CLI", f"found at {claude}")


def run_doctor(env_file: Path) -> list[Diagnostic]:
    """Inspect local tgcc configuration without contacting Telegram or Claude."""
    env_file = env_file.expanduser()
    diagnostics: list[Diagnostic] = []
    if not env_file.exists():
        diagnostics.append(_fail("Env file", f"missing: {env_file}"))
        diagnostics.append(_check_claude_cli())
        return diagnostics

    diagnostics.append(_ok("Env file", f"found: {env_file}"))
    diagnostics.append(_check_env_permissions(env_file))
    config = parse_env_file(env_file)
    diagnostics.append(_check_runtime_permissions(env_file, config))
    diagnostics.append(_check_required_value(config, "TELEGRAM_BOT_TOKEN"))
    diagnostics.append(_check_id_list(config, "ADMIN_USER_IDS", required=True))
    diagnostics.append(_check_id_list(config, "ALLOWED_USER_IDS", required=False))
    diagnostics.append(_check_project_dir(config, env_file))
    diagnostics.append(_check_int(config, "CLAUDE_TIMEOUT", default="300"))
    diagnostics.append(_check_int(config, "QUEUE_MAX_SIZE", default="3", minimum=1))
    diagnostics.append(_check_int(config, "ATTACHMENT_MAX_MB", default="20", minimum=1))
    diagnostics.append(_check_permission_mode(config))
    diagnostics.append(_check_model(config))
    diagnostics.append(_check_effort(config))
    diagnostics.append(_check_bool(config, "CLAUDE_CLI_RESUME_COMPAT", default=False))
    diagnostics.append(_check_attachment_mode(config))
    diagnostics.append(_check_attachment_retention_days(config))
    diagnostics.append(_check_skip_permissions(config))
    diagnostics.append(_check_bool(config, "LOG_INTERACTIONS", default=False))
    diagnostics.append(_check_bool(config, "CLAUDE_COMMAND_MENU", default=False))
    diagnostics.append(_check_bool(config, "TELEGRAM_DRAFT_PREVIEW", default=False))
    diagnostics.extend(_check_mini_app(config))
    diagnostics.append(_check_claude_cli())
    return diagnostics


def render_doctor_report(diagnostics: list[Diagnostic]) -> str:
    lines = ["tgcc doctor", ""]
    for diagnostic in diagnostics:
        label = diagnostic.status.upper()
        lines.append(f"{label:<4} {diagnostic.name}: {diagnostic.detail}")

    ok, warnings, failed = doctor_summary(diagnostics)
    lines.extend(
        [
            "",
            f"Summary: {ok} ok, {warnings} warning(s), {failed} failure(s).",
        ]
    )
    return "\n".join(lines)


def doctor_summary(diagnostics: list[Diagnostic]) -> tuple[int, int, int]:
    failed = sum(diagnostic.is_failed for diagnostic in diagnostics)
    warnings = sum(diagnostic.is_warning for diagnostic in diagnostics)
    ok = len(diagnostics) - failed - warnings
    return ok, warnings, failed


def render_doctor_json(diagnostics: list[Diagnostic]) -> str:
    ok, warnings, failed = doctor_summary(diagnostics)
    payload = {
        "summary": {
            "ok": ok,
            "warnings": warnings,
            "failures": failed,
        },
        "diagnostics": [
            {
                "name": diagnostic.name,
                "status": diagnostic.status,
                "detail": diagnostic.detail,
            }
            for diagnostic in diagnostics
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def doctor_exit_code(diagnostics: list[Diagnostic], *, strict: bool = False) -> int:
    if any(diagnostic.is_failed for diagnostic in diagnostics):
        return 1
    if strict and any(diagnostic.is_warning for diagnostic in diagnostics):
        return 1
    return 0


__all__ = [
    "Diagnostic",
    "doctor_exit_code",
    "doctor_summary",
    "fix_local_permissions",
    "render_doctor_json",
    "render_doctor_report",
    "run_doctor",
]
