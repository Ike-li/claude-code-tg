# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog style, and this project uses semantic
versioning once tagged releases begin.

## Unreleased

### Security

- Group chats are now default-deny. The bot only operates in a group whose chat
  id is listed in the new `ALLOWED_CHAT_IDS` setting; previously any authorized
  user could trigger a run in any group, streaming `bypassPermissions` output to
  all members. A global handler gate enforces this for messages, commands, and
  callbacks alike.
- Restored session ids from `status.json` are now UUID-validated before reaching
  the `claude --resume` argv.
- The output sanitizer strips ANSI/OSC terminal escape sequences and stray
  control characters, and redacts URL credentials, HTTP Basic-auth headers, and
  more credential-assignment formats. Exception text sent to Telegram and
  attacker-controlled attachment filenames are now sanitized.
- `tgcc doctor` now reports group/world-readable `.env` files (which hold the bot
  token) as a failure rather than a warning.

### Fixed

- The executor no longer leaks subprocesses or the stderr-drain task when a run
  is cancelled or the bot shuts down; a new shutdown hook reaps all live
  processes. Process eviction is guarded by identity so a queued follow-up run is
  not clobbered.
- An oversized (>1MB) stream-json line from Claude is now skipped instead of
  crashing the run.
- The blocking `git` branch lookup runs off the event loop, and the stderr drain
  buffer is bounded to avoid unbounded memory growth.

### Changed

- Loosened the optional `uvicorn` pin from `~=0.38.0` to `>=0.38,<1.0` so
  security and bugfix minors are allowed.

## 0.8.3 - 2026-06-05

### Added

- Published to PyPI: `uv tool install claude-code-tg` (or `pip install
  claude-code-tg`). Git installs remain available for the latest dev build.
- GitHub Actions release workflow that builds and publishes to PyPI via Trusted
  Publishing (OIDC) on `v*` tag pushes, with a tag/version consistency check.

### Changed

- README install instructions now lead with the PyPI package; demo image uses an
  absolute URL so it renders outside the GitHub repo.

## 0.8.2 - 2026-06-05

### Security

- Bump `starlette` from `0.50.0` to `>=1.0.1` (resolved to `1.2.1`) to address
  GHSA-86qp-5c8j-p5mr / CVE-2026-48710 (missing Host header validation that can
  poison `request.url.path` and bypass path-based security checks). starlette is
  only used by the optional, off-by-default Mini App console, and tgcc
  authenticates via Telegram initData HMAC rather than path-based checks, so the
  practical exposure was low.

## 0.8.1 - 2026-06-05

### Added

- `tgcc init` quick setup mode: prompts for only the three essentials (bot
  token, admin user id, project directory) and fills sane defaults for the rest.
  Use `tgcc init --full` for the previous prompt-everything flow.
- Grouped per-field comments in `.env.example` (required / common / attachments
  / advanced / mini-app sections).

### Changed

- The env-not-found error in `tgcc start`/`tgcc foreground` now points to
  `tgcc init` instead of only `.env.example`.
- Documentation cleanup: fixed version drift to `0.8.x`, deduplicated repeated
  command/permission/attachment tables into the User Guide as the single source
  of truth, moved contributor/agent notes under `docs/dev/`, and tidied the
  documentation index.

### Fixed

- Corrected the README `mypy` command to `uv run --extra dev mypy`.
- Added `xhigh` to the documented `CLAUDE_EFFORT` values.

## 0.8.0 - 2026-06-05

### Added

- Lightweight Telegram bridge for Claude Code CLI with per-chat sessions,
  `/resume`, `/model`, `/permissions`, `/stop`, status cards, copy buttons, and
  queued execution.
- Multi-instance `tgcc` CLI for `init`, `doctor`, `start`, `stop`, `restart`,
  `status`, `logs`, `foreground`, the `*-all` batch variants, and attachment
  pruning across one or more `.env` files.
- Telegram-native UI support for `sendChatAction`, ForceReply prompts, optional
  Draft Preview, and an optional private-chat Mini App console.
- Attachment handling modes for local paths, project-local copies, and explicit
  rejection, with retention cleanup and owner-only storage.
- Operator, user, security, support, compatibility, roadmap, E2E, maintainer,
  and contributor documentation for the `0.8.0` Alpha line.
- CI, packaging metadata, CODEOWNERS, issue templates, Code of Conduct,
  coverage reporting, mypy, Ruff, and build validation.

### Changed

- Split the original CLI and bot modules into focused config, parser, init,
  process, app, command, processing, input, and output modules.
- Moved runtime state, logs, env files, pid files, and attachment caches toward
  owner-only permissions with no-follow guards where the platform supports them.
- Sent Claude prompts through stdin instead of process argv to reduce local
  process-list exposure.
- Documented the Alpha security boundary more clearly: trusted Telegram users
  can drive Claude Code inside the configured project.
- Consolidated sprawling historical docs into shorter task-based guides and a
  single Telegram E2E runbook.

### Fixed

- Redacted Telegram Bot API tokens, encoded download tokens, and common secrets
  from logs and output paths used by diagnostics.
- Split long Telegram messages without introducing leading-space artifacts.
- Updated stopped status cards so `/stop` does not leave stale running state.
- Treated `tgcc logs -n 0` as no historical tail instead of printing the whole
  log.
- Hardened runtime metadata, pid, log, env, and attachment writes against
  symlink and replacement-race edge cases.
- Tightened Telegram callback parsing, command handling, Mini App malformed
  JSON responses, and action error reporting.

### Historical Note

`0.8.0` is the first tagged release (`v0.8.0`). This changelog summarizes the
work that led up to it instead of preserving every unreleased internal
checkpoint; git history remains the source for granular implementation details.
