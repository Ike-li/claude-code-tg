# Support

`tgcc` is a lightweight, self-hosted bridge for Telegram and Claude Code CLI.
Support is focused on local setup, multi-instance operation, and safe
trusted-user deployments.

## Before Asking

- Read [README.md](README.md) or [README.en.md](README.en.md).
- For first-run setup, use the [5-minute quickstart](docs/quickstart.md).
- For failures, check [docs/troubleshooting.md](docs/troubleshooting.md) and
  [docs/compatibility.md](docs/compatibility.md).
- Include `tgcc --version` output or the exact commit.
- Run `tgcc doctor --env <file>`, `tgcc status --env <file>`, and
  `tgcc logs --env <file> -n 100`.
- Sanitize all output before sharing it publicly.

## Where To Ask

- Reproducible bugs: use the Bug report issue template.
- Focused improvements: use the Feature request issue template.
- Questions / help: use the Question / help issue template.
- Security vulnerabilities: report privately through [SECURITY.md](SECURITY.md)
  or GitHub private vulnerability reporting:
  <https://github.com/Ike-li/claude-code-tg/security/advisories/new>.
- Conduct reports: follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## What Not To Share Publicly

Do not paste Telegram bot tokens, `.env` files, Claude credentials, API keys,
private chat transcripts, unsanitized logs, local filesystem paths,
screenshots with personal data, exploit details, or conduct incident details in
public issues or pull requests.

## Scope

In scope for the current preview line:

- install and upgrade guidance
- Telegram bot setup and allowlist behavior
- Claude Code CLI invocation and permission-mode behavior
- multi-instance `*.env` management
- logs and attachment handling

Out of scope for the current preview line:

- enterprise SSO, RBAC, or audit requirements
- managed cloud hosting
- Telegram-side per-tool approval cards
- voice or TTS, multi-provider switching, or one-click Git publishing
- unsafe deployments that expose the bot to untrusted users

## Response Expectations

This is a small preview project. Best-effort responses are more likely when a
report includes reproduction steps, versions, sanitized config shape, expected
behavior, actual behavior, and validation commands already run.
