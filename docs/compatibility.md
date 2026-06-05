# Compatibility Matrix

This matrix documents the support boundary for the `0.8.x` Alpha line. It is
not a promise that every dependency version or operating system variant is
fully covered; it is the compatibility target maintainers use when triaging
issues.

## Runtime Support

| Area | `0.8.x` Alpha status | Notes |
|------|----------------------|-------|
| Python 3.11 | Supported | Covered by CI. |
| Python 3.12 | Supported | Covered by CI. |
| Python 3.13 | Supported | Covered by CI. |
| macOS | Supported | Used for live Telegram + Claude Code smoke validation. |
| Linux | Supported | GitHub Actions runs on Ubuntu; self-hosted deployments should follow the same validation commands. |
| Windows | Best effort | Not a primary release target yet; owner-only permissions and process-tree behavior may differ. |

## External Tools

| Dependency | Expected state | Notes |
|------------|----------------|-------|
| Claude Code CLI | Installed and authenticated for the same local user that runs `tgcc`. | `tgcc` invokes the `claude` command directly and sends prompts through stdin. |
| Telegram Bot API | A dedicated BotFather token for each instance. | Temporary smoke-test tokens must be rotated or revoked before public release. |
| python-telegram-bot | `python-telegram-bot[job-queue]~=22.7`. | Managed through `pyproject.toml`. |
| Starlette/Uvicorn | Optional via `mini-app` extra. | Required only when `TELEGRAM_MINI_APP_ENABLED=true`. |
| uv | Recommended installer and development tool. | Use `uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"` for public Git installs. The latest tagged release is `v0.8.2`; record `tgcc --version` and the installed commit for repeatable deployments. CI and release automation pin workflow `UV_VERSION` to `0.11.17` before running frozen sync. |
| PyPI | Not published as of `0.8.2`. | Git installs are the documented public installation path. |

## Validation Baseline

Before treating a platform or dependency update as supported, run:

```bash
uv sync --extra dev --frozen
uv run python scripts/validate_local.py
```

Run `scripts/validate_local.py` for the full local validation ladder (pytest,
ruff check, mypy, ruff format check, and uv build).

## Support Boundary

- `tgcc` stores runtime state locally under `~/.tgcc/`; owner-only permissions
  are applied where the platform allows.
- `.env` files should stay out of git and use `0600` permissions on Unix-like
  systems.
- `ATTACHMENT_MODE=path|copy-to-project|reject` defines whether Telegram files
  stay in instance storage, are copied into the Claude project, or are rejected.
- `ATTACHMENT_RETENTION_DAYS` is optional; empty/0 disables automatic cleanup,
  and positive values prune old instance/project attachment copies at startup
  and daily while the bot is running.
- `.env.example` and `tgcc init` default to
  `CLAUDE_PERMISSION_MODE=bypassPermissions` for trusted local projects. Change
  it to `default` or `plan` before starting on untrusted/shared project
  directories. The active mode is visible in `/start`, `/status`, run cards, and
  startup/run logs.
- `CLAUDE_MODEL` and `/model` pass a Claude Code model alias or full model name
  to `--model`; empty values use the CLI default model.
- `CLAUDE_EFFORT` and `/effort` pass one of `low`, `medium`, `high`, `xhigh`,
  `max`, or `ultracode` to Claude Code `--effort`; empty values use the CLI
  default effort.
- `CLAUDE_CLI_RESUME_COMPAT=true` rewrites completed tgcc transcript
  `entrypoint` values from `sdk-cli` to `cli` so the local Claude Code
  `/resume` picker may show Telegram-started sessions. It is off by default
  because it edits Claude Code's private history files under `~/.claude`.
- `/permissions` sets a per-chat Claude Code `--permission-mode` override;
  `/permissions reset` restores the instance default.
- `CLAUDE_COMMAND_MENU` is disabled by default. Set it to `true` only when you
  want `tgcc` to probe Claude slash commands and cache Telegram menu entries.
  Users can still run `/commands` in Telegram to list pass-through Claude Code
  commands without publishing them to the Telegram menu.
- `TELEGRAM_DRAFT_PREVIEW` is disabled by default and only affects private
  chats when enabled.
- `TELEGRAM_MINI_APP_ENABLED` is disabled by default; enabling it requires the
  `mini-app` extra and an HTTPS `TELEGRAM_MINI_APP_PUBLIC_URL`.
