# Documentation Index

Use this page as the project doc front door. Pick the shortest path that matches
what you are doing; you do not need to read every file.

## Start Here

- **New install:** [5-Minute Quickstart](quickstart.md)
- **Daily use:** [User Guide](user-guide.md) — source of truth for commands,
  config, attachments, Draft Preview, and Mini App
- **Something failed:** [Troubleshooting](troubleshooting.md)
- **Running long-term:** [Operator Guide](operator-guide.md)
- **Security boundary / reporting:** [Security Policy](../SECURITY.md) and
  [Security Model](security-model.md)

## All Documents

### For users

| File | Role |
| --- | --- |
| [README](../README.md) / [README.en](../README.en.md) | Landing page: positioning, minimum setup, core commands, doc map (zh/en parity). |
| [Quickstart](quickstart.md) | Fresh install to first Telegram prompt. |
| [User Guide](user-guide.md) | Day-to-day Telegram behavior, commands, config, attachments, Mini App. |
| [Troubleshooting](troubleshooting.md) | Symptom-based checks before opening an issue. |
| [Operator Guide](operator-guide.md) | Long-running operation, upgrades, retention, incident response. |
| [Compatibility Matrix](compatibility.md) | Supported Python, OS, install, and dependency boundaries. |
| [Security Policy](../SECURITY.md) | Private vulnerability reporting and deployment checklist. |
| [Support](../SUPPORT.md) | Public help boundary and safe issue-reporting expectations. |
| [Changelog](../CHANGELOG.md) | Release-line summary; not a replacement for git history. |

### For contributors and maintainers

| File | Role |
| --- | --- |
| [Contributing](../CONTRIBUTING.md) | Contribution path, validation commands, PR expectations. |
| [Architecture](architecture.md) | Internal design, module boundaries, and tradeoffs. |
| [Security Model](security-model.md) | Trust boundaries, protected assets, controls, limitations. |
| [Roadmap](roadmap.md) | Current priorities, Beta exit criteria, and non-goals. |
| [Maintainers](../MAINTAINERS.md) | Release owner, maintainer-only actions, triage expectations. |
| [Code of Conduct](../CODE_OF_CONDUCT.md) | Community behavior and conduct-reporting rules. |
| [dev/project-memory.md](dev/project-memory.md) | Handoff notes for maintainer or agent sessions. |
| [dev/e2e/](dev/e2e/telegram-e2e.md) | Real-client Telegram E2E runbook and closure ledger. |

When content could fit more than one document, prefer the most specific owner
above and link to it from broader entry points instead of duplicating details.
Avoid adding new historical or one-off test docs; update the E2E runbook,
findings ledger, changelog, or project memory as appropriate.
