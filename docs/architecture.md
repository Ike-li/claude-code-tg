# Architecture

`tgcc` is a local Telegram-to-Claude-Code bridge. It intentionally keeps the
runtime small: Telegram updates arrive in Python, Claude work runs in short
Claude Code CLI subprocesses, and local state stays under `~/.tgcc/`.

## Core Flow

```text
Telegram user
  -> python-telegram-bot Application
  -> TGBot command/message handler
  -> per-chat queue
  -> claude -p subprocess
  -> stream-json events
  -> Telegram status card + final answer
```

Each Claude run is a short-lived process:

```bash
claude -p --input-format text \
  --session-id <new_uuid> | --resume <session_id> \
  [--model <model>] [--effort <level>] \
  --output-format stream-json \
  --verbose
```

The prompt is written through stdin, not argv. `CLAUDE_PROJECT_DIR` becomes the
subprocess `cwd`, not a shell-built argument. The code uses
`create_subprocess_exec`, not `shell=True`.

## Key Decisions

| Decision | Reason |
| --- | --- |
| Short-lived Claude processes | Avoid long-lived TTY state, prompt-ready detection, ANSI parsing, crash recovery, and per-user interactive process pools. |
| `--resume` for continuity | Claude Code owns conversation JSONL state; tgcc only stores chat-to-session mappings. |
| `stream-json` instead of final JSON only | Lets Telegram show tool progress, Stop, status cards, and recent output while Claude is still running. |
| Per-chat serialization | A chat has one active runner and a FIFO queue; different chats can run concurrently. |
| Final answer separate from status card | Status cards answer "what is it doing now?"; final answers stay readable and paginated. |
| Short callback tokens | Telegram callback payloads stay small; long prompts, session ids, and command names live in process-local stores. |

## Sessions And Queues

State is keyed by Telegram `chat_id`:

- `sessions`: chat -> Claude session id
- `permission_modes`: chat -> permission override
- `model_overrides`: chat -> model override
- `effort_overrides`: chat -> Claude effort override
- `busy`: chats with an active runner
- `queues`: FIFO prompts waiting behind the active runner

`/new`, `/clear`, and `/resume <session_id>` bump a session version and clear
the active chat state. Results only write back when the version still matches,
so an old run cannot overwrite a new session after `/new`.

Group chats share one chat-level session, queue, model override, effort
override, and permission override. Any authorized group participant can stop the
shared run.

Persistent state is written to `status.json`; Claude Code conversation history
itself remains in Claude's own user data under `~/.claude/projects/`.

## Telegram UI Model

Each run creates one editable status card and one separate final answer:

- the status card shows task summary, elapsed time, session, branch, effective
  permission mode/model/effort, CLI args, context tokens/window, current tool,
  copy buttons, detail filters, pagination, and Stop while running
- tool input/output/error blocks are folded out of the compact card and shown
  through expanded details
- queue state is shown through `/status` and persistent queued messages rather
  than embedded in every run status card
- best-effort `sendChatAction(typing)` heartbeats run while Claude is active
- status-card heartbeat edits refresh elapsed time during long quiet tool runs
- final answers are paginated through `message_output.py`
- result buttons support rerun, status, new session, and copy result

ForceReply is used for missing `/run`, `/resume`, `/model`, and `/permissions`
arguments. `/effort` uses inline choices without opening a reply prompt. Pending
reply tokens are process-local, scoped by chat, prompt message id, intent, and
originating user.

Draft Preview is optional and private-chat only. When
`TELEGRAM_DRAFT_PREVIEW=true`, `sendMessageDraft` can show temporary assistant
text previews, but the normal status card and final answer remain the source of
truth.

## Slash Command Policy

Claude commands are executed through `claude -p`, a non-interactive headless
environment. Commands that need a TTY, picker, account flow, local setup wizard,
or diagnostic side effect are filtered from Telegram command menus.

tgcc owns bridge-level commands such as `/new`, `/resume`, `/status`, `/stop`,
`/commands`, `/run`, and `/help`. High-value interactive Claude commands such
as `/model`, `/effort`, and `/permissions` are implemented as native per-chat
settings. Headless-safe Claude built-ins such as `/context`, `/usage`, `/cost`,
and `/reload_skills` are exposed as wrappers.

Project and skill slash commands discovered from Claude are shown through
`/commands` and executed as `/run /command`. Built-in management commands and
commands that collide with tgcc controls are filtered.

## Attachments

Telegram documents and photos are downloaded before Claude runs. The default
instance path is:

```text
~/.tgcc/<instance>/attachments/<chat_id>/<timestamp>-<random>-<safe-name>
```

`ATTACHMENT_MODE` controls what happens next:

| Mode | Behavior |
| --- | --- |
| `path` | Pass the instance-cache path to Claude. |
| `copy-to-project` | Copy into `<project>/.tgcc-attachments/` before prompting Claude. |
| `reject` | Refuse Telegram attachments. |

`copy-to-project` helps when Claude Code default permissions reject reads
outside `CLAUDE_PROJECT_DIR`, but it writes files into the project and should be
explicit. Attachment cleanup is shared by the CLI prune command and optional
daily retention jobs.

## Mini App

The Mini App console is optional and disabled by default. When enabled, `server`
starts a Starlette/Uvicorn app in the same process and configures Telegram's Web
App menu button with an HTTPS public URL.

`web_console.py` validates Telegram Mini App `initData` HMAC, `auth_date`, and
tgcc allowlists. The frontend never receives the Bot token. v1 supports private
chat status plus `stop`, `new`, `resume`, `set_model`, `set_effort`,
`set_permissions`, and `rerun` actions; it does not support attachment upload,
group contexts, or full tool logs.

## Module Map

| Module | Responsibility |
| --- | --- |
| `server.py` | Load runtime config, initialize bot, start polling and optional Mini App server. |
| `cli.py`, `cli_parser.py` | `tgcc` CLI behavior and argument declarations. |
| `config.py`, `cli_init.py` | Env parsing, defaults, validation, and `tgcc init`. |
| `cli_instances.py`, `instance_store.py`, `process_control.py` | Multi-env discovery, instance paths, PID/log/status metadata, and process lifecycle. |
| `bot.py`, `bot_app.py` | TGBot state, authorization, Telegram Application wiring, jobs, and update intake. |
| `bot_commands.py`, `command_menu.py` | Telegram commands, callbacks, ForceReply, settings, resume, command picker flows, and Claude slash-command menu probing/pass-through. |
| `bot_processing.py` | Claude run lifecycle, status card updates, final answer, queue drain. |
| `executor.py` | Claude subprocess creation, `stream-json` parsing, cancellation, and `RunEvent` emission. |
| `sessions.py`, `claude_sessions.py` | Chat sessions, queues, model/effort/permission overrides, `status.json` persistence, and discovery/parsing of local Claude Code session transcripts for `/resume`. |
| `run_view.py`, `result_view.py`, `resume_view.py`, `command_view.py` | Telegram UI rendering and short-token stores. |
| `message_input.py`, `attachments.py`, `attachment_cleanup.py` | Telegram text/photo/document conversion, attachment modes, and cleanup. |
| `message_output.py`, `telegram_ui.py` | Telegram pagination, HTML escaping, and button helpers. |
| `pending_reply.py` | Process-local ForceReply pending store. |
| `web_console.py` | Optional Mini App API, static page, and initData authentication. |
| `diagnostics.py`, `file_security.py`, `sanitizer.py`, `interaction_log.py`, `utils.py` | Doctor checks, owner-only file helpers, redaction, optional interaction logging, and shared utilities. |

## Concurrency

`bot_app.py` enables concurrent Telegram update handling so Stop callbacks and
new messages are received while another handler is waiting on Claude. Business
serialization still happens per chat:

- different chats can run in parallel
- the same chat has one active run plus a bounded FIFO queue
- queue overflow is reported to the user
- `/new`, `/clear`, and `/resume` stop active work and clear queued prompts for
  that chat

Claude subprocesses run in their own process groups where supported. Stop and
`tgcc stop` terminate the process group and escalate if needed. The configured
Claude timeout is an stdout idle check; tgcc keeps waiting while the Claude
process is still running.

## Local State And Security Boundaries

Instance directories are named from the env path stem plus a hash:

```text
~/.tgcc/<env-stem>-<path-hash>/
```

Each instance contains `tgcc.pid`, `tgcc.log`, `status.json`, `instance.json`,
and `attachments/`. Runtime files are owner-only where the platform supports
it. Env files, runtime metadata, logs, PID files, status files, and attachment
paths avoid user-controlled symlink traversal through the shared file-security
helpers.

Important boundaries:

- Telegram access is gated by `ADMIN_USER_IDS` and `ALLOWED_USER_IDS`.
- Prompt text is sent to Claude through stdin and redacted before logs/output
  where applicable.
- `CLAUDE_PERMISSION_MODE` maps to Claude Code `--permission-mode`; template
  defaults such as `bypassPermissions` are only appropriate for trusted users
  and trusted project directories.
- `CLAUDE_EFFORT` maps to Claude Code `--effort`; empty values leave the CLI
  default in control.
- `CLAUDE_CLI_RESUME_COMPAT=true` is an opt-in compatibility shim that rewrites
  completed tgcc transcript `entrypoint` values from `sdk-cli` to `cli` so the
  local Claude Code `/resume` picker may show Telegram-started sessions.
- `CLAUDE_SKIP_PERMISSIONS` is a legacy compatibility path for
  `--dangerously-skip-permissions` and should remain rare.
- `status.json` persists local bridge state and the last Claude runtime metadata
  snapshot, but it does not persist the last prompt.

See `docs/security-model.md` for the full trust-boundary summary.

## Error Boundaries

| Scenario | Behavior |
| --- | --- |
| Claude CLI missing | `tgcc doctor` and startup report the missing command. |
| Non-zero Claude exit | stderr/result text is sanitized and returned as an error result. |
| Idle timeout while Claude is running | keep waiting instead of reporting an error. |
| Invalid JSON line | skip the line and keep reading. |
| Long Telegram output | paginate under Telegram message limits. |
| Attachment too large | reject before or after download depending on known size. |
| Telegram API best-effort UI failure | log/debug and keep the run lifecycle moving where safe. |
