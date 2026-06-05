"""Tests for Claude slash command probing and Telegram menu building."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_tg.command_menu import (
    build_claude_menu,
    build_runnable_claude_commands,
    load_or_probe_slash_commands,
    probe_slash_commands,
    read_cached_slash_commands,
    to_telegram_command_name,
    write_cached_slash_commands,
)


class TestToTelegramCommandName:
    def test_dashes_become_underscores(self) -> None:
        assert to_telegram_command_name("code-review") == "code_review"
        assert to_telegram_command_name("deep-research") == "deep_research"

    def test_lowercased(self) -> None:
        assert to_telegram_command_name("Verify") == "verify"

    def test_strips_and_collapses_invalid(self) -> None:
        assert to_telegram_command_name("  foo:bar baz  ") == "foo_bar_baz"

    def test_empty_returns_none(self) -> None:
        assert to_telegram_command_name("") is None
        assert to_telegram_command_name("---") is None

    def test_truncated_to_32(self) -> None:
        name = to_telegram_command_name("a" * 50)
        assert name is not None
        assert len(name) == 32


class TestBuildClaudeMenu:
    def test_keeps_custom_commands_and_skills(self) -> None:
        entries = build_claude_menu(["code-review", "verify", "my_custom"], set())
        mapping = {e.tg_name: e.claude_command for e in entries}
        assert mapping == {
            "code_review": "code-review",
            "verify": "verify",
            "my_custom": "my_custom",
        }

    def test_drops_interactive_builtins(self) -> None:
        entries = build_claude_menu(
            ["help", "model", "clear", "compact", "verify"], set()
        )
        assert [e.claude_command for e in entries] == ["verify"]

    def test_includes_plugin_commands_with_abbreviation(self) -> None:
        entries = build_claude_menu(
            ["oh-my-claudecode:autopilot", "foo:bar", "verify"], set()
        )
        mapping = {e.tg_name: e.claude_command for e in entries}
        assert mapping == {
            "omc_autopilot": "oh-my-claudecode:autopilot",
            "foo_bar": "foo:bar",
            "verify": "verify",
        }

    def test_drops_names_colliding_with_reserved(self) -> None:
        entries = build_claude_menu(["run", "status", "verify"], {"run", "status"})
        assert [e.claude_command for e in entries] == ["verify"]

    def test_dedupes_by_telegram_name(self) -> None:
        entries = build_claude_menu(["foo-bar", "foo_bar"], set())
        assert [e.claude_command for e in entries] == ["foo-bar"]

    def test_respects_limit(self) -> None:
        entries = build_claude_menu(["a", "b", "c", "d"], set(), limit=2)
        assert [e.claude_command for e in entries] == ["a", "b"]

    def test_description_references_original_command(self) -> None:
        (entry,) = build_claude_menu(["code-review"], set())
        assert "code-review" in entry.description


class TestBuildRunnableClaudeCommands:
    def test_keeps_only_runnable_original_command_names(self) -> None:
        commands = build_runnable_claude_commands(
            [
                "verify",
                "run",
                "help",
                "model",
                "code-review",
                "foo:bar",
                "verify",
                "  ",
            ],
            reserved_names={"run"},
        )

        assert commands == ["code-review", "foo:bar", "verify"]


class TestSlashCommandCache:
    def test_read_missing_cache_returns_none(self, tmp_path) -> None:
        assert read_cached_slash_commands(tmp_path / "missing.json") is None

    def test_write_and_read_cache(self, tmp_path) -> None:
        cache_file = tmp_path / "command-menu.json"

        write_cached_slash_commands(cache_file, ["verify", "help"])

        assert read_cached_slash_commands(cache_file) == ["verify", "help"]

    def test_read_cache_filters_non_string_entries(self, tmp_path) -> None:
        cache_file = tmp_path / "command-menu.json"
        cache_file.write_text(
            json.dumps({"slash_commands": ["verify", 123, None]}),
            encoding="utf-8",
        )

        assert read_cached_slash_commands(cache_file) == ["verify"]

    @pytest.mark.asyncio
    async def test_load_or_probe_uses_cache_without_probe(self, tmp_path) -> None:
        cache_file = tmp_path / "command-menu.json"
        cache_file.write_text(
            json.dumps({"slash_commands": ["verify"]}),
            encoding="utf-8",
        )

        with patch(
            "claude_code_tg.command_menu.probe_slash_commands",
            new_callable=AsyncMock,
        ) as probe:
            result = await load_or_probe_slash_commands("/tmp", cache_file)

        assert result == ["verify"]
        probe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_load_or_probe_refreshes_and_writes_cache(self, tmp_path) -> None:
        cache_file = tmp_path / "command-menu.json"
        cache_file.write_text(
            json.dumps({"slash_commands": ["old"]}),
            encoding="utf-8",
        )

        with patch(
            "claude_code_tg.command_menu.probe_slash_commands",
            new_callable=AsyncMock,
            return_value=["verify"],
        ) as probe:
            result = await load_or_probe_slash_commands(
                "/tmp",
                cache_file,
                refresh=True,
            )

        assert result == ["verify"]
        probe.assert_awaited_once_with("/tmp")
        assert read_cached_slash_commands(cache_file) == ["verify"]


class _FakeStdin:
    def __init__(self) -> None:
        self.closed = False
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None: ...

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    async def __aiter__(self):
        for line in self._lines:
            yield line


class _FakeProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines)
        self.returncode: int | None = None
        self.pid = 4242
        self.kill = MagicMock()

    async def wait(self) -> int:
        self.returncode = 0
        return 0


def _init_line(commands: list[str]) -> bytes:
    return (
        json.dumps(
            {"type": "system", "subtype": "init", "slash_commands": commands}
        ).encode()
        + b"\n"
    )


class TestProbeSlashCommands:
    @pytest.mark.asyncio
    async def test_reads_slash_commands_from_init_event(self) -> None:
        proc = _FakeProcess(
            [
                b'{"type":"system","subtype":"other"}\n',
                _init_line(["verify", "code-review"]),
                b'{"type":"result"}\n',
            ]
        )
        with (
            patch(
                "claude_code_tg.command_menu.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("claude_code_tg.command_menu.send_signal_to_process_tree"),
        ):
            result = await probe_slash_commands("/tmp")

        assert result == ["verify", "code-review"]
        assert proc.stdin.closed

    @pytest.mark.asyncio
    async def test_returns_empty_when_claude_missing(self) -> None:
        with patch(
            "claude_code_tg.command_menu.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            assert await probe_slash_commands("/tmp") == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_init_lacks_commands(self) -> None:
        proc = _FakeProcess(
            [b'{"type":"system","subtype":"init"}\n', b'{"type":"result"}\n']
        )
        with (
            patch(
                "claude_code_tg.command_menu.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ),
            patch("claude_code_tg.command_menu.send_signal_to_process_tree"),
        ):
            assert await probe_slash_commands("/tmp") == []
