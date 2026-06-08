# 快速参考：代码审查修复手册

**适用版本**: 0.8.4  
**目标读者**: 开发者、维护者

---

## 🚀 立即开始

```bash
# 1. 查看完整修复计划
cat docs/dev/code-review-action-plan.md

# 2. 查看优先级矩阵
cat docs/dev/priority-matrix.md

# 3. 开始第一个修复
git checkout -b fix/security-hardening
```

---

## 📋 快速索引

| 问题分类 | 数量 | 最高优先级 | 文档链接 |
|---------|------|-----------|---------|
| 🔒 安全 | 7 | P0 | [阶段 1](#阶段-1-安全加固) |
| ✨ 质量 | 18 | P1 | [阶段 2](#阶段-2-代码质量重构) |
| 🏗️ 架构 | 10 | P1 | [阶段 3](#阶段-3-架构优化) |
| ⚡ 性能 | 12 | P1 | [阶段 4](#阶段-4-性能优化) |
| 🧪 测试 | 4 | P2 | 见测试覆盖章节 |
| 📚 文档 | 12 | P3 | [阶段 4](#阶段-4-文档补充) |

---

## 🎯 按时间规划

### 如果只有 1 天
**修复 P0（安全关键）**：
1. 群组授权绕过（4h）
2. Sanitizer 增强（3h）
3. 错误消息脱敏（2h）

**命令**:
```bash
git checkout -b fix/critical-security
# 修复后运行
uv run pytest tests/test_bot_commands.py tests/test_sanitizer.py -v
```

### 如果有 1 周
**P0 + P1 高危（安全+质量）**：
- Day 1-2: 安全加固（4 项）
- Day 3-4: Executor 重构
- Day 5: bot_processing 重构

### 如果有 1 月
**完整 4 阶段计划**：
- Week 1: 安全加固
- Week 2-3: 代码质量重构
- Week 4-5: 架构优化
- Week 6+: 性能与文档

---

## 🔥 Top 10 必修项

### 1. 群组授权绕过 [P0]
```bash
文件: src/claude_code_tg/bot_commands.py
时间: 4 小时
测试: tests/test_bot_commands.py
```

**快速修复**:
```python
# 在每个 handle_* 方法开头添加
async def handle_new(self, update, context):
    resolved = _message_context(update)
    if resolved is None:
        return
    user_id, chat_id, message = resolved
    chat = update.effective_chat
    
    # 添加这两行检查
    if not self._is_authorized(user_id):
        return
    if not self._is_chat_allowed(chat_id, chat.type if chat else None):
        return
    # 继续处理...
```

### 2. Sanitizer 增强 [P1]
```bash
文件: src/claude_code_tg/sanitizer.py
时间: 3 小时
测试: tests/test_sanitizer.py
```

**修改**:
```python
# Line 8: 放宽长度要求 19+ → 15+
(re.compile(r"\b(sk|key|api)[-_][A-Za-z0-9][A-Za-z0-9_-]{15,}\b"), "***"),

# 添加新模式
(re.compile(r"([A-Za-z_]*(key|secret|token|password)[A-Za-z_]*\s*=\s*)\S+", re.IGNORECASE), r"\1***"),
(re.compile(r"\b(aws_session_token|AWS_SESSION_TOKEN)\s*=\s*\S+"), "***"),
```

### 3. Session 所有权验证 [P1]
```bash
文件: src/claude_code_tg/sessions.py, bot.py
时间: 4 小时
测试: tests/test_sessions.py
```

**添加**:
```python
# sessions.py
class ChatSessionStore:
    def __init__(self, ...):
        self.session_owners: dict[str, int] = {}  # session_id -> chat_id
    
    def normalize_and_validate_session_id(self, session_id: str, chat_id: int) -> str | None:
        try:
            normalized = str(uuid.UUID(session_id.strip()))
        except (AttributeError, ValueError):
            return None
        
        # 检查所有权
        owner = self.session_owners.get(normalized)
        if owner is not None and owner != chat_id:
            return None  # 属于其他 chat
        
        self.session_owners[normalized] = chat_id  # 记录所有权
        return normalized
```

### 4-10. 其他高优先级项
见 `docs/dev/code-review-action-plan.md` 详细说明。

---

## 🛠️ 常用命令

### 开发流程
```bash
# 创建分支
git checkout -b fix/issue-description

# 运行相关测试
uv run pytest tests/test_module.py -v

# 运行完整验证
uv run python scripts/validate_local.py

# 检查覆盖率
uv run pytest --cov=claude_code_tg --cov-report=term-missing

# 代码格式化
uv run ruff format .

# 类型检查
uv run mypy

# 提交
git add .
git commit -m "fix(category): description

- Detail 1
- Detail 2

Fixes: #issue-number"
```

### 调试
```bash
# 查看审查结果
cat /private/tmp/claude-501/.../tasks/wbdzxkh1w.output

# 运行特定测试
uv run pytest tests/test_bot_app.py::test_chat_gate -v

# 启动 bot 测试
tgcc start --env test.env
```

---

## 📊 进度跟踪

### 使用本地 TODO
```bash
# 在项目根目录创建
cat > CODE_REVIEW_PROGRESS.md << 'EOF'
# 代码审查修复进度

## 阶段 1: 安全加固 [0/4]
- [ ] 群组授权绕过
- [ ] Sanitizer 增强
- [ ] Session 所有权
- [ ] 错误消息脱敏

## 阶段 2: 代码质量 [0/5]
- [ ] Executor.run 重构
- [ ] bot_processing 重构
- [ ] normalize_* 提取
- [ ] _apply_* 提取
- [ ] 异常处理优化

## 阶段 3: 架构优化 [0/5]
- [ ] 依赖注入
- [ ] bot.py 拆分
- [ ] 配置管理
- [ ] 状态持久化
- [ ] 命令注册

## 阶段 4: 性能文档 [0/8]
- [ ] Git 分支缓存
- [ ] Instance 元数据缓存
- [ ] LRU 淘汰
- [ ] RunView 清理
- [ ] Stderr 优化
- [ ] I/O 优化
- [ ] 文档补充
- [ ] 代码风格
EOF
```

### 使用 GitHub Issues
```bash
# 创建里程碑
gh api repos/:owner/:repo/milestones -f title="Code Review Fixes" -f description="..."

# 批量创建 Issues
# 见 scripts/create_review_issues.sh（需要创建）
```

---

## 📖 相关文档

| 文档 | 用途 |
|------|------|
| `code-review-action-plan.md` | 完整修复计划（4 阶段） |
| `priority-matrix.md` | 优先级评分和排序 |
| `CODE_REVIEW_PROGRESS.md` | 进度跟踪（自建） |
| `CHANGELOG.md` | 记录所有变更 |

---

## 💡 最佳实践

### 修复前
1. ✅ 阅读问题描述和推荐方案
2. ✅ 查看相关代码上下文
3. ✅ 运行现有测试，确保通过
4. ✅ 理解问题根因

### 修复中
1. ✅ 小步提交，频繁测试
2. ✅ 为每个修复编写/更新测试
3. ✅ 保持代码风格一致
4. ✅ 添加必要的注释和 docstring

### 修复后
1. ✅ 运行完整测试套件
2. ✅ 执行 `validate_local.py`
3. ✅ 手动烟雾测试
4. ✅ 更新文档和 CHANGELOG
5. ✅ 提交 PR 并请求审查

---

## 🚨 注意事项

### 避免的陷阱
1. ❌ 一次修复太多问题（单个 PR 应聚焦 1-3 个相关问题）
2. ❌ 跳过测试（每个修复都需要测试验证）
3. ❌ 忽略回归风险（运行完整测试套件）
4. ❌ 破坏现有 API（保持向后兼容）

### 处理冲突
- **阶段 3 依赖阶段 2** - 先完成 executor/bot_processing 重构，再引入依赖注入
- **架构重构影响测试** - 先完善集成测试，确保行为不变
- **性能优化可能引入复杂性** - 先测量，后优化，保持简单

---

## 🤝 寻求帮助

### 如果遇到困难
1. 查看原始审查报告（`tasks/wbdzxkh1w.output`）
2. 参考相关测试用例
3. 查阅 `docs/architecture.md`
4. 在 GitHub Issues 提问

### 代码审查
- 每个 PR 应由另一位开发者审查
- 重点关注：安全性、测试覆盖、向后兼容

---

**最后更新**: 2026-06-08  
**维护者**: 项目团队
