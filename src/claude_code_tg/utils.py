"""Shared utilities for claude-code-tg."""

import logging
from pathlib import Path

from claude_code_tg.file_security import (
    open_rejecting_symlink_read,
    rejectable_symlink_path_component,
)

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a key=value dict. Skips comments and blank lines."""
    result: dict[str, str] = {}
    symlink = rejectable_symlink_path_component(env_path)
    if symlink:
        logger.warning(
            "Env path %s contains a symlink (%s); refusing to read",
            env_path,
            symlink,
        )
        return result
    if not env_path.exists():
        return result
    try:
        with open_rejecting_symlink_read(env_path) as f:
            lines = f.read().splitlines()
    except OSError as exc:
        logger.warning("Could not read env file %s: %s", env_path, exc)
        return result
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Remove surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def read_env_value(env_path: Path, key: str) -> str | None:
    """Read a single value from an env file by key."""
    config = parse_env_file(env_path)
    return config.get(key)


def parse_env_bool(value: str | None, default: bool = False) -> bool:
    """Parse common env-style boolean strings."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def parse_positive_ids(value: str) -> tuple[list[int], list[str]]:
    """Split a comma-separated string into positive ints and invalid items.

    An item is invalid if it is non-numeric or not strictly positive. Blank
    items are ignored. Order is preserved for both returned lists.
    """
    ids: list[int] = []
    invalid: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            parsed = int(item)
        except ValueError:
            invalid.append(item)
            continue
        if parsed <= 0:
            invalid.append(item)
            continue
        ids.append(parsed)
    return ids, invalid


def _format_uptime(seconds: int) -> str:
    """Format elapsed seconds as compact uptime text."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h{minutes}m"


def check_env_permissions(env_files: list[Path]) -> None:
    """Warn if env files are readable by group or others."""
    for env_file in env_files:
        symlink = rejectable_symlink_path_component(env_file)
        if symlink:
            logger.warning(
                "Env path %s contains a symlink (%s); expected a regular owner-only file",
                env_file,
                symlink,
            )
            continue
        if not env_file.exists():
            continue
        mode = env_file.stat().st_mode
        if mode & 0o077:
            logger.warning(
                "Env file %s has overly permissive mode %o (expected 0600)",
                env_file,
                mode & 0o777,
            )


def discover_env_files(scan_dir: Path = Path(".")) -> list[Path]:
    """Discover regular, non-symlinked *.env files in the scan directory."""
    if rejectable_symlink_path_component(scan_dir) or not scan_dir.exists():
        return []
    return sorted(
        env_file
        for env_file in scan_dir.glob("*.env")
        if not rejectable_symlink_path_component(env_file) and env_file.is_file()
    )
