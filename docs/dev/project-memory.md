# Project Memory

Last updated: 2026-06-05.

This file is the handoff note for new maintainer or agent sessions. It captures
current product direction, recently completed work, and the next useful checks
without duplicating the longer architecture and user docs.

## Current Direction

`tgcc` is a local, self-hosted Telegram bridge for Claude Code CLI. Keep it
small and inspectable: Python package, direct CLI subprocess calls, local state
under `~/.tgcc/`, conservative permissions, and no cloud control plane.

The main UX direction is a useful Telegram operations surface, not a full
terminal clone. Telegram should show enough run progress to answer "what is it
doing now?" while keeping the final Claude answer separate and readable.

## Recent Milestone

The current head includes the Telegram run UI upgrade:

- `Executor.run(..., on_event=...)` emits `RunEvent` objects for tool start,
  tool result, assistant text, completion, and errors.
- `run_view.py` renders compact and expanded status cards with elapsed time,
  task summary, current tool, folded tool input/output detail, filters,
  pagination, copy, and Stop.
- `result_view.py`, `resume_view.py`, and `command_view.py` keep short
  process-local callback tokens for result actions, session pickers, and command
  pickers.
- `telegram_ui.py` centralizes Telegram HTML escaping and setting buttons.
- Final answers remain separate from the status card; text-only commands such
  as `/usage` should not duplicate the answer in the completed status card.
- Button-triggered commands and reruns enqueue through the normal queue path
  and now send a persistent queued message in addition to callback feedback.

The follow-up Telegram native UI work adds:

- `sendChatAction(typing)` heartbeat and periodic status-card heartbeat edits
  while Claude runs.
- ForceReply prompts for missing `/run`, `/resume`, `/model`, and
  `/permissions` arguments; `/effort` uses inline choices without opening a
  reply prompt.
- Opt-in `CLAUDE_CLI_RESUME_COMPAT` rewrites completed tgcc transcript
  `entrypoint` values from `sdk-cli` to `cli` so local Claude Code `/resume`
  may show Telegram-started sessions.
- Copy buttons for status, session IDs, and command picker rows.
- Default-off `TELEGRAM_DRAFT_PREVIEW` support for private-chat
  `sendMessageDraft` previews.
- Default-off Mini App console plumbing via optional Starlette/Uvicorn extras.

Validation after this milestone:

- `uv run python scripts/validate_local.py` passed with 714 tests and 90.28%
  coverage.
- Review feedback for the Telegram native UI milestone was fixed.
- A real Telegram E2E pass on 2026-06-04 covered private-chat UI, copy buttons,
  ForceReply, group chat, Draft Preview, and the optional Mini App. Results,
  runbook, and findings live under `docs/dev/e2e/`.
- The first E2E fix pass enabled concurrent Telegram update handling, kept
  per-chat run/queue serialization in local state, reduced no-op status-card
  edits, and surfaced Mini App action errors in the WebView.

## Important Boundaries

- Do not commit real bot tokens, chat IDs, `.env` files, runtime logs, or
  attachment caches.
- Telegram callback payloads must stay short. Use process-local stores with
  short tokens for large prompts, session IDs, and command names.
- Treat callback tokens as ephemeral. They may expire after restart or pruning;
  user-facing docs should tell users to rerun `/resume`, `/commands`, or resend
  the prompt when needed.
- Keep final answer pagination in `message_output.py`; status cards are for
  progress and recent tool detail, not full transcripts.
- Keep attachment behavior conservative. `copy-to-project` is useful when
  Claude Code default permissions cannot read instance-cache paths, but it
  writes into the project and should remain explicit.

## Telegram E2E Handoff

Before running a new full Telegram E2E session, read:

- `docs/dev/e2e/telegram-e2e.md`
- `docs/dev/e2e/telegram-e2e-findings.md`

Historical lessons from the 2026-06-04 run:

- Avoid direct Bot API `getUpdates` while the polling instance is active.
- Computer Use works well for Telegram buttons, ForceReply, and Mini App menu
  checks, but Telegram Desktop attachment preview and manual reply-to-old-bot
  message selection are fragile.
- Natural group `@bot` mentions require BotFather privacy disabled; group slash
  commands addressed to the bot work with privacy enabled.
- Real Mini App menu testing needs a temporary HTTPS tunnel and cleanup of
  default and chat-specific menu buttons.
- Computer Use uses the same Mac pointer, keyboard, and focused window as the
  user. Do not assume it can run Telegram Desktop UI checks invisibly in the
  background; use a separate VM/desktop for uninterrupted work.
- Keep E2E docs sanitized: no tokens, numeric Telegram IDs, full session IDs,
  private logs, local cache paths, or tunnel URLs.
- E2E secrets and temporary Mini App public URLs belong only in ignored root env
  files such as `cctg_test.env`; Telegram groups/BotFather settings live in
  Telegram, runtime logs live under `$HOME/.tgcc/`, and the throwaway Claude
  project should stay outside this repository via `CLAUDE_PROJECT_DIR`.

The follow-up full coverage rerun verified Mini App local API auth/action
checks and the real Telegram menu open path. During that pass,
`/api/action` malformed JSON returned HTTP 500; it is fixed in code and covered
by `tests/test_web_console.py`. ForceReply pending tokens are now scoped to the
originating user, with group isolation covered by `tests/test_bot.py`. The
reusable helpers
`scripts/e2e_preflight.py`, `scripts/e2e_prepare_assets.py`,
`scripts/e2e_macos_click.py`, `scripts/e2e_mini_app_api.py`,
`scripts/e2e_reset_telegram_menu.py`, and `scripts/e2e_log_scan.py` now run the
sanitized E2E env audit, synthetic upload and prompt asset prep, macOS
CoreGraphics click preflight/clicking, local Mini App API checks, Telegram Mini
App menu reset after tunnel tests, and E2E log scans without printing raw log
lines.
The later Telegram Desktop continuation verified keyboard-driven `/status`, a
seed final-result card, slow progress runs, result-card `状态`, expired
`重新执行`, and queued `重新执行` while busy through real Telegram Desktop. The
queued-rerun pass used the CoreGraphics click helper and showed the persistent
`已排队 (1/3)` message before the queued run drained and sent a final answer.
Remaining evidence gaps are limited to automation-fragile real-client cases and
are recorded in `docs/dev/e2e/telegram-e2e.md` and
`docs/dev/e2e/telegram-e2e-findings.md`.

## Documentation Handoff

The documentation set was consolidated on 2026-06-05. The project uses `docs/index.md` as the document map and ownership table. Keep future updates in the most specific owner document instead of
duplicating setup, security, or E2E details across multiple entry points.

Current high-level ownership:

- `README.md` is the Chinese landing page; `README.en.md` is the English
  landing page kept in parity with the Chinese one.
- `docs/quickstart.md` is the shortest first-run path; `docs/user-guide.md` is
  the source of truth for daily Telegram behavior and configuration.
- `docs/troubleshooting.md` handles symptom checks; `docs/operator-guide.md`
  handles long-running operations and incident response.
- `SECURITY.md` handles private reporting and deployment checklist;
  `docs/security-model.md` handles trust boundaries and controls.
- `docs/architecture.md` handles internal design; `docs/dev/e2e/telegram-e2e.md`
  and `docs/dev/e2e/telegram-e2e-findings.md` handle real Telegram test procedure
  and compact closure notes.
- `CHANGELOG.md` summarizes the 0.8.0 line; use git history for
  granular internal checkpoints.

## Useful Entry Points

- `src/claude_code_tg/executor.py` parses Claude `stream-json`, builds
  `ExecutionResult`, and emits `RunEvent`.
- `src/claude_code_tg/bot_processing.py` owns the run lifecycle: status card,
  queue drain, final answer, and result action buttons.
- `src/claude_code_tg/bot_commands.py` owns Telegram commands and callbacks.
- `src/claude_code_tg/run_view.py` owns status-card rendering and detail state.
- `src/claude_code_tg/sessions.py` owns session, queue, model, effort,
  permission, and `status.json` persistence.
- `docs/architecture.md` is the source of truth for design decisions.
- `docs/user-guide.md` is the source of truth for operator-facing Telegram
  behavior.

## Next Useful Work

- For future Telegram E2E, focus any manual desktop time on automation-fragile
  real-client rows: image/photo/oversized uploads, group reply-to-bot selection,
  and optional real multi-account ForceReply UX confirmation.
- Keep local helper coverage current for Mini App API actions, long-message
  pagination/copy fallback, attachment edge cases, and expired callback stores.
- Keep model/effort docs and `/model`/`/effort` behavior aligned with current
  Claude Code CLI behavior.
- Revisit README screenshots or GIFs only with sanitized assets.
- Avoid adding per-tool Telegram approval cards in the current Alpha line;
  that remains a non-goal unless the product direction changes.
