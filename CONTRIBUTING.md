# Contributing

Thanks for helping improve `tgcc`.

English-speaking contributors can start with [README.en.md](README.en.md) and
the [documentation index](docs/index.md). Architecture and module boundaries
are summarized in [docs/architecture.md](docs/architecture.md).

## Product Direction

`tgcc` is a lightweight, Python-first, self-hosted manager for Claude Code CLI
over Telegram. Prefer changes that improve reliable local operation,
multi-project management, clear safety defaults, simple maintenance, or focused
test coverage.

Avoid broad feature expansion that turns tgcc into a general AI bot platform
unless it preserves the self-hosted shape and trusted-user security model.

## First-Time Path

- Start with issues labeled `good first issue` or `help wanted`.
- Keep the first PR narrow and link the issue or acceptance check it closes.
- For behavior changes, include a small reproduction or smoke step a maintainer
  can rerun.
- Keep suspected vulnerabilities out of public issues. Use
  [SECURITY.md](SECURITY.md) for private reporting.

## Repository Map

- Source lives in `src/claude_code_tg/`.
- Tests live in `tests/` and mirror source modules with `test_*.py` files.
- User and maintainer docs live in `docs/`; assets live in `docs/assets/`.
- Helper scripts live in `scripts/`.
- Ownership-sensitive areas are listed in [.github/CODEOWNERS](.github/CODEOWNERS).

## Development

Install dev dependencies and run the full local gate:

```bash
uv sync --extra dev
uv run python scripts/validate_local.py
```

Use focused checks while iterating:

```bash
uv run pytest
uv run pytest tests/test_bot.py
uv run ruff check .
uv run --extra dev mypy
uv run ruff format --check .
uv build
```

The full validation wrapper runs pytest with coverage, Ruff lint, mypy, Ruff
format check, and package build. CI runs the same categories and uploads
coverage XML for review.

## Validation By Change Type

Run the narrowest check that proves the change while iterating, then run
`uv run python scripts/validate_local.py` before requesting review.

| Change type | Focused checks |
| --- | --- |
| CLI, env parsing, process lifecycle | Matching `tests/test_cli_*.py` module |
| Telegram bot behavior, command replies, UI text | `tests/test_bot*.py` and message-output tests |
| Attachments, logs, local file safety | Attachment, file-security, doctor, and sanitizer tests |
| Mini App or web console | Mini App tests plus relevant bot state tests |
| Docs, templates, release notes, community files | Full validation wrapper |
| Release, CI, packaging | `uv build` plus full validation wrapper |
| Security-sensitive behavior | Focused regression and maintainer review |

If a change crosses rows, run the checks for every affected area.

## Pull Requests

- Keep changes small and scoped.
- Update docs when behavior, configuration, or operator workflow changes.
- Add or update tests for user-visible behavior.
- Run `uv run python scripts/validate_local.py` before submitting review-ready
  changes.
- Do not commit `.env`, tokens, logs, attachment caches, Claude transcripts, or
  local runtime state.
- Do not post Telegram tokens, private chat content, local paths, unsanitized
  logs, exploit details, or conduct incident details in public.

## Community And Maintainers

Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) in issues, discussions, and pull
requests. Maintainer authority, release-owner duties, and maintainer-only
actions are documented in [MAINTAINERS.md](MAINTAINERS.md).
