# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11+ package for bridging Telegram chats to the Claude Code CLI.
Source lives in `src/claude_code_tg/`; the main areas are bot wiring
(`bot.py`, `bot_app.py`, `bot_commands.py`), CLI/config (`cli.py`, `config.py`),
Claude execution (`executor.py`), sessions (`sessions.py`, `claude_sessions.py`),
attachments, diagnostics, and file-security helpers. Tests live in `tests/` and
mirror source modules with `test_*.py` files. User and maintainer docs live in
`docs/`; assets are under `docs/assets/`. Local helper scripts live in `scripts/`.

## Build, Test, and Development Commands

- `uv run python scripts/validate_local.py` runs the full local gate: pytest with
  coverage, Ruff lint, mypy, Ruff format check, and package build.
- `uv run pytest` runs the test suite. Use paths for focused runs, for example
  `uv run pytest tests/test_bot.py`.
- `uv run ruff check .` checks linting and import ordering.
- `uv run --extra dev mypy` type-checks `src/claude_code_tg`.
- `uv build` builds the sdist and wheel.
- `uv run tgcc --help` inspects the installed CLI entry point locally.

## Session Handoff

When opening a fresh maintainer or agent session, read `docs/project-memory.md`
first, then run `git log -2 --oneline` before making assumptions about current
state. For Telegram E2E work, also read `docs/e2e/telegram-e2e.md` and
`docs/e2e/telegram-e2e-findings.md` before starting a real-client run.

## Documentation Maintenance

Use `docs/index.md` as the document map before adding or moving docs. Keep
`README.md` as the Chinese landing page, `README.en.md` as the short English
entry point, `docs/quickstart.md` as the shortest first-run path, and
`docs/user-guide.md` as the source of truth for day-to-day Telegram behavior.
Prefer linking to the specific owner document over repeating setup, security,
or E2E details in multiple files.

Do not add new run-specific Telegram E2E docs for ordinary test passes; update
`docs/e2e/telegram-e2e.md` for procedure changes and
`docs/e2e/telegram-e2e-findings.md` for compact closure notes. Use
`docs/project-memory.md` only for current handoff state, not long-lived user
documentation.

## Coding Style & Naming Conventions

Use 4-space indentation, type annotations for public/internal boundaries, and
clear `snake_case` names for modules, functions, variables, and tests. Keep code
small and explicit; prefer existing helpers for sessions, file safety, output
pagination, and command parsing. Ruff controls formatting-adjacent lint rules
and import ordering; do not hand-format around it.

## Testing Guidelines

Tests use `pytest`, `pytest-asyncio`, and `pytest-cov`; coverage must stay at or
above 85%. Name tests `test_<behavior>` and group related cases in `Test...`
classes. Use `AsyncMock`/fixtures instead of real Telegram network calls. Mark
real subprocess integration tests with `@pytest.mark.slow` when needed.

## Telegram E2E Notes

Use a dedicated test bot, ignored env file, throwaway project directory, and
real Telegram client for end-to-end Telegram validation. Do not write tokens,
numeric Telegram IDs, full session IDs, tunnel URLs, private logs, or attachment
caches into docs or commits. Avoid direct `getUpdates` while polling is active;
it conflicts with the running bot and pollutes logs.

E2E local artifacts have fixed homes: keep test env files such as
`cctg_test.env` at the repository root where `*.env` ignores them, keep
temporary Mini App HTTPS tunnel URLs only in that ignored env file while active,
keep the throwaway Claude project outside this repository via
`CLAUDE_PROJECT_DIR`, and rely on `$HOME/.tgcc/` for runtime state/logs. Telegram
test groups and BotFather settings live in Telegram itself, not in git.

Telegram E2E procedure and historical closure status are captured under
`docs/e2e/`. Notable lessons:
Computer Use is useful for Telegram buttons, ForceReply, and Mini App menu
checks, but it uses the user's active Mac pointer, keyboard, and focused
window; it is not an isolated second keyboard/mouse. Telegram Desktop attachment
preview and replying to an older bot message are fragile to automate. Natural
non-command group `@bot` mentions require BotFather privacy to be disabled;
slash commands addressed to the bot work with privacy enabled. Real Mini App
menu testing needs a temporary HTTPS tunnel and cleanup of both default and
chat-specific menu buttons; use
`uv run python scripts/e2e_reset_telegram_menu.py --env cctg_test.env` for the
cleanup step. Use `uv run python scripts/e2e_log_scan.py --env cctg_test.env`
for sanitized final log scans instead of pasting raw logs.
Start E2E runs with `uv run python scripts/e2e_preflight.py --env cctg_test.env`
to verify the ignored env file, owner-only permissions, outside-repo project,
and cleanup defaults without printing secrets. Then run
`uv run python scripts/e2e_prepare_assets.py --env cctg_test.env` to create
synthetic upload files and copyable prompts under the throwaway project instead
of using private local files. For macOS Telegram Desktop button-heavy batches,
run `uv run python scripts/e2e_macos_click.py --preflight`; if it passes, use
that helper with `--dry-run` first to click Telegram window-relative coordinates
when Computer Use coordinate clicks are unreliable.

## Commit & Pull Request Guidelines

Recent history uses short imperative subjects, sometimes with conventional
prefixes such as `feat:`. Keep commits focused, for example `feat: add command
cache` or `Fix session restore edge case`. PRs should include a concise summary,
validation commands run, linked issues when relevant, and any security/config
impact. Include screenshots only for Telegram UX changes where visual behavior
matters.

## Security & Configuration Tips

Never commit real bot tokens, chat IDs, `.env` files, runtime logs, or attachment
caches. Prefer `.env.example` for defaults and `tgcc doctor --env <file>` for
operator checks. Be conservative with `CLAUDE_PERMISSION_MODE`,
`CLAUDE_SKIP_PERMISSIONS`, and attachment modes; document risk changes clearly.
