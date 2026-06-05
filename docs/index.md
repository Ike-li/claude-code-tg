# Documentation Index

Use this page as the project doc front door. Start with the shortest path that
matches what you are doing; avoid scanning every file.

## Document Roles

Use this table to decide where a future update belongs.

| File | Role |
| --- | --- |
| [README](../README.md) | Chinese landing page: positioning, minimum setup, core commands, and doc map. |
| [README.en.md](../README.en.md) | Short English entry point that sends readers into the full docs. |
| [Quickstart](quickstart.md) | Fresh install to first Telegram prompt; keep it short. |
| [User Guide](user-guide.md) | Source of truth for day-to-day Telegram behavior, commands, config, attachments, Draft Preview, and Mini App usage. |
| [Troubleshooting](troubleshooting.md) | Symptom-based checks before opening an issue. |
| [Operator Guide](operator-guide.md) | Long-running instance operation, upgrades, retention, and incident response. |
| [Compatibility Matrix](compatibility.md) | Supported Python, OS, install, dependency, and Alpha support boundaries. |
| [Security Policy](../SECURITY.md) | Private vulnerability reporting and deployment checklist. |
| [Security Model](security-model.md) | Trust boundaries, protected assets, controls, and limitations. |
| [Architecture](architecture.md) | Internal design, module boundaries, and tradeoffs. |
| [Roadmap](roadmap.md) | Current priorities, Beta exit criteria, and non-goals. |
| [Telegram E2E Guide](e2e/telegram-e2e.md) | Real-client Telegram E2E runbook and coverage checklist. |
| [Telegram E2E Findings](e2e/telegram-e2e-findings.md) | Compact closure ledger for E2E issues and harness limits. |
| [Project Memory](project-memory.md) | Current handoff notes for maintainer or agent sessions. |
| [Contributing](../CONTRIBUTING.md) | Contribution path, validation commands, and PR expectations. |
| [Maintainers](../MAINTAINERS.md) | Release owner, maintainer-only actions, and triage expectations. |
| [Changelog](../CHANGELOG.md) | Release-line summary; not a replacement for git history. |
| [Support](../SUPPORT.md) | Public help boundary and safe issue-reporting expectations. |
| [Code of Conduct](../CODE_OF_CONDUCT.md) | Community behavior and conduct-reporting rules. |

When content could fit more than one document, prefer the most specific owner
above and link to it from broader entry points instead of duplicating details.
Avoid adding new historical or one-off test docs; update the E2E guide,
findings ledger, changelog, or project memory as appropriate.

## Start Here

- New install: [5-Minute Quickstart](quickstart.md)
- Daily use: [User Guide](user-guide.md)
- Something failed: [Troubleshooting](troubleshooting.md)
- Long-running bot operation: [Operator Guide](operator-guide.md)
- Security boundary or private reporting: [Security Policy](../SECURITY.md)
  and [Security Model](security-model.md)
- English overview: [README.en.md](../README.en.md)

## Product Context

- [README](../README.md) — positioning, minimum setup, core commands, and doc
  map.
- [Compatibility Matrix](compatibility.md) — supported Python versions,
  operating systems, install paths, and Alpha support boundaries.
- [Roadmap](roadmap.md) — Alpha priorities, Beta exit criteria, and current
  non-goals.

## Maintainers And Contributors

- [Contributing](../CONTRIBUTING.md) — repository map, validation commands, and
  contribution path.
- [Architecture](architecture.md) — CLI invocation model, sessions,
  attachments, module boundaries, and tradeoffs.
- [Project Memory](project-memory.md) — current direction, recent milestones,
  and handoff notes for new maintainer or agent sessions.
- [Maintainers](../MAINTAINERS.md) — maintainer authority, release-owner duties,
  and escalation paths.
- [Changelog](../CHANGELOG.md) — notable changes by release line.

## Specialized Notes

- [Telegram E2E Guide](e2e/telegram-e2e.md) — real-client coverage checklist,
  helper commands, Mini App tunnel cleanup, and evidence rules.
- [Telegram E2E Findings](e2e/telegram-e2e-findings.md) — compact closure ledger
  for issues and test-harness boundaries found during real Telegram testing.
