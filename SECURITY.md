# Security Policy

`tgcc` is a self-hosted bridge between Telegram and a local Claude Code CLI
process. Treat the machine that runs it as trusted infrastructure: authorized
Telegram users can ask Claude Code to inspect or change files in the configured
project directory.

For the full trust-boundary model, see
[docs/security-model.md](docs/security-model.md).

## Supported Versions

Security fixes are best effort and focus on the latest tagged release (`v0.8.0`)
and the current `main` branch.

| Version or branch | Security support |
| --- | --- |
| Latest tagged release (`v0.8.0`) | Best-effort fixes for issues affecting the latest release. |
| Current `main` | Best-effort fixes for issues affecting the current codebase. |
| Older tags or commits | Not supported; upgrade before reporting unless the issue still affects supported code. |

## Reporting A Vulnerability

Report suspected vulnerabilities privately through GitHub private vulnerability
reporting:

<https://github.com/Ike-li/claude-code-tg/security/advisories/new>

Do not include exploit details, tokens, chat transcripts, local paths,
configuration values, or proof-of-concept steps in a public issue. If the
private advisory page is unavailable, a public issue may only ask maintainers to
restore a private security contact path.

Include the following only in the private report:

- affected version or commit
- configuration shape, with tokens removed
- steps to reproduce
- expected impact

## Response Expectations

This Alpha project handles vulnerability reports on a best-effort basis.
Maintainers should acknowledge private reports when available, triage whether
the issue affects token handling, local file access, attachments, Claude Code
invocation, logs, release artifacts, or GitHub Actions, and keep details private
until a fix, mitigation, or no-impact decision is ready.

## Deployment Checklist

- Use one dedicated Telegram bot token per instance.
- Rotate or revoke any BotFather token used for smoke testing before publishing
  screenshots, recordings, logs, or releases.
- Keep `.env` files out of git and set them to owner-only permissions; `tgcc init`
  creates env files as owner-only files.
- Use regular files and directories for `.env`, instance, pid, log, status, and
  attachment paths. Replace symlinked runtime paths before production use.
- Restrict `ADMIN_USER_IDS` and `ALLOWED_USER_IDS` to trusted users.
- Prefer conservative `CLAUDE_PERMISSION_MODE` values such as `default` or
  `plan`.
- Use `bypassPermissions` or `CLAUDE_SKIP_PERMISSIONS=true` only for trusted
  project directories and trusted Telegram users.
- Treat prompts, Claude transcripts, attachments, and logs as sensitive local
  data.
- Treat Telegram attachments as untrusted input; use `tgcc attachments prune
  --env <file> --dry-run` before deleting old attachment files.
- Run one bot per project when projects need separate access boundaries.
- Review logs before sharing them; tgcc redacts common secrets, but no
  sanitizer can guarantee complete coverage.
