# Telegram E2E Findings

This file is the compact closure ledger for issues found during real Telegram
E2E testing. Detailed historical evidence is kept in git history; current test
procedure lives in `telegram-e2e.md`.

## Current Status

As of 2026-06-05:

- Open confirmed product defects: none.
- Fixed and verified product defects: F-001, F-002, F-006, F-010, and the
  ForceReply originator-user isolation fix.
- Mitigated and not reproduced in latest reruns: F-003.
- Setup or test-harness findings, not product defects: F-004, F-005, F-007,
  F-008, and F-009.

## Findings

| ID | Status | Summary | Current action |
| --- | --- | --- | --- |
| F-001 | Fixed and verified | Stop callback did not interrupt active runs because polling updates were serialized behind the active Claude run. | Keep concurrent-update and per-chat queue regression coverage. |
| F-002 | Fixed and verified | Busy queue prompts did not appear during active runs for the same update-serialization reason. | Keep queue notification and drain-order regression coverage. |
| F-003 | Mitigated | Intermittent `editMessageText` 400s during status updates. | Keep no-op status edits reduced and Telegram edit errors debug-only; capture text if it returns. |
| F-004 | Evidence boundary | Telegram Desktop automation did not reliably complete image/photo/oversized attachment uploads. | Local regression covers attachment routes; use manual upload confirmation or stronger GUI automation for future real-client evidence. |
| F-005 | Test-harness issue | Direct `getUpdates` while polling caused Telegram 409 conflicts and polluted logs. | Do not use `getUpdates` against a live polling instance. |
| F-006 | Fixed and verified | Mini App `Rerun Last` action errors were not visible in the WebView. | Keep WebView/action error handling and local Mini App API coverage. |
| F-007 | Client/setup behavior | Existing private chat did not immediately pick up the default Mini App menu. | Use chat-specific E2E menu only when needed, then reset with `scripts/e2e_reset_telegram_menu.py`. |
| F-008 | Telegram setup prerequisite | Natural group `@bot` mentions require BotFather privacy disabled. | Prefer slash commands in groups unless the operator intentionally disables privacy. |
| F-009 | Evidence boundary | Replying to an older bot message in Telegram Desktop was not reliable through automation. | Local routing regression covers the code path; manual client evidence can be added when practical. |
| F-010 | Fixed and verified | Malformed JSON to Mini App `/api/action` returned HTTP 500. | Keep `400 invalid_payload` behavior covered by `tests/test_web_console.py` and the Mini App API helper. |

## Verification Summary

- Real Telegram Desktop verified Stop, busy queue notifications, queue drain,
  result-card rerun while busy, expired result callbacks, status buttons,
  ForceReply UX, group slash/ForceReply, Draft Preview, and Mini App menu open.
- Local regression verifies long-message pagination/copy fallback, attachment
  edge cases, ForceReply originator-user isolation, callback expiry paths, and
  signed Mini App API actions.
- Final full local gate passed with `uv run python scripts/validate_local.py`
  after the fixes and E2E helper additions.
