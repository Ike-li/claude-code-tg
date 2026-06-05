# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog style, and this project uses semantic
versioning once tagged releases begin.

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
