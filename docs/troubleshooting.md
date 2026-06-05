# Troubleshooting Guide

Use this guide before opening an issue. It keeps the first diagnostic pass
repeatable and helps maintainers distinguish configuration issues from `tgcc`
bugs without asking for private logs or tokens.

## First Checks

Run these commands against the exact env file that starts the instance:

```bash
tgcc --version
tgcc doctor --env <file>
tgcc status --env <file>
tgcc logs --env <file> -n 100
```

If you are not sure which env file is active, run:

```bash
tgcc status --all
```

For public issues, do not paste Telegram bot tokens, Claude credentials,
private chat transcripts, unsanitized logs, or local filesystem paths. Share
only sanitized output.

## Bot Does Not Reply

Check these in order:

- `tgcc status --env <file>` says the target instance is running.
- `tgcc logs --env <file> -n 100` shows a clean startup and no auth or polling
  error.
- `ADMIN_USER_IDS` or `ALLOWED_USER_IDS` includes your Telegram user id.
- In group chats, you mentioned the bot or replied to a bot message.
- The BotFather token belongs to the bot you are messaging and has not been
  revoked.
- `CLAUDE_PROJECT_DIR` exists and is readable by the local user running `tgcc`.
- `claude --help` works for the same local user.

## Claude Code CLI Is Missing Or Unauthenticated

`tgcc start` checks for the `claude` command before launching the bot. If it
fails:

```bash
which claude
claude --help
```

Run one normal Claude Code session as the same local user, finish
authentication, then start `tgcc` again. Avoid starting `tgcc` from a service
account or shell profile that has a different `PATH` from your interactive
terminal.

## Telegram Sessions Do Not Appear In Local Claude `/resume`

`tgcc` runs Claude Code through headless `claude -p --output-format stream-json`
so it can stream tool events and status cards back to Telegram. Those
transcripts are written under the same `~/.claude/projects/<project>` history
tree as local Claude Code, but their `entrypoint` is `sdk-cli`. Claude Code's
interactive `/resume` picker may hide those sessions even when they are in the
same project directory.

To make Telegram-started sessions visible to the local picker, set:

```env
CLAUDE_CLI_RESUME_COMPAT=true
```

Then restart the instance. New completed tgcc runs will rewrite their transcript
`entrypoint` values from `sdk-cli` to `cli` after the Claude process exits. This
edits Claude Code's private local history files, so keep it disabled unless you
need local picker compatibility. You can always manually resume a known session
id from the project directory:

```bash
claude --resume <session_id>
```

## Already Running

`Already running` means the same `.env` instance already has a recorded process.
Inspect it before starting another copy:

```bash
tgcc status --env <file>
tgcc stop --env <file>
tgcc start --env <file>
```

If the process died unexpectedly, `tgcc stop --env <file>` cleans up stale
runtime metadata when it is safe to do so.

## Multiple Env Files

Each `*.env` file is treated as a separate instance. Use explicit `--env`
arguments for single-instance operations:

```bash
tgcc status --all
tgcc logs --env prod.env -n 100
tgcc restart --env prod.env
```

Use `tgcc start-all`, `tgcc stop-all`, and `tgcc restart-all` only when you
intend to operate every discovered non-symlink env file in the scan directory.

## Doctor Reports Broad Permissions

`.env`, instance directories, `tgcc.log`, pid files, metadata, status files, and
attachment caches should be owner-only. Fix regular files and directories with:

```bash
tgcc doctor --env <file> --fix-permissions
tgcc doctor --env <file>
```

Automation can use `tgcc doctor --env <file> --strict --format json` to fail on
warnings and collect structured diagnostics.

Where the platform supports no-follow file opening, `tgcc` rejects user
controlled symlink path components for local secrets, logs, runtime metadata,
and attachment caches. `--fix-permissions` skips symlinks instead of changing a
link target. Replace symlinked env files or runtime paths with regular files
and directories.

## Attachments Are Downloaded But Claude Cannot Read Them

The common cause is `ATTACHMENT_MODE=path` combined with Claude Code's default
permission mode, which may reject paths outside `CLAUDE_PROJECT_DIR`. Switch to
`ATTACHMENT_MODE=copy-to-project` when Claude needs to read attachment contents
directly.

See [User Guide → Attachment Handling](user-guide.md#attachment-handling) for
the full mode table, the `attachments prune` commands, and
`ATTACHMENT_RETENTION_DAYS` cleanup.

## Permission Modes

If the default `bypassPermissions` is too broad for the current repo or user
set, change `CLAUDE_PERMISSION_MODE` to `default` or `plan` before restarting.
See [User Guide → Model, Effort, And Permission Modes](user-guide.md#model-effort-and-permission-modes)
for the full behavior of each mode and the per-chat `/permissions` override.

## A Token May Have Been Exposed

Use one dedicated BotFather token per instance, and revoke or rotate any token
that may have been exposed. Keep tokens out of public issues, logs, and chat
transcripts. If a token may be exposed, revoke or rotate it through BotFather,
then remove any local secret files yourself before sharing diagnostics.
