# Session 所有权验证修复总结

**日期**: 2026-06-08  
**优先级**: P1 (High Security)  
**状态**: ✅ 已完成并测试

---

## 📋 问题描述

### 安全问题
- **严重程度**: 中危 (Medium)
- **分类**: Authorization / Session Hijacking
- **影响范围**: 所有使用 /resume 或 Mini App 的用户

### 根本原因
`_normalize_session_id` 方法只验证 UUID 格式，不检查所有权：

1. **缺少所有权跟踪** - 没有记录哪个 session 属于哪个 chat
2. **无跨用户验证** - 用户 A 可以通过 `/resume <uuid>` 接管用户 B 的 session
3. **Mini App 同样脆弱** - Mini App 的 resume action 也不验证所有权

**攻击场景**：
- 用户 A 使用 `/status` 查看自己的 session UUID
- 用户 B（如果能看到或猜到 UUID）可以用 `/resume <uuid>` 接管
- 用户 B 就能看到用户 A 的对话历史和继续操作

---

## ✅ 修复内容

### 1. 添加所有权跟踪

在 `ChatSessionStore` 中添加映射：
```python
# sessions.py
class ChatSessionStore:
    def __init__(self, ...):
        self.session_owners: dict[str, int] = {}  # session_id -> chat_id
```

### 2. 记录所有权

在所有设置 session 的地方记录所有权：

**attach_session**:
```python
def attach_session(self, chat_id: int, session_id: str) -> None:
    old_session = self.sessions.get(chat_id)
    if old_session and old_session != session_id:
        self.session_owners.pop(old_session, None)  # 移除旧的
    self.sessions[chat_id] = session_id
    self.session_owners[session_id] = chat_id  # 记录新的
```

**set_session_if_current**:
```python
def set_session_if_current(self, chat_id: int, session_id: str, expected_version: int) -> bool:
    if self.session_versions.get(chat_id, 0) != expected_version:
        return False
    self.sessions[chat_id] = session_id
    self.session_owners[session_id] = chat_id  # 记录所有权
    return True
```

**reset_chat**:
```python
def reset_chat(self, chat_id: int) -> int:
    old_session = self.sessions.pop(chat_id, None)
    if old_session:
        self.session_owners.pop(old_session, None)  # 移除所有权
```

**restore_sessions**:
```python
self.sessions[int(chat_id_str)] = canonical
self.session_owners[canonical] = int(chat_id_str)  # 恢复所有权
```

### 3. 添加验证方法

```python
def normalize_and_validate_session_id(
    self, session_id: str, chat_id: int
) -> str | None:
    """验证 UUID 格式和所有权。
    
    返回 None 如果：
    - UUID 格式无效
    - Session 属于其他 chat
    """
    try:
        normalized = str(uuid.UUID(session_id.strip()))
    except (AttributeError, ValueError):
        return None

    # 检查所有权
    owner_chat_id = self.session_owners.get(normalized)
    if owner_chat_id is not None and owner_chat_id != chat_id:
        return None  # 属于其他 chat，拒绝

    return normalized
```

### 4. 更新调用点

**bot.py**:
```python
def _normalize_and_validate_session_id(
    self, session_id: str, chat_id: int
) -> str | None:
    return self.state.normalize_and_validate_session_id(session_id, chat_id)

# Mini App
if action == "resume":
    session_id = self._normalize_and_validate_session_id(
        str(payload.get("session_id", "")), chat_id
    )
    if not session_id:
        return {"ok": False, "error": "invalid_session_id_or_unauthorized"}
```

**bot_commands.py**:
```python
async def _attach_session_id(self, chat_id: int, message: Message, raw_session_id: str) -> None:
    session_id = self._normalize_and_validate_session_id(raw_session_id, chat_id)
    if not session_id:
        await message.reply_text(
            "无效的 session_id 或该 session 属于其他 chat。"
        )
        return
```

---

## 🧪 测试验证

### 新增测试 (10 个)

1. `test_normalize_and_validate_new_session` - 验证未拥有的 session
2. `test_normalize_and_validate_owned_by_same_chat` - 同一 chat 可验证自己的 session
3. `test_normalize_and_validate_owned_by_different_chat` - 其他 chat 不能验证 ⭐
4. `test_normalize_and_validate_invalid_uuid` - 拒绝无效 UUID
5. `test_attach_session_records_ownership` - attach 记录所有权
6. `test_attach_session_transfers_ownership` - attach 新 session 转移所有权
7. `test_reset_chat_removes_ownership` - reset 移除所有权
8. `test_restore_sessions_records_ownership` - 恢复时记录所有权
9. `test_set_session_if_current_records_ownership` - set_session 记录所有权
10. `test_multiple_chats_different_sessions` - 多 chat 各自拥有不同 session

### 测试结果
```
✅ 新增测试: 10/10 通过
✅ 完整测试套件: 808/808 通过 (+10)
✅ ruff 检查: 通过
```

---

## 📊 改进效果

### 修复前风险
- **Session Hijacking**: 用户可猜测或窃取其他用户的 session UUID
- **隐私泄露**: 用户 B 可看到用户 A 的对话历史
- **操作劫持**: 用户 B 可以用户 A 的身份继续对话

### 修复后
- ✅ 每个 session 只属于一个 chat
- ✅ 跨用户接管被阻止
- ✅ 所有权在重启后持久化
- ✅ 向后兼容（首次验证的 session 自动获得所有权）

---

## 📝 代码变更

### 文件修改
- `src/claude_code_tg/sessions.py`: +44 行
- `src/claude_code_tg/bot.py`: +21 行
- `src/claude_code_tg/bot_commands.py`: +9 行
- `tests/test_session_ownership.py`: +260 行（新文件）

### 提交信息
```
f443faa fix(security): add session ownership validation
```

---

## 🔒 安全影响

### 修复前
```
User A: session_123 → Chat A
User B: /resume session_123 → ✅ 成功（不安全！）
结果: User B 劫持了 User A 的 session
```

### 修复后
```
User A: session_123 → Chat A（所有权记录）
User B: /resume session_123 → ❌ 拒绝（"该 session 属于其他 chat"）
结果: User B 无法劫持
```

---

## 🎯 设计决策

### 为什么不使用 user_id？
使用 `chat_id` 而非 `user_id` 作为所有者，因为：
1. Telegram 群组中多用户共享同一 chat_id
2. 一个用户可能在多个私聊/群组使用 bot
3. chat_id 是 bot 的自然隔离边界

### 首次验证自动获得所有权
未拥有的 session 在首次验证时自动获得所有权，因为：
1. 向后兼容 - 不破坏现有的本地 session
2. 用户体验 - 不需要额外步骤
3. 安全性 - 一旦拥有，其他 chat 就无法接管

### 所有权持久化
通过 `restore_sessions` 恢复所有权，因为：
1. bot 重启后所有权不丢失
2. 防止重启后的劫持窗口
3. 与现有的 session 持久化机制一致

---

## ✅ 验收标准

所有验收标准已达成：

- [x] 在 ChatSessionStore 添加 session_owners 映射
- [x] 修改 normalize 方法验证所有权
- [x] 在 attach、set、reset、restore 记录/移除所有权
- [x] 在 handle_resume 使用新验证
- [x] 在 Mini App resume action 使用新验证
- [x] 添加跨用户访问测试
- [x] 所有测试通过 (808/808)

---

## 📈 后续建议

1. **审计日志** - 记录 session 验证失败的尝试
2. **监控告警** - 检测频繁的劫持尝试
3. **用户通知** - 当 session 被其他人尝试接管时通知用户
4. **Session 过期** - 考虑添加 session TTL 机制

---

**完成时间**: 2026-06-08  
**总耗时**: 约 2 小时  
**影响**: ✅ Session 劫持风险消除，用户隐私得到保护
