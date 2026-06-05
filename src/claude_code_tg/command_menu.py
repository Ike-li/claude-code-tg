"""Probe Claude Code slash commands and build the Telegram command menu.

The bot drives Claude Code through ``claude -p`` (headless). Headless mode only
exposes a subset of slash commands: project/skill commands, plugin commands
(``/foo:bar``), and a few built-ins are dispatchable, while raw interactive
built-ins (``/help``, ``/model`` …) are not. Some high-value built-ins have
tgcc-owned Telegram wrappers, but dynamic probing still filters their raw Claude
entries. The authoritative list of what is actually available comes from the
``system`` ``init`` event emitted at the start of every ``stream-json`` session,
in its ``slash_commands`` field.

This module probes that list once and turns it into Telegram menu entries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import signal
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

from claude_code_tg.file_security import (
    open_rejecting_symlink_read,
    replace_owner_only_text,
)
from claude_code_tg.process_control import send_signal_to_process_tree

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 20
# Standalone cap for probed Claude entries; bot_app passes the exact remaining
# Telegram menu capacity after fixed bot commands are counted.
MAX_CLAUDE_MENU_COMMANDS = 90

# Built-in / interactive commands that exist in the init list but cannot be
# meaningfully driven through a one-shot ``claude -p`` call (they need a TTY,
# only mutate local interactive state, or are no-ops in a fresh headless turn).
# Anything NOT listed here passes through, so project-defined custom commands and
# skills in any instance are kept automatically.
INTERACTIVE_BUILTINS = frozenset(
    {
        "add-dir",
        "agents",
        "bug",
        "clear",
        "compact",
        "config",
        "context",
        "cost",
        "doctor",
        "exit",
        "export",
        "goal",
        "heapdump",
        "help",
        "hooks",
        "ide",
        "init",
        "insights",
        "install-github-app",
        "login",
        "logout",
        "mcp",
        "memory",
        "model",
        "output-style",
        "permissions",
        "pr-comments",
        "privacy-settings",
        "quit",
        "release-notes",
        "reload-skills",
        "resume",
        "run-skill-generator",
        "status",
        "statusline",
        "team-onboarding",
        "terminal-setup",
        "todos",
        "upgrade",
        "usage",
        "vim",
    }
)

_INVALID_TG_CHARS = re.compile(r"[^a-z0-9_]+")
# Shorten long plugin prefixes so namespaced menu names fit Telegram's 32 chars.
_PLUGIN_ABBREVIATIONS = {"oh-my-claudecode": "omc"}
# Minimal prompt so claude proceeds to emit the init event; the process is killed
# right after, so the model turn never really runs. Must be non-whitespace —
# claude treats a blank prompt as empty and exits before emitting init.
_PROBE_PROMPT = b"hi"


class ClaudeCommand(NamedTuple):
    """A Claude slash command exposed in the Telegram menu.

    ``tg_name`` is the Telegram-safe command name (used as the menu entry and the
    handler key); ``claude_command`` is the original name fed back to Claude.
    """

    tg_name: str
    description: str
    claude_command: str


def to_telegram_command_name(name: str) -> str | None:
    """Return a Telegram-safe command name (``[a-z0-9_]`` 1-32), or None.

    Telegram only accepts lowercase letters, digits and underscores, so e.g.
    ``code-review`` becomes ``code_review``.
    """
    collapsed = _INVALID_TG_CHARS.sub("_", name.strip().lower()).strip("_")
    if not collapsed:
        return None
    return collapsed[:32]


def _menu_name_for(name: str) -> str | None:
    """Telegram-safe menu name for a probed command, including plugin commands.

    Plugin commands ``plugin:cmd`` cannot keep the ``:`` (illegal in Telegram) and
    the ``oh-my-claudecode`` prefix is too long, so the plugin part is abbreviated
    and namespaced: ``oh-my-claudecode:autopilot`` -> ``omc_autopilot``,
    ``foo:bar`` -> ``foo_bar``. The namespace prefix also avoids collisions with
    bundled commands of the same short name.
    """
    if ":" in name:
        plugin, _, cmd = name.partition(":")
        abbrev = _PLUGIN_ABBREVIATIONS.get(plugin.strip().lower(), plugin)
        return to_telegram_command_name(f"{abbrev}_{cmd}")
    return to_telegram_command_name(name)


def build_claude_menu(
    probed: list[str],
    reserved_names: set[str],
    *,
    limit: int = MAX_CLAUDE_MENU_COMMANDS,
) -> list[ClaudeCommand]:
    """Filter probed slash commands into Telegram menu entries.

    Drops interactive built-ins, anything whose Telegram name collides with a
    reserved (bot control) command, and duplicates. Plugin commands (``foo:bar``)
    are kept with a namespaced name (see :func:`_menu_name_for`). Entries are
    sorted by Telegram name and capped at ``limit``.
    """
    entries: list[ClaudeCommand] = []
    used: set[str] = set(reserved_names)
    for name in probed:
        if not isinstance(name, str) or not name.strip():
            continue
        # Interactive built-ins are bare names; plugin commands (with ":") bypass.
        if ":" not in name and name.lower() in INTERACTIVE_BUILTINS:
            continue
        tg_name = _menu_name_for(name)
        if tg_name is None or tg_name in used:
            continue
        used.add(tg_name)
        entries.append(
            ClaudeCommand(
                tg_name=tg_name,
                description=f"Claude 命令 /{name}",
                claude_command=name,
            )
        )
    entries.sort(key=lambda entry: entry.tg_name)
    if len(entries) > limit:
        logger.warning(
            "Claude command menu truncated to %d of %d entries", limit, len(entries)
        )
        entries = entries[:limit]
    return entries


def build_runnable_claude_commands(
    probed: list[str],
    reserved_names: set[str] | None = None,
) -> list[str]:
    """Return slash command names that can be shown as ``/run`` candidates."""
    commands: list[str] = []
    used: set[str] = set()
    reserved = {name.lower() for name in reserved_names or set()}
    for name in probed:
        if not isinstance(name, str):
            continue
        command = name.strip()
        if not command:
            continue
        if ":" not in command and command.lower() in INTERACTIVE_BUILTINS:
            continue
        if ":" not in command and command.lower() in reserved:
            continue
        if command in used:
            continue
        used.add(command)
        commands.append(command)
    commands.sort()
    return commands


def read_cached_slash_commands(cache_file: Path | None) -> list[str] | None:
    if cache_file is None or not cache_file.exists():
        return None
    try:
        with open_rejecting_symlink_read(cache_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    raw = data.get("slash_commands") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    return [command for command in raw if isinstance(command, str)]


def write_cached_slash_commands(
    cache_file: Path | None,
    commands: list[str],
) -> None:
    if cache_file is None:
        return
    payload = {
        "version": 1,
        "slash_commands": commands,
    }
    try:
        replace_owner_only_text(cache_file, json.dumps(payload, ensure_ascii=False))
    except OSError as exc:
        logger.warning("Could not write Claude command cache: %s", exc)


async def load_or_probe_slash_commands(
    project_dir: str,
    cache_file: Path | None,
    *,
    refresh: bool = False,
) -> list[str]:
    if not refresh:
        cached = read_cached_slash_commands(cache_file)
        if cached is not None:
            return cached
    probed = await probe_slash_commands(project_dir)
    write_cached_slash_commands(cache_file, probed)
    return probed


def _terminate(process: asyncio.subprocess.Process) -> None:
    """Best-effort kill of the probe process and its children."""
    if process.returncode is not None:
        return
    pid = getattr(process, "pid", None)
    if pid:
        with suppress(ProcessLookupError, OSError):
            send_signal_to_process_tree(pid, signal.SIGKILL)
            return
    with suppress(ProcessLookupError):
        process.kill()


async def probe_slash_commands(
    project_dir: str,
    *,
    timeout: int = PROBE_TIMEOUT_SECONDS,
) -> list[str]:
    """Return the slash commands Claude Code exposes for ``project_dir``.

    Runs ``claude -p`` once, reads the ``system``/``init`` event's
    ``slash_commands`` field, then kills the process. Never raises: any failure
    (claude missing, not authenticated, timeout, bad JSON) yields an empty list.
    """
    cmd = [
        "claude",
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=1024 * 1024,
            cwd=project_dir,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Slash command probe could not start claude: %s", exc)
        return []

    if process.stdin is not None:
        with suppress(BrokenPipeError, ConnectionResetError, OSError):
            process.stdin.write(_PROBE_PROMPT)
            await process.stdin.drain()
            process.stdin.close()

    commands: list[str] = []
    try:
        async with asyncio.timeout(timeout):
            assert process.stdout is not None
            async for line in process.stdout:
                decoded = line.decode(errors="replace").strip()
                if not decoded:
                    continue
                try:
                    event = json.loads(decoded)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    raw = event.get("slash_commands")
                    if isinstance(raw, list):
                        commands = [c for c in raw if isinstance(c, str)]
                    break
    except (TimeoutError, asyncio.CancelledError):
        logger.warning("Slash command probe timed out after %ss", timeout)
    except Exception:  # never let probing break bot startup
        logger.exception("Slash command probe failed")
    finally:
        _terminate(process)
        with suppress(Exception):
            await process.wait()

    return commands
