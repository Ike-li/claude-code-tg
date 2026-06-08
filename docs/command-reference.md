# TGCC 命令完整参考

**版本**: 0.8.x  
**更新日期**: 2026-06-08

---

## 📋 实例管理命令

### 🚀 启动实例

```bash
tgcc start [--env <path>]
```

**配置文件搜索优先级**（从高到低）：
1. `--env` 参数指定的路径
2. `DOTENV_PATH` 环境变量
3. 当前目录 `.env` 文件
4. `~/.tgcc/configs/default.env`

**示例**：
```bash
tgcc start                           # 自动搜索配置文件
tgcc start --env .env                # 指定配置文件
tgcc start --env project1            # 使用全局配置
tgcc start --env /path/to/.env       # 使用完整路径
```

### 🛑 停止实例

```bash
tgcc stop [--env <path>]
```

**示例**：
```bash
tgcc stop                            # 停止当前目录的实例
tgcc stop --env project1             # 停止指定实例
```

### 🔄 重启实例

```bash
tgcc restart [--env <path>]
```

### 📊 查看状态

```bash
tgcc status [--env <path>] [--all]
```

**示例**：
```bash
tgcc status                          # 查看当前实例
tgcc status --env project1           # 查看指定实例
tgcc status --all                    # 查看所有实例
```

### 📝 查看日志

```bash
tgcc logs [--env <path>] [-n <lines>] [-f]
```

**选项**：
- `-n, --lines <N>` - 显示最后 N 行（默认：50）
- `-f, --follow` - 实时跟踪日志

**示例**：
```bash
tgcc logs                            # 查看日志
tgcc logs -f                         # 实时跟踪
tgcc logs -n 100                     # 显示最后100行
tgcc logs --env project1 -f          # 跟踪指定实例
```

### 🖥️ 前台运行（调试模式）

```bash
tgcc foreground [--env <path>]
```

---

## 📦 批量操作命令

### 🚀 启动所有实例

```bash
tgcc start-all
```

启动当前目录下所有 `.env` 文件对应的实例。

### 🛑 停止所有实例

```bash
tgcc stop-all
```

### 🔄 重启所有实例

```bash
tgcc restart-all
```

---

## 🔧 配置和初始化命令

### 📝 初始化配置

```bash
tgcc init [--force]
```

**选项**：
- `--force` - 覆盖已存在的 `.env` 文件

**示例**：
```bash
tgcc init                            # 创建 .env 配置文件
tgcc init --force                    # 强制覆盖现有配置
```

---

## 📎 附件管理命令

### 🧹 清理附件

```bash
tgcc attachments prune [options]
```

**选项**：
- `--env <path>` - 指定实例
- `--all-envs` - 清理所有实例
- `--all-files` - 清理所有文件（忽略保留期）
- `--older-than <days>` - 只清理 N 天前的文件
- `--dry-run` - 模拟运行（不实际删除）
- `--scope <instance|project|both>` - 清理范围

**示例**：
```bash
tgcc attachments prune --older-than 7      # 清理7天前的附件
tgcc attachments prune --all-files         # 清理所有附件
tgcc attachments prune --dry-run           # 预览清理
tgcc attachments prune --all-envs          # 清理所有实例
```

---

## 🔍 诊断和健康检查命令

### 🏥 健康检查

```bash
tgcc doctor [options]
```

**选项**：
- `--env <path>` - 检查指定实例
- `--json` - 以 JSON 格式输出
- `--fix` - 自动修复权限问题

**示例**：
```bash
tgcc doctor                              # 检查当前实例
tgcc doctor --env project1               # 检查指定实例
tgcc doctor --fix                        # 检查并自动修复
tgcc doctor --json                       # JSON 格式输出
```

**检查项目**：
- ✓ `.env` 文件存在性和权限
- ✓ Claude CLI 安装状态
- ✓ 必需环境变量
- ✓ 文件权限（600）
- ✓ 符号链接检测

---

## ℹ️ 帮助和版本

### ❓ 帮助信息

```bash
tgcc --help                    # 显示主帮助
tgcc <command> --help          # 显示命令帮助
```

### 🏷️ 版本信息

```bash
tgcc --version                 # 显示版本号
```

---

## 📂 全局配置目录结构

```
~/.tgcc/
├── configs/                    # 配置文件目录
│   ├── default.env            # 默认配置
│   ├── project1.env           # 项目1配置
│   └── project2.env           # 项目2配置
│
├── instances/                  # 实例运行时目录
│   ├── <env-hash>/            # 按配置文件哈希命名
│   │   ├── tgcc.pid          # 进程ID
│   │   ├── tgcc.log          # 日志文件
│   │   ├── status.json       # 状态文件
│   │   └── attachments/      # 附件目录
│   └── ...
│
└── registry.json               # 实例注册表（新功能预留）
```

---

## 💡 常用场景示例

### 🎯 场景1：单项目使用（传统方式）

```bash
cd /path/to/myproject
tgcc init                      # 创建 .env
# 编辑 .env 配置
tgcc start                     # 启动
tgcc logs -f                   # 查看日志
tgcc stop                      # 停止
```

### 🎯 场景2：全局配置管理（推荐）

```bash
# 创建全局配置目录
mkdir -p ~/.tgcc/configs

# 为每个项目创建配置
cp /path/to/project1/.env ~/.tgcc/configs/project1.env
cp /path/to/project2/.env ~/.tgcc/configs/project2.env

# 在任意目录启动
tgcc start --env project1      # 启动项目1
tgcc start --env project2      # 启动项目2

# 查看状态
tgcc status --env project1
tgcc status --env project2
```

### 🎯 场景3：多实例管理

```bash
cd /workspace
ls *.env
# project1.env
# project2.env
# project3.env

tgcc start-all                 # 启动所有
tgcc status --all              # 查看所有状态
tgcc stop-all                  # 停止所有
```

### 🎯 场景4：调试模式

```bash
cd /path/to/project
tgcc foreground                # 前台运行，查看实时输出
# Ctrl+C 退出
```

### 🎯 场景5：日志分析

```bash
tgcc logs -n 100               # 查看最后100行
tgcc logs -f                   # 实时跟踪
tgcc logs --env project1 -n 50 # 查看指定实例的最后50行
```

### 🎯 场景6：附件清理

```bash
# 清理7天前的附件
tgcc attachments prune --older-than 7

# 预览清理（不实际删除）
tgcc attachments prune --older-than 7 --dry-run

# 清理所有附件
tgcc attachments prune --all-files

# 清理所有实例的附件
tgcc attachments prune --all-envs --older-than 7
```

### 🎯 场景7：健康检查和修复

```bash
# 检查配置
tgcc doctor

# 自动修复权限问题
tgcc doctor --fix

# JSON 格式输出（用于脚本）
tgcc doctor --json
```

---

## ⚙️ 环境变量

### DOTENV_PATH

指定配置文件路径：

```bash
export DOTENV_PATH=/path/to/.env
tgcc start
```

### TGCC_LOG_LEVEL

设置日志级别（DEBUG/INFO/WARNING/ERROR）：

```bash
export TGCC_LOG_LEVEL=DEBUG
tgcc foreground
```

---

## 🔒 安全注意事项

### ⚠️ .env 文件权限

```bash
chmod 600 .env                 # 仅所有者可读写
chmod 700 ~/.tgcc              # 全局配置目录
```

### ⚠️ 符号链接安全

tgcc 会拒绝包含符号链接的配置文件路径（防止安全攻击）。

### ⚠️ 敏感信息

- 不要将 `.env` 文件提交到 Git
- `.env` 应该在 `.gitignore` 中

---

## 🆘 故障排查

### 问题：tgcc start 失败

1. 运行 `tgcc doctor` 检查配置
2. 检查 `.env` 文件权限（应为 600）
3. 确认 Claude CLI 已安装（`claude --version`）
4. 查看日志：`tgcc logs`

### 问题：找不到配置文件

1. 检查当前目录是否有 `.env`
2. 使用 `--env` 参数明确指定
3. 或在 `~/.tgcc/configs/` 创建配置

### 问题：实例无法停止

1. 检查进程是否还在运行：`ps aux | grep tgcc`
2. 手动 kill：`kill <PID>`
3. 清理 PID 文件：`rm ~/.tgcc/instances/<hash>/tgcc.pid`

### 问题：日志文件过大

1. 使用附件清理：`tgcc attachments prune`
2. 手动轮转：`mv tgcc.log tgcc.log.old`

---

## 📚 相关文档

- [快速开始](quickstart.md)
- [运维指南](operator-guide.md)
- [架构文档](architecture.md)
- [全局配置设计](dev/global-config-multiinstance-design.md)
