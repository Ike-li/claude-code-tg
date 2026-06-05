---
name: Feature request
about: Suggest a focused improvement for tgcc
title: "[Feature]: "
labels: enhancement, needs triage
assignees: ""
---

## Problem

What user problem should this solve?

## Proposed behavior

Describe the smallest useful behavior that would solve it.

## Why this fits tgcc

tgcc is intentionally a lightweight, self-hosted Claude Code Telegram manager.
Explain how the feature supports that positioning.

## Environment / scope

If this depends on setup, include safe non-secret context.

- tgcc version or commit (if known): run `tgcc --version`, or include the exact commit
- Install method: `uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"` / `uv tool install -e .` / `uv sync` / not applicable
- Runtime area: Telegram bot / CLI / docs / release process / other

## Alternatives considered

What workaround or different approach did you consider?

## Acceptance checks

- [ ] Documentation updated
- [ ] Tests or smoke steps included
- [ ] Security/privacy impact considered
- [ ] No tokens, chat transcripts, unsanitized logs, local filesystem paths, or private chat content included
