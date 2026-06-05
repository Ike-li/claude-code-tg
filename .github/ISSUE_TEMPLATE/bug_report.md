---
name: Bug report
about: Report a reproducible tgcc problem
title: "[Bug]: "
labels: bug, needs triage
assignees: ""
---

## What happened?

Describe the problem and the expected behavior.

## Steps to reproduce

1.
2.
3.

## Environment

- tgcc version or commit: run `tgcc --version`, or include the exact commit
- Python version:
- OS:
- Claude Code CLI version:
- Install method: `uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"` / `uv tool install -e .` / `uv sync` / other

## Configuration shape

Do not paste secrets, tokens, chat transcripts, unsanitized logs, or local
filesystem paths. Include only safe values such as:

```env
CLAUDE_PROJECT_DIR=
CLAUDE_TIMEOUT=
QUEUE_MAX_SIZE=
CLAUDE_PERMISSION_MODE=
CLAUDE_MODEL=
ATTACHMENT_MAX_MB=
ATTACHMENT_MODE=
ATTACHMENT_RETENTION_DAYS=
CLAUDE_SKIP_PERMISSIONS=
```

## Logs

Paste relevant sanitized output from:

```bash
tgcc doctor --env <file>
tgcc status --env <file>
tgcc logs --env <file> -n 100
```

## Additional context

Screenshots, Telegram message examples, or suspected related changes. Redact
personal data before sharing anything publicly.

## Privacy checklist

- [ ] I did not include Telegram bot tokens, `.env` files, Claude credentials, API keys, private chat transcripts, unsanitized logs, local filesystem paths, screenshots with personal data, or exploit details.
- [ ] This is not a security vulnerability report. Security-sensitive reports should follow SECURITY.md instead of public issues.
