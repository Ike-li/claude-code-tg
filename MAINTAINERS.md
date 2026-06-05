# Maintainers

`tgcc` is currently maintained as a small Alpha project. This file documents
release ownership, maintainer-only actions, and triage expectations.

## Current Maintainer

- @Ike-li is the current maintainer and release owner for the `0.8.x` Alpha
  line.

The maintainer owns repository settings, security-response routing, and final
merge or tag decisions. Sensitive boundaries should follow
[.github/CODEOWNERS](.github/CODEOWNERS).

## Maintainer-Only Actions

These actions require maintainer authority and should not be assigned as first
contributor tasks:

- rotating or revoking BotFather smoke tokens
- enabling GitHub private vulnerability reporting or Issues
- changing branch protection, rulesets, repository variables, or release tags
- syncing repository labels or profile metadata
- handling private vulnerability or conduct reports
- publishing release artifacts

## Release Stewardship

Before announcing a public Alpha release, the release owner should:

- run `uv run python scripts/validate_local.py` from a clean checkout
- verify release notes, package metadata, and public docs point to current
  behavior
- rotate or revoke any temporary BotFather token used for smoke testing
- keep release-machine secrets and local paths out of public issues, release
  notes, logs, screenshots, and summaries

## Triage Expectations

This is an Alpha project, so maintainer response is best effort. Issues are
easier to review when reporters use the templates and include sanitized version
and environment context.

Move suspected vulnerabilities to [SECURITY.md](SECURITY.md) and conduct
concerns to [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Public issues should not
include tokens, private chat transcripts, unsanitized logs, local filesystem
paths, exploit details, or conduct incident details.

## Adding Maintainers

Add a maintainer only after they have demonstrated sustained, careful review
judgment in the project. Update this file, [.github/CODEOWNERS](.github/CODEOWNERS),
repository permissions, and release documentation in the same change.
