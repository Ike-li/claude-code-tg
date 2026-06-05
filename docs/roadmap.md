# Roadmap

This roadmap keeps the `0.8.x` Alpha direction explicit. It is intentionally
small: `tgcc` should remain a local, self-hosted Telegram bridge for Claude Code
CLI rather than grow into a general AI bot platform.

## Near-Term Focus

1. Sanitized visual demo: keep the current sanitized static demo aligned;
   optional post-release screenshots or GIFs must stay
   sanitized and must not become a release-blocking placeholder.
2. Telegram run UI validation: manually smoke-test status cards, detail
   pagination/filtering, copy buttons, result actions, and queued callback
   notifications on real mobile Telegram clients.
3. Model and effort selection hardening: continue improving `CLAUDE_MODEL`,
   `CLAUDE_EFFORT`, `/model`, `/effort`, and coverage of Claude Code
   `--model`/`--effort` behavior.
4. Attachment retention automation hardening: continue improving
   `ATTACHMENT_RETENTION_DAYS` validation and logs.
5. Distribution: PyPI Trusted Publishing is live
   (`uv tool install claude-code-tg`) via a tag-triggered GitHub Actions release
   workflow; keep release notes, tags, and docs aligned on each version.

## Beta Exit Criteria

- At least one public release has been validated with the
  temporary BotFather token rotated or revoked.
- GitHub private vulnerability reporting is enabled and linked from issue
  intake, support, and security docs.
- The compatibility matrix has been validated on the documented Python versions
  and primary operating systems.
- Manual validation covers setup, `/start`, `/status`, prompt execution,
  permission mode changes, attachment handling, `/new`, `/stop`, and log
  redaction.
- The README, English README, support policy, and changelog remain aligned.

## Non-Goals For The Alpha Line

- Managed cloud hosting or a hosted control plane.
- Enterprise SSO, RBAC, audit logging, or compliance reporting.
- Telegram-side approval cards for each Claude Code tool call.
- Voice input, TTS, broad provider switching, or one-click Git publishing.
- Support for deployments that expose the bot to untrusted Telegram users.

## Decision Rules

- Prefer local, inspectable behavior over cloud services.
- Prefer explicit permission-mode visibility over silent convenience defaults.
- Prefer documentation and tests when changing setup, permissions, release, or
  support boundaries.
- Prefer small scoped features over platform expansion.
