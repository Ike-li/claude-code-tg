# Operator Guide

This guide is for maintainers or operators running `tgcc` beyond a one-off
local test. It focuses on deployment boundaries, routine checks, and incident
response.

## Deployment Profile

`tgcc` is designed for self-hosted use on a trusted machine. The operating
system account that runs the bot can inspect local project files, `~/.tgcc/`
state, logs, status files, attachments, and Claude Code data.

Recommended baseline:

- one dedicated Telegram BotFather token per instance
- one `.env` file per project boundary
- confirm `CLAUDE_PERMISSION_MODE` before first launch; the generated template
  defaults to `bypassPermissions` for trusted local projects, while
  untrusted/shared project directories should use `default` or `plan`
- `ATTACHMENT_MODE=reject` when file intake is not required
- trusted Telegram users only in `ADMIN_USER_IDS` and `ALLOWED_USER_IDS`

Use one dedicated BotFather token per instance, and revoke or rotate any token
that may have been exposed.

## Local State And Permissions

Runtime state lives under `~/.tgcc/<instance>/`. It includes pid files,
`status.json`, `instance.json`, `tgcc.log`, and attachment caches.

Before sharing logs or smoke evidence, run:

```bash
tgcc doctor --env <file> --fix-permissions
tgcc doctor --env <file>
tgcc doctor --env <file> --strict --format json
```

The expected local posture is owner-only permissions for `.env`, runtime files,
logs, and attachment caches. `tgcc init` secures generated env files without
chmodding the containing project directory; `tgcc start` checks env path
permissions and symlink state before loading dotenv, and runtime instance
directories remain owner-only. Logs are redacted, but they can still contain
local paths, chat behavior, timestamps, and error context.
Use the strict JSON form for deployment automation that should fail on warnings
and archive structured diagnostics without scraping the human report.

`tgcc` logs the instance default permission mode and effort at startup, then
logs the effective mode and effort when each Claude run starts. Telegram also
shows the active mode and effective effort in `/start`, `/status`, and run
status cards.

## Start, Stop, And Observe

Routine lifecycle:

```bash
tgcc start --env prod.env
tgcc status --env prod.env
tgcc logs --env prod.env -n 100
tgcc logs --env prod.env -f
tgcc restart --env prod.env
tgcc stop --env prod.env
```

For several local env files:

```bash
tgcc start-all
tgcc status --all
tgcc stop-all
```

## Attachment Retention

Operators should choose an explicit attachment policy:

- `ATTACHMENT_MODE=reject` for deployments that should not process files.
- `ATTACHMENT_MODE=path` when files can stay in instance storage.
- `ATTACHMENT_MODE=copy-to-project` when Claude must read attachments from the
  project directory.

Manual cleanup:

```bash
tgcc attachments prune --env prod.env --dry-run
tgcc attachments prune --env prod.env --older-than-days 30
```

Automatic cleanup:

```env
ATTACHMENT_RETENTION_DAYS=30
```

This prunes old instance attachment caches and project `.tgcc-attachments/`
copies on startup and daily while the bot is running.

## Upgrade Routine

Before upgrading a running instance:

1. Run `tgcc status --env <file>` and note the PID and log path.
2. Stop the instance with `tgcc stop --env <file>`.
3. Upgrade or reinstall the package.
4. Run `tgcc doctor --env <file>`.
5. Start again with `tgcc start --env <file>`.
6. Confirm `tgcc logs --env <file> -n 100` shows a clean startup.

For local editable installs:

```bash
uv tool install -e . --force
```

## Incident Response

If a Telegram bot token, `.env`, private log, chat transcript, or smoke artifact
is exposed:

1. Revoke or rotate the BotFather token immediately.
2. Stop affected `tgcc` instances.
3. Remove public copies of the exposed artifact.
4. Review `tgcc.log`, `status.json`, and attachment caches for related exposure.
5. Use GitHub private vulnerability reporting for security-sensitive follow-up.
6. Add a regression test if the exposure came from a repo
   process gap.

## Public Support Boundary

Public reports should include sanitized diagnostics only:

```bash
tgcc doctor --env <file>
tgcc status --env <file>
tgcc logs --env <file> -n 100
```

Move vulnerability details, exploit steps, tokens, private chat transcripts, and
unsanitized logs out of public issues. Use [Support](../SUPPORT.md) for public
support boundaries and [Security Policy](../SECURITY.md) for private
vulnerability reporting.
