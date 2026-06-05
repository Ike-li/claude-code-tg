# Telegram E2E Guide

Use this single guide for full Telegram E2E sessions. It replaces the older
separate plan and runbook files. Keep it sanitized: never record bot tokens,
numeric Telegram IDs, full session IDs, private logs, temporary tunnel URLs, or
local attachment cache paths.

## Scope

The goal is not line coverage. The goal is that every Telegram-facing entry
point has one of these evidence types:

- Real client: Telegram Desktop or mobile behavior observed through Computer
  Use or manual confirmation.
- Background API/logs: local CLI, app logs, safe Bot API methods that do not
  compete with polling, or Mini App HTTP API checks.
- Local regression: pytest or `validate_local.py` evidence for rows that cannot
  be safely or reliably forced through Telegram Desktop.
- Boundary: explicitly recorded desktop automation, multi-account, external
  quota, or setup limitation.

The Telegram-facing code surface includes bot startup, static commands,
callbacks, message routing, queue/run views, attachments, Draft Preview, group
chat, and the optional Mini App console.

## Strategy

Use a hybrid background flow:

- Run setup, `tgcc doctor`, instance start/stop, log review, local regression,
  and Mini App HTTP API checks in terminals.
- Use Telegram Desktop only for real client behavior: sending messages, clicking
  buttons, replying to ForceReply prompts, uploading files, group flows, and
  opening Mini Apps.
- Tell the user before starting any Telegram Desktop batch. Computer Use uses
  the same Mac pointer, keyboard, and focused window as the user.
- Use a dedicated BotFather test bot, dedicated private chat, and dedicated test
  group. Do not add a production bot to E2E groups.
- Do not call Telegram `getUpdates` directly while polling is active. Use logs,
  `getMe`, or stop the instance first.

If the user needs uninterrupted desktop work, run the real Telegram client part
from a separate VM, remote desktop, or spare machine.

## Test Resources

Most E2E resources are outside the repository or ignored by git:

- Root env file such as `cctg_test.env`; it must be ignored and `chmod 600`.
- Throwaway Claude project outside the repository via `CLAUDE_PROJECT_DIR`.
- Synthetic upload assets under
  `CLAUDE_PROJECT_DIR/tgcc-e2e-assets`, created by
  `scripts/e2e_prepare_assets.py`.
- `tgcc` logs and runtime state under `$HOME/.tgcc/`.
- Temporary Mini App HTTPS tunnel URL stored only in the ignored env file as
  `TELEGRAM_MINI_APP_PUBLIC_URL`.
- Telegram test bot and test group configuration in Telegram/BotFather.

## Background Commands

Run readiness checks:

```bash
uv run python scripts/e2e_preflight.py --env cctg_test.env
uv run python scripts/e2e_prepare_assets.py --env cctg_test.env
uv run python scripts/e2e_macos_click.py --preflight
uv run tgcc doctor --env cctg_test.env
uv run tgcc status --env cctg_test.env
uv run tgcc start --env cctg_test.env
uv run tgcc logs --env cctg_test.env --lines 100
```

Stop or restart as needed:

```bash
uv run tgcc stop --env cctg_test.env
uv run tgcc restart --env cctg_test.env
```

Run sanitized log scans:

```bash
uv run python scripts/e2e_log_scan.py --env cctg_test.env \
  --count sendChatAction \
  --count sendMessageDraft \
  --count setChatMenuButton \
  --count "Usage limit reached"
```

Finish with:

```bash
uv run python scripts/e2e_preflight.py --env cctg_test.env
uv run python scripts/e2e_log_scan.py --env cctg_test.env
uv run python scripts/validate_local.py
```

## Desktop Automation Notes

On macOS, run the CoreGraphics helper preflight before button-heavy batches:

```bash
uv run python scripts/e2e_macos_click.py --preflight
```

Use a dry run before every coordinate click after the Telegram window moves:

```bash
uv run python scripts/e2e_macos_click.py --app Telegram --x 140 --y 835 --dry-run
uv run python scripts/e2e_macos_click.py --app Telegram --x 140 --y 835
```

Coordinates are relative to the current Telegram window. Do not use this helper
for attachment uploads unless the file picker is visibly under control. Telegram
Desktop attachment menus can appear as separate small windows without stable
accessibility labels; image/photo/oversized upload rows may need manual
confirmation or a more scriptable GUI environment.

## Coverage Checklist

### Batch 0: Background Setup

- Dedicated bot token configured in ignored env.
- Admin and allowed user configured.
- Throwaway project exists outside repository.
- `tgcc doctor`, `status`, `start`, `logs`, `stop`, and `restart`.
- Startup evidence for `deleteWebhook`, `setMyCommands`, current permission
  mode, and absence of tracebacks.
- Optional dynamic command menu when `CLAUDE_COMMAND_MENU=true`.

### Batch 1: Private Chat Core

- `/start` and `/help`.
- Unauthorized user ignored or documented as unavailable.
- Direct prompt: status card first, `sendChatAction`, final answer separated.
- Final answer buttons: rerun, status, new session, copy result.
- Long answer pagination and copy fallback; no `Button_copy_text_invalid`.
- Safe error result.

### Batch 2: Run Controls And Queue

- Status details, compact view, filters, pagination, and run-card copy.
- Stop button during a long run and `/stop` while running/idle.
- Busy queue notices, queue drain order, queue full behavior.
- Result-card rerun while busy queues through the normal queue path.
- `/new` and `/clear` stop active work, reset session, and clear queue.

### Batch 3: Commands, ForceReply, Sessions

- `/status` with session/status copy buttons.
- `/resume` list, copy ID, take over, invalid UUID, no-session ForceReply.
- `/attach` compatibility alias and missing-args ForceReply.
- `/sessions` compatibility alias.
- `/run` ForceReply slash normalization.
- `/model`, `/model reset`, invalid model, ForceReply, and inline choices.
- `/effort`, `/effort reset`, invalid effort, no ForceReply, and inline choices.
- `/permissions`, `/permissions reset`, invalid permission, ForceReply, and
  inline choices.
- `/mode` compatibility alias.
- `/context`, `/usage`, `/cost`, and `/reload_skills`.
- `/commands refresh`, command copy, and command execution buttons.
- Expired callbacks and expired/empty/non-bot ForceReply where practical.

### Batch 4: Attachments And Groups

- `ATTACHMENT_MODE=path`, `copy-to-project`, and `reject`.
- Small text document, captioned document, photo, image document, oversized
  file, default attachment prompt with no caption, and download/size errors.
- Group ordinary message ignored.
- Group slash command addressed to the bot responds.
- Natural `@bot` mention tested only if BotFather privacy is temporarily
  disabled for the dedicated E2E bot.
- Reply-to-bot routing when manual selection is reliable.
- Group ForceReply command addressed to the bot.
- ForceReply token isolation across users covered by local regression; add real
  multi-account evidence only if another authorized Telegram account is
  available.

### Batch 5: Draft Preview And Mini App

- Default `TELEGRAM_DRAFT_PREVIEW=false` produces no `sendMessageDraft`.
- Enabled Draft Preview calls `sendMessageDraft` in private chats, suppresses it
  in groups, throttles/truncates by local regression, degrades on API errors,
  and still sends the normal final answer.
- Mini App optional dependency and invalid config behavior.
- Signed local Mini App API checks:

```bash
uv run --extra mini-app python scripts/e2e_mini_app_api.py --env cctg_test.env
```

- Real Telegram menu opens the Mini App through a temporary HTTPS tunnel.
- Visible actions: refresh, stop, new session, resume, set model, set effort,
  set permissions, rerun last prompt.
- Cleanup resets defaults:

```env
TELEGRAM_DRAFT_PREVIEW=false
TELEGRAM_MINI_APP_ENABLED=false
TELEGRAM_MINI_APP_PUBLIC_URL=
```

```bash
uv run python scripts/e2e_reset_telegram_menu.py --env cctg_test.env
```

## Known Boundaries

- Claude `Usage limit reached` is an external blocker for active-run rows. Wait
  for the user-facing reset time before retrying.
- Existing Telegram private chats can cache Mini App menu state. For E2E-only
  chats, it is acceptable to set a chat-specific Web App menu and reset it with
  `scripts/e2e_reset_telegram_menu.py`.
- BotFather privacy mode affects natural group mentions. Slash commands
  addressed to the bot work with privacy enabled; natural non-command mentions
  may require temporarily disabling privacy for the dedicated E2E bot.
- Telegram Desktop reply-to-old-bot-message and attachment upload flows can be
  automation-fragile. Record them separately from product defects when local
  regression covers the underlying route.

## Result Template

Create a dated result file only for substantial new full runs or releases. Keep
routine evidence in PR summaries or `project-memory.md`.

```markdown
# Telegram E2E Results: YYYY-MM-DD

Status: complete | blocked | partial

## Environment

- Dedicated test bot:
- Dedicated private chat and group:
- Env file ignored and chmod 600:
- Throwaway project outside repository:
- Mini App tunnel:
- Final validation:

## Coverage Summary

| Area | Status | Evidence |
| --- | --- | --- |
| Background/config | pass/fail/boundary | sanitized summary |
| Private-chat core | pass/fail/boundary | sanitized summary |
| Run controls/queue | pass/fail/boundary | sanitized summary |
| Commands/sessions | pass/fail/boundary | sanitized summary |
| Attachments | pass/fail/boundary | sanitized summary |
| Group chat | pass/fail/boundary | sanitized summary |
| Draft Preview | pass/fail/boundary | sanitized summary |
| Mini App | pass/fail/boundary | sanitized summary |

## Findings

- Fixed:
- New product defects:
- Evidence boundaries:

## Cleanup State

- Bot:
- Draft Preview:
- Mini App:
- Tunnel:
- Telegram menu buttons:
- BotFather privacy:
```

## Current Closure Status

As of the 2026-06-05 cleanup, the latest full coverage rerun found no open
confirmed product defects. Product bugs discovered in the first real-client pass
were fixed or mitigated; remaining rows are documented evidence boundaries
around Telegram Desktop upload automation, manual group reply selection, and
some Mini App visible WebView action combinations that are covered by the signed
local API helper.
