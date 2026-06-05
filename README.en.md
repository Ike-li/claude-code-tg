# tgcc - Control Claude Code from Telegram

[![CI](https://github.com/Ike-li/claude-code-tg/actions/workflows/ci.yml/badge.svg)](https://github.com/Ike-li/claude-code-tg/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](docs/compatibility.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](docs/compatibility.md)

English | [中文](README.md)

**Message Claude Code from your phone. It runs on your machine and sends results back to Telegram.**

Send command on Telegram → tgcc calls Claude Code CLI locally → Results delivered to Telegram

![tgcc Telegram smoke demo](docs/assets/tgcc-demo.svg)

---

## ⚡ Quick Start

```bash
# Install
uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"

# Configure (quick wizard: 3 essentials only; use tgcc init --full for every option)
tgcc init

# Start
tgcc start
```

Then message your bot in Telegram!

<details>
<summary>📋 What you need</summary>

- Python 3.11+
- `uv` package manager
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (authenticated)
- Telegram Bot Token (create via [@BotFather](https://t.me/BotFather))
- Your Telegram User ID (get from [@userinfobot](https://t.me/userinfobot))

</details>

---

## 💡 Why tgcc?

| What You Need | What tgcc Gives You |
|---------------|---------------------|
| 🏠 **Fully Local** | No cloud server needed, tokens and code stay on your machine |
| 📱 **Code from Phone** | Start tasks during commute, see results when you get home |
| 🎯 **Multi-Project** | One machine, multiple bots, each mapped to a different directory |
| 🔒 **Security Visible** | Auto-redacted logs, explicit permission modes, controlled file access |
| ⚙️ **Per-Chat Config** | Override model/effort/permissions for each conversation |

---

## 🎮 Common Usage

### Basic Telegram Commands

```
/new        - Start new Claude session
/resume     - Resume local Claude session
/stop       - Stop current execution
/status     - Check run status
/model opus - Switch to Opus model
/effort max - Maximum thinking effort
```

### Managing Multiple Bots Locally

```bash
# Check configuration before starting
tgcc doctor --env prod.env

# Check all instance statuses
tgcc status --all

# Batch start / stop / restart
tgcc start-all
tgcc stop-all
tgcc restart-all

# View specific instance logs
tgcc logs --env prod.env -f
```

---

## 📸 Features

<details>
<summary><b>📤 Send Files and Images</b></summary>

Three modes:
- `path` - Pass local file path to Claude (recommended)
- `copy-to-project` - Copy attachments to project directory
- `reject` - Disable file uploads

</details>

<details>
<summary><b>🎛️ Runtime Control</b></summary>

Each Telegram chat can independently set:
- Model (Opus / Sonnet / Haiku)
- Effort (low → ultracode)
- Permission mode (bypassPermissions / default / plan)

All settings visible in status cards and logs.

</details>

<details>
<summary><b>📊 Live Status Cards</b></summary>

During execution, shows editable status card with:
- Current tool being executed
- Elapsed time
- Permission mode and effort level
- Stop button

After completion, shows results with copy and re-run buttons.

</details>

---

## 🔐 Security Notes

⚠️ **Default permission mode is `bypassPermissions`** for trusted projects. Change to `default` or `plan` before starting if you don't fully control the project directory.

✅ **Best Practices:**
- Only add trusted users to `ALLOWED_USER_IDS`
- Keep `.env` files at `chmod 600` (init does this automatically)
- Regularly check logs to ensure redaction works
- Never commit real tokens to git

See [Security Policy](SECURITY.md) and [Security Model](docs/security-model.md) for details.

---

## 📚 Full Documentation

- **Quick Start**: [5-Minute Guide](docs/quickstart.md) - Shortest path
- **Daily Use**: [User Guide](docs/user-guide.md) - All config options and Telegram commands
- **Troubleshooting**: [Troubleshooting](docs/troubleshooting.md) - Symptom-based solutions
- **Long-Term Operation**: [Operator Guide](docs/operator-guide.md) - Log management, upgrades, incident response
- **Architecture**: [Architecture](docs/architecture.md) - Module structure and design decisions
- **Contributing**: [Contributing](CONTRIBUTING.md) - Local validation and PR workflow

Full documentation index: [Documentation Index](docs/index.md)

---

## 🚧 Current Status

This is `0.8.1` Alpha (tagged `v0.8.1`):

✅ **Implemented**: Text conversations, file input, multi-instance management, session resume, permission modes, queues, log redaction, CI

⏳ **Not Yet**: PyPI publishing (install via git for now)

Run full local validation:
```bash
uv run python scripts/validate_local.py
```

---

## 🤝 Contributing

Contributions welcome! Before submitting PRs:

```bash
uv sync --extra dev
uv run pytest --cov=claude_code_tg
uv run ruff check .
uv run --extra dev mypy
uv run ruff format --check .
```

See [Contributing Guide](CONTRIBUTING.md).

---

## 📄 License

MIT License - see [LICENSE](LICENSE)

---

## 🙋 Get Help

- Issues and feature requests: [GitHub Issues](https://github.com/Ike-li/claude-code-tg/issues)
- Security vulnerabilities: see [Security Policy](SECURITY.md)
- Usage questions: check [Troubleshooting](docs/troubleshooting.md) first

---

<sub>⚡ Built with Claude Code | 🤖 Powered by Anthropic Claude | 💬 Delivered via Telegram</sub>
