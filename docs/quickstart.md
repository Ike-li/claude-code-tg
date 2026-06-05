# 5 分钟快速开始

**目标**：从零到第一条 Telegram 消息让 Claude Code 执行。

---

## Step 1: 检查前置条件 (1 分钟)

在终端运行这些命令，确保都能正常输出：

```bash
python3 --version    # 需要 3.11 或更高
uv --version         # 包管理器
claude --version     # Claude Code CLI
```

如果 `claude` 命令不存在或未认证，先完成：
```bash
# 安装 Claude Code（如果还没有）
# 然后认证
claude auth login
```

---

## Step 2: 获取 Telegram 凭证 (2 分钟)

### 2.1 创建 Bot 并获取 Token

1. 在 Telegram 搜索并打开 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot`
3. 按提示设置 Bot 名称和用户名
4. **复制** BotFather 给你的 token（一串数字+冒号+字母数字组合）

### 2.2 获取你的 User ID

1. 在 Telegram 搜索并打开 [@userinfobot](https://t.me/userinfobot)
2. 发送任意消息
3. **复制**它回复的数字 ID（一串数字）

---

## Step 3: 安装并配置 (1 分钟)

```bash
# 安装 tgcc
uv tool install "git+https://github.com/Ike-li/claude-code-tg.git"

# 进入你想让 Claude 操作的项目目录
cd /path/to/your/project

# 运行配置向导
tgcc init
```

`tgcc init` 会问你：
- **Bot Token**: 粘贴 Step 2.1 的 token
- **Admin User IDs**: 粘贴 Step 2.2 的数字 ID
- **Allowed User IDs**: 直接回车（默认和 Admin 相同）
- **Project Directory**: 直接回车（默认是当前目录）
- **Permission Mode**: 直接回车（默认 `bypassPermissions`，适合个人可信项目）

---

## Step 4: 启动并测试 (1 分钟)

```bash
# 检查配置
tgcc doctor

# 启动 Bot
tgcc start

# 确认运行状态
tgcc status
```

看到 `Status: Running` 就成功了！

---

## Step 5: 在 Telegram 使用

1. 在 Telegram 搜索你刚创建的 Bot（用户名）
2. 打开对话，发送 `/start`
3. 试试发一条指令：

```
帮我看看这个项目的 README，总结一下主要功能
```

Bot 会显示一个状态卡，然后返回 Claude 的回答 🎉

---

## 🎯 常用命令速查

```bash
# === Telegram 里 ===
/new              新会话
/resume           恢复会话
/stop             停止执行
/status           查看状态
/model opus       切换模型
/effort max       最大思考强度

# === 本地终端 ===
tgcc status       查看运行状态
tgcc logs -f      实时查看日志
tgcc stop         停止 Bot
tgcc restart      重启 Bot
```

---

## ❌ 遇到问题？

### Bot 不回复

```bash
# 检查是否在运行
tgcc status

# 查看最近日志
tgcc logs -n 50

# 确认你的 User ID 在白名单里
cat .env | grep ALLOWED_USER_IDS
```

### "claude: command not found"

```bash
# 安装并认证 Claude Code CLI
# 访问：https://docs.anthropic.com/en/docs/claude-code
```

### "Already running"

```bash
# 先停止，再启动
tgcc stop
tgcc start
```

### 权限相关错误

在 `.env` 中修改：
```env
CLAUDE_PERMISSION_MODE=default  # 或 plan，更严格
```

然后重启：
```bash
tgcc restart
```

---

## 📖 下一步

- **发送文件**：直接在 Telegram 发图片/文档，Claude 就能读取
- **多项目管理**：每个项目目录创建独立 `.env`，用 `--env` 参数区分
- **高级配置**：阅读 [用户指南](user-guide.md) 了解所有选项

**完整文档**: [Documentation Index](index.md)

---

<sub>💡 提示：用 `tgcc doctor --strict` 做部署前检查，它会把警告也当作错误</sub>
