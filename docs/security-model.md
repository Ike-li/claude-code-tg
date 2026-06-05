# Security Model

This document summarizes `tgcc` security boundaries. `SECURITY.md` is the
public reporting policy; this file is the maintainer-facing model for what the
project protects and where operator responsibility begins.

## Trust Boundaries

`tgcc` assumes the host machine and the operating-system account running the bot
are trusted infrastructure. Anyone with shell access to that account can inspect
project files, runtime state, logs, attachments, and Claude Code data.

Main boundaries:

- Telegram users are untrusted until listed in `ADMIN_USER_IDS` or
  `ALLOWED_USER_IDS`.
- Telegram groups share one chat-level Claude session and queue. Authorized
  participants can affect the shared conversation.
- Telegram Bot API, Telegram clients, and temporary Mini App tunnels are
  external services.
- Claude Code runs locally in `CLAUDE_PROJECT_DIR` with the configured
  permission mode.
- Project files, `.tgcc-attachments/`, and `~/.tgcc/` runtime state are local
  assets controlled by the host user.

## Protected Assets

- Telegram Bot tokens and temporary smoke-test tokens.
- Admin/allowed user ids, chat ids, and session ids.
- Prompts, Telegram messages, captions, attachment names, and local paths.
- Project source and generated files.
- Runtime state under `~/.tgcc/`: logs, pid files, metadata, `status.json`, and
  attachment caches.
- Project-local attachment copies under `.tgcc-attachments/`.
- Build and release artifacts.

## Controls

`tgcc` relies on several small controls rather than a cloud control plane:

- Telegram allowlists gate bot access.
- `.env`, instance directories, logs, pid files, status files, metadata, and
  attachment caches are owner-only where the platform supports it.
- File helpers avoid following user-controlled symlink path components for env,
  log, runtime metadata, pid, status, and attachment paths where possible.
- Prompts are sent to Claude through stdin instead of process argv.
- Logs and user-visible error output pass through best-effort redaction.
- Attachment handling is explicit:
  `ATTACHMENT_MODE=path|copy-to-project|reject`.
- `tgcc doctor` checks config, Claude CLI availability, project paths,
  attachment settings, runtime permissions, and risky defaults.
- Mini App requests must pass Telegram `initData` HMAC, `auth_date`, and tgcc
  allowlist checks; the frontend does not receive the Bot token.

## Known Limitations

These are not security guarantees:

- Authorized Telegram users can ask Claude Code to inspect or modify files that
  the configured Claude permissions allow.
- `bypassPermissions`, `dontAsk`, broad per-chat `/permissions` overrides, and
  `CLAUDE_SKIP_PERMISSIONS=true` are only appropriate for trusted users and
  trusted project directories.
- Log redaction is best effort. Review logs before sharing.
- Telegram stores messages according to Telegram's own product behavior.
- Claude Code may persist conversation or tool-use state outside `tgcc`.
- Local administrators or malware on the host can inspect process memory,
  files, network traffic, and child-process activity.

## Maintainer Review Triggers

Treat changes in these areas as security-boundary changes:

- authentication or allowlist logic
- Claude Code invocation, permission mode mapping, model selection, or effort
  selection
- prompt transport, logging, redaction, or status persistence
- attachment download, project-copy behavior, cleanup, or retention
- owner-only file creation, symlink guards, permission repair, or instance
  migration
- Mini App auth, public URL handling, or action authorization
- GitHub Actions permissions or release artifacts
- public docs that explain setup, security expectations, or disclosure flow

Security-boundary PRs should include focused tests, docs updates, and a fresh
`uv run python scripts/validate_local.py` run.
