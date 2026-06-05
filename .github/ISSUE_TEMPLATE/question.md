---
name: Question / help
about: Ask for setup or usage help within tgcc support scope
title: "[Question]: "
labels: question, needs triage
assignees: ""
---

## What are you trying to do?

Describe the setup, command, or Telegram workflow you are trying to complete.

## Where are you stuck?

Describe what happened, what you expected, and which README or troubleshooting
step you already tried.

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

## Diagnostics

Paste relevant sanitized output from:

```bash
tgcc doctor --env <file>
tgcc status --env <file>
tgcc logs --env <file> -n 100
```

## Privacy checklist

- [ ] I did not include Telegram bot tokens, `.env` files, Claude credentials, API keys, private chat transcripts, unsanitized logs, local filesystem paths, screenshots with personal data, or exploit details.
- [ ] This is not a security vulnerability report. Security-sensitive reports should follow SECURITY.md instead of public issues.
