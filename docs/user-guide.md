# User Guide

This guide expands the quick start in `README.md` into the day-to-day workflow
for running `tgcc` as a self-hosted Telegram bridge to Claude Code CLI.

## Install And Upgrade

Install from the public repository:

```bash
uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"
tgcc --version
```

PyPI is not published for the `0.1.0` preview, and the public repository does not
currently maintain a public tagged release. Use the Git URL for public installs or a
local editable install while developing; for long-running instances, record
`tgcc --version` and the installed commit.

For local development:

```bash
git clone https://github.com/Ike-li/claude-code-tg.git
cd claude-code-tg
uv sync --extra dev
uv run tgcc --help
uv run tgcc --version
```

To upgrade a local editable install after pulling new code:

```bash
uv tool install -e . --force
```

## Configuration

Create a config file with `tgcc init`, or copy `.env.example`:

```bash
tgcc init --env prod.env
cp .env.example prod.env
chmod 600 prod.env
```

`tgcc init` defaults to a quick setup that asks only the three essentials (bot
token, your user ID, project directory) and fills sane defaults for everything
else. Use `tgcc init --full` to be prompted for every option instead.

`tgcc init` secures the generated env file itself with `0600` permissions but
does not chmod the project directory that contains it.
Use one dedicated BotFather token per instance, and revoke or rotate any token
that may have been exposed. Keep tokens out of public issues, logs, and chat
transcripts.

Minimum required settings:

```env
TELEGRAM_BOT_TOKEN=<bot token from BotFather>
ADMIN_USER_IDS=<your Telegram user id>
CLAUDE_PROJECT_DIR=/path/to/project
```

Common optional settings:

```env
ALLOWED_USER_IDS=
CLAUDE_TIMEOUT=300
QUEUE_MAX_SIZE=3
CLAUDE_PERMISSION_MODE=bypassPermissions
CLAUDE_MODEL=
CLAUDE_EFFORT=
ATTACHMENT_MAX_MB=20
ATTACHMENT_MODE=path
ATTACHMENT_RETENTION_DAYS=
CLAUDE_SKIP_PERMISSIONS=false
LOG_INTERACTIONS=false
CLAUDE_COMMAND_MENU=false
TELEGRAM_DRAFT_PREVIEW=false
TELEGRAM_MINI_APP_ENABLED=false
```

`CLAUDE_TIMEOUT` is the stdout idle-check interval. If the Claude process is
still running after that many seconds without output, tgcc keeps waiting; errors
are returned only after Claude exits or the user stops the run.

Use `tgcc doctor --env <file>` before starting a new instance. It checks the
env file, project directory, Claude CLI availability, attachment settings, and
owner-only local permissions.
For CI, deployment scripts, or release dashboards, use
`tgcc doctor --env <file> --strict --format json` so warnings return non-zero
and the result is machine-readable.

## Daily Commands

Single instance:

```bash
tgcc start --env prod.env
tgcc status --env prod.env
tgcc logs --env prod.env -n 100
tgcc logs --env prod.env -f
tgcc restart --env prod.env
tgcc stop --env prod.env
```

Multiple instances in one directory:

```bash
tgcc start-all
tgcc status --all
tgcc restart-all
tgcc stop-all
```

## Telegram Commands

| Command | Purpose |
|---------|---------|
| `/start` | Show the welcome message. |
| `/new` | Start a fresh Claude Code session. |
| `/resume [session_id|keyword|--all]` | List recent local/tgcc Claude sessions, search them, or attach to a session id. |
| `/clear` | Clear the current Telegram chat's Claude context. |
| `/model <model>` | Set the current chat's Claude model override; `reset` restores the instance default. |
| `/effort <level>` | Set the current chat's Claude effort override; `reset` restores the instance default. |
| `/permissions <mode>` | Set the current chat's Claude permission-mode override; `reset` restores the instance default. |
| `/context` | Pass Claude `/context` to show context usage. |
| `/usage` | Pass Claude `/usage` to show current-call usage. |
| `/cost` | Pass Claude `/cost` to show current-call cost. |
| `/reload_skills` | Pass Claude `/reload-skills` to refresh skills. |
| `/stop` | Stop the current Claude Code run. |
| `/status` | Show session, queue, settings, attachment state, and the last Claude CLI runtime metadata. |
| `/run <cmd>` | Pass a Claude Code slash command such as `/compact`. |
| `/commands` | List pass-through Claude Code slash commands; use `/commands refresh` to refresh the cache. |
| `/help` | Show bot help. |

Use `/commands` when you need to discover Claude Code commands without adding
them to the Telegram menu. It also hides entries that collide with tgcc bot
control commands. Tap a listed command button to execute it, or use the copy
button for the `/run /command` form.
Claude Code runs through `claude -p`, so commands that require an interactive
TTY, picker, account flow, local setup wizard, or diagnostic file write are
filtered. tgcc wraps high-value interactive commands such as `/model`,
`/effort`, and `/permissions` as native per-chat settings, and directly exposes
only headless-safe built-ins such as `/context`, `/usage`, `/cost`, and
`/reload_skills`.
When `/model`, `/permissions`, or `/mode` are sent without arguments, tgcc also
shows inline buttons for common choices and a ForceReply prompt for custom
values. `/effort` shows inline choices without opening a reply prompt. Typed
values such as `/model opus`, `/effort ultracode`, and `/permissions plan`
continue to work.
To move a Telegram session to another chat, copy the full `session_id` from
`/status` in the original chat and send `/resume <session_id>` in the target
chat.
To attach a local or tgcc-created Claude Code session from the same project, run `/resume`
and tap one of the listed session buttons. By default tgcc shows the recent
sessions only; use `/resume <keyword>` to search titles, ids, branches, and
paths, or `/resume --all` to show the full list. The listed sessions include
copy buttons for full IDs. You can still send `/resume <session_id>` manually.
When no local sessions are found, tgcc shows the manual `/resume <session_id>`
form without switching the Telegram input box into reply mode. `/attach` and
`/sessions` remain available as compatibility aliases.

In group chats, use slash commands addressed to the bot, mention the bot, or
reply to a bot message. Group chats share one chat-level Claude session and
queue. Telegram BotFather privacy mode affects which group messages are
delivered to bots: `/run@your_bot ...` style commands work with privacy enabled,
but natural non-command `@your_bot` mentions may require disabling privacy for
that dedicated bot.

During a run, tgcc keeps one editable status card in the chat and sends
best-effort Telegram `typing...` actions while Claude is working. The card
refreshes periodically during long quiet tool runs so the elapsed time keeps
moving even when Claude has not emitted a new stream event. The compact card
shows a short task summary, the current tool, a stop button while running, and
details/copy buttons when tool detail is available. Tool input/output is folded
by default; expanded details can be filtered by all/input/output/error and
paged through when a run has many tool calls. The final Claude answer is still
sent separately, so completed text-only commands do not duplicate their answer
inside the status card.

Final answers include action buttons for common follow-ups: rerun the same
prompt, show status, start a new session, or copy the result text. Rerun buttons
use short in-memory tokens; if an old result button expires after restart or
state pruning, send the prompt again manually.

`/status` also includes a `Claude CLI 回传` section after the first Claude run
in a chat. That section is a last-known snapshot from Claude Code
`stream-json`, including fields such as `claude_code_version`, `cwd`, `model`,
`permissionMode`, `mcp_servers`, `contextWindow`, `maxOutputTokens`, and
`speed`. Before the first run, tgcc shows that no Claude CLI runtime metadata is
available yet.

## Attachment Handling

`ATTACHMENT_MODE=path|copy-to-project|reject` controls Telegram file handling:

| Mode | Behavior |
|------|----------|
| `path` | Keep files under `~/.tgcc/.../attachments` and pass that path to Claude. |
| `copy-to-project` | Copy files into `<project>/.tgcc-attachments/` before prompting Claude. |
| `reject` | Refuse Telegram attachments. |

Claude Code's default permission mode may reject paths outside
`CLAUDE_PROJECT_DIR`. Use `copy-to-project` only when Claude needs to read
attachment contents directly. Use `reject` when the deployment should never
process Telegram files. `ATTACHMENT_MAX_MB` defaults to `20` and rejects larger
Telegram files before they are passed to Claude.

Clean old attachments on demand:

```bash
tgcc attachments prune --env prod.env --dry-run
tgcc attachments prune --env prod.env --older-than-days 30
```

For unattended instances, set `ATTACHMENT_RETENTION_DAYS=30` to prune old
instance and project attachment copies on startup and daily while the bot is
running.

## Model, Effort, And Permission Modes

`CLAUDE_MODEL` sets the instance default for Claude Code `--model`. `/model`
sets a per-chat override, and `/model reset` restores the instance default.
Empty values use the Claude Code CLI default.

`CLAUDE_EFFORT` sets the instance default for Claude Code `--effort`.
Supported values follow Claude Code: `low`, `medium`, `high`, `xhigh`, `max`,
and `ultracode`. Empty values use the CLI default. `/effort <level>` sets a
per-chat override, and `/effort reset` restores the instance default. `x-high`
and `x_high` are accepted as aliases for `xhigh`; `ultra-code` and `ultra_code`
are accepted as aliases for `ultracode`.

`.env.example` and `tgcc init` default to
`CLAUDE_PERMISSION_MODE=bypassPermissions` for trusted local projects. This is
convenient over Telegram but bypasses Claude Code permission prompts, so change
it to `default` or `plan` before starting on untrusted/shared project
directories. The current mode appears in `/start`, `/status`, each run status
card, and startup/run logs. `/start`, `/status`, and run cards also show the
effective effort. Use `/permissions <mode>` to set a per-chat permission-mode
override, and `/permissions reset` to restore the instance default.

`CLAUDE_SKIP_PERMISSIONS=true` is a legacy broad bypass that appends Claude
Code's `--dangerously-skip-permissions` flag only when no explicit
`CLAUDE_PERMISSION_MODE` is set. Prefer `CLAUDE_PERMISSION_MODE` and use this
legacy switch only for trusted local projects.

`CLAUDE_CLI_RESUME_COMPAT=false` is the default. Set it to `true` only when you
want Telegram-started headless sessions to appear in the local Claude Code
`/resume` picker. When enabled, tgcc rewrites the completed session transcript's
top-level `entrypoint` values from `sdk-cli` to `cli` after the Claude process
exits. This touches Claude Code's local private history files under
`~/.claude/projects`, so leave it off unless that picker compatibility matters
for your workflow.

`LOG_INTERACTIONS=false` is the default. Set it to `true` only for local
debugging; interaction logs can include Telegram message content, Claude
prompts, and model output.
When sharing `/status` output in issues, support chats, or public channels,
redact full session IDs, `cwd`, and MCP server details that reveal local paths,
project names, private services, or account state.

`CLAUDE_COMMAND_MENU=false` is the default. Set it to `true` only when you want
startup to probe Claude slash commands once and cache Telegram menu entries.

## Draft Preview And Mini App

`TELEGRAM_DRAFT_PREVIEW=false` is the default. When set to `true`, private chats
receive Telegram's ephemeral `sendMessageDraft` preview while Claude is
generating. It is only a temporary preview; tgcc still sends the final answer as
a normal Telegram message.

The Mini App console is optional and off by default:

```env
TELEGRAM_MINI_APP_ENABLED=false
TELEGRAM_MINI_APP_PUBLIC_URL=https://example.com/tgcc
TELEGRAM_MINI_APP_HOST=127.0.0.1
TELEGRAM_MINI_APP_PORT=8787
TELEGRAM_MINI_APP_MENU_TEXT=tgcc
```

Install the optional dependencies with `uv sync --extra mini-app` before
enabling it. `TELEGRAM_MINI_APP_PUBLIC_URL` must be HTTPS and point to the
externally reachable URL for the local web console. The v1 console is private
chat only; it can show current status and run summary, stop or start sessions,
set model/effort/permission overrides, attach a session id, and rerun the last
prompt.
Some Telegram clients cache the chat menu button, and a private chat may have a
chat-specific menu override. If the Mini App menu does not appear after startup
even though logs show `setChatMenuButton` succeeded, reopen the chat/client or
check for a chat-specific menu button override.

## Troubleshooting

For symptom-by-symptom checks, use the
[Troubleshooting guide](troubleshooting.md). It covers no-reply cases, Claude
CLI auth, already-running instances, multi-env directories, permission warnings,
attachments, and token exposure handling.
