# 阶段 4：性能优化与文档（续）

## 4.1 添加缓存机制 [MEDIUM]
**工作量**: 4 小时

### 4.1.1 Git 分支信息缓存
**文件**: `bot_processing.py`
- [ ] 创建 `BranchCache` 类（TTL 30 秒）
- [ ] 在 `project_branch_label()` 使用缓存
- [ ] 添加缓存失效机制

**实现**:
```python
class BranchCache:
    def __init__(self, ttl: int = 30):
        self._cache: dict[str, tuple[str, float]] = {}
        self._ttl = ttl
    
    def get(self, project_dir: str) -> str | None:
        if project_dir in self._cache:
            value, timestamp = self._cache[project_dir]
            if time.time() - timestamp < self._ttl:
                return value
        return None
    
    def set(self, project_dir: str, value: str):
        self._cache[project_dir] = (value, time.time())
```

### 4.1.2 Instance 元数据缓存
**文件**: `instance_store.py`
- [ ] 添加 memoization 装饰器
- [ ] 基于 `st_mtime` 失效缓存
- [ ] 测试批量操作性能提升

### 4.1.3 Session 元数据优化
**文件**: `claude_sessions.py`
- [ ] `_read_session_metadata()` 只读前 50 行
- [ ] 添加早期终止逻辑
- [ ] 为超大文件考虑反向读取

## 4.2 内存管理优化 [MEDIUM]
**工作量**: 4 小时

### 4.2.1 实现 LRU 淘汰
**文件**: `sessions.py`
- [ ] 添加 `max_chats` 配置（默认 1000）
- [ ] 跟踪每个 chat_id 的 `last_access_time`
- [ ] 实现 LRU 淘汰逻辑
- [ ] 定期清理 30 天不活跃的 chat

**实现**:
```python
from collections import OrderedDict

class ChatSessionStore:
    def __init__(self, max_chats: int = 1000):
        self.sessions = OrderedDict()  # LRU 顺序
        self.max_chats = max_chats
    
    def _access(self, chat_id: int):
        if chat_id in self.sessions:
            self.sessions.move_to_end(chat_id)
        if len(self.sessions) > self.max_chats:
            self.sessions.popitem(last=False)  # 移除最旧的
```

### 4.2.2 RunView 清理
**文件**: `run_view.py`, `bot_processing.py`
- [ ] 创建 `RunViewStore.cleanup()` 方法
- [ ] 删除 1 小时前完成的 RunView
- [ ] 添加定期清理任务（15 分钟）

### 4.2.3 优化 stderr 缓冲
**文件**: `executor.py`
- [ ] 使用 `collections.deque(maxlen=...)` 自动淘汰
- [ ] 或将超量 stderr 写入临时文件
- [ ] 限制内存峰值

## 4.3 I/O 优化 [LOW]
**工作量**: 3 小时

### 4.3.1 状态文件去抖
**文件**: `sessions.py`
- [ ] 添加 `dirty` 标记
- [ ] 实现定期 flush（5 秒）
- [ ] 保留关键操作的立即写入

### 4.3.2 附件清理单次遍历
**文件**: `attachments.py`
- [ ] 在第一次遍历时收集目录
- [ ] 按深度排序后删除
- [ ] 减少 50% 文件系统操作

### 4.3.3 Session 重写优化
**文件**: `claude_sessions.py`
- [ ] `rewrite_session_entrypoint_for_cli_resume()` 只读前 100 行
- [ ] 发现无需修改时跳过写入
- [ ] 添加性能日志

## 4.4 文档补充 [各 0.5-1 小时]
**总工作量**: 1 天

### 4.4.1 代码文档
- [ ] 为 `Executor.run()` 添加详细 docstring
- [ ] 为 `BotMessageProcessor._process_message()` 添加 docstring
- [ ] 为所有 CLI 命令函数添加 docstring
- [ ] 为 dataclass 字段添加说明（`RunEvent`, `ExecutionResult`, `ClaudeRuntimeStatus`）
- [ ] 在 `__init__.py` 添加包级文档
- [ ] 为 `sanitizer.py` 的 regex 模式添加注释

### 4.4.2 用户文档
- [ ] 在 `docs/user-guide.md` 添加"多实例场景"章节
- [ ] 添加附件模式 + 保留交互表格
- [ ] 扩展 `docs/troubleshooting.md` 添加 MCP 服务器调试
- [ ] 添加 Windows 特定说明（`docs/compatibility.md`）
- [ ] 创建 `docs/migration.md`（0.8.3 → 0.8.4）

### 4.4.3 开发文档
- [ ] 扩展 `docs/architecture.md` 添加错误处理哲学
- [ ] 在 `CONTRIBUTING.md` 添加文档变更指南
- [ ] 扩展 `docs/security-model.md` 添加威胁模型
- [ ] 考虑生成 API 参考（Sphinx/pdoc3）

## 4.5 代码风格统一 [LOW]
**工作量**: 3 小时

- [ ] 定义所有魔法数字为常量
  - `STDOUT_BUFFER_SIZE_BYTES = 1024 * 1024`
  - `STATUS_UPDATE_THROTTLE_SECONDS = 2.0`
  - `MAX_TG_MESSAGE_LENGTH = 4000`
- [ ] 统一命名风格（`_runtime_str` vs `_runtime_text`）
- [ ] 为缺少 docstring 的工具函数添加说明
- [ ] 统一参数列表（考虑配置对象）
- [ ] 添加类型注解到内部辅助函数

**阶段 4 总计**: 2.5 天

---

## 📅 时间表总览

| 阶段 | 目标 | 工作量 | 开始 | 结束 | 里程碑 |
|------|------|--------|------|------|--------|
| **阶段 1** | 安全加固 | 2 天 | Day 1 | Day 2 | 安全审计通过 |
| **阶段 2** | 代码质量重构 | 4 天 | Day 3 | Day 6 | 覆盖率 85%+，复杂度↓30% |
| **阶段 3** | 架构优化 | 7.5 天 | Day 7 | Day 14 | 依赖注入实现 |
| **阶段 4** | 性能与文档 | 2.5 天 | Day 15 | Day 17 | 性能↑20%，文档 90%+ |
| **缓冲** | 测试与调整 | 3 天 | Day 18 | Day 20 | - |

**总计**: 15-20 个工作日（3-4 周）

---

## 🎯 关键里程碑

### M1: 安全基线达成（Day 2）
- ✅ 所有高危安全问题修复
- ✅ Sanitizer 覆盖增强
- ✅ Session 所有权验证实现
- ✅ 安全测试套件通过

### M2: 代码质量提升（Day 6）
- ✅ executor.py 和 bot_processing.py 重构完成
- ✅ 圈复杂度降低 30%
- ✅ 代码覆盖率保持 85%+
- ✅ 所有重复逻辑消除

### M3: 架构现代化（Day 14）
- ✅ 依赖注入容器实现
- ✅ bot.py 拆分为服务
- ✅ 配置管理统一
- ✅ 状态持久化抽象化

### M4: 生产就绪（Day 17）
- ✅ 性能提升 20%+
- ✅ 文档覆盖率 90%+
- ✅ API 参考文档生成
- ✅ 迁移指南完成

### M5: 发布准备（Day 20）
- ✅ 所有测试通过
- ✅ CI/CD 绿色
- ✅ 变更日志更新
- ✅ 版本号升级（0.9.0）

---

## 📊 风险评估

### 高风险
1. **阶段 3 架构重构** - 可能引入回归
   - **缓解**: 保持高测试覆盖，分小步提交
   
2. **bot.py 拆分** - 影响面大
   - **缓解**: 先写集成测试，确保行为一致

### 中风险
3. **依赖注入引入** - 学习曲线
   - **缓解**: 使用简单的自建容器，避免重量级框架

4. **性能优化** - 可能无明显效果
   - **缓解**: 先分析热点，后优化，添加性能测试

### 低风险
5. **文档补充** - 时间压力
   - **缓解**: 代码文档优先，用户文档可延后

---

## 🔄 迭代策略

### 每阶段结束后
1. 运行完整测试套件
2. 执行 `uv run python scripts/validate_local.py`
3. 手动烟雾测试关键功能
4. 更新 CHANGELOG.md
5. 提交 PR 并代码审查

### 持续集成
- 每次提交触发 CI
- 保持测试覆盖率不下降
- ruff/mypy 检查通过
- 性能基准不退化

---

## 📝 交付物清单

### 代码
- [ ] 所有 69 个问题修复完成
- [ ] 测试覆盖率 ≥ 85%
- [ ] 所有 lint 检查通过
- [ ] 性能提升 20%+

### 文档
- [ ] `docs/dev/code-review-action-plan.md`（本文档）
- [ ] `docs/migration.md`（迁移指南）
- [ ] `docs/api/`（API 参考）
- [ ] 更新 `docs/architecture.md`
- [ ] 更新 `docs/user-guide.md`
- [ ] 更新 `CHANGELOG.md`

### 测试
- [ ] 新增单元测试（100+ 个用例）
- [ ] 新增集成测试（20+ 个场景）
- [ ] 性能基准测试
- [ ] 安全测试套件

---

## 🚀 快速启动

### 立即开始阶段 1
```bash
# 1. 创建功能分支
git checkout -b fix/security-hardening

# 2. 开始修复群组授权绕过
# 编辑 src/claude_code_tg/bot_commands.py

# 3. 运行测试
uv run pytest tests/test_bot_commands.py -v

# 4. 提交
git add src/claude_code_tg/bot_commands.py tests/
git commit -m "fix(security): add defense-in-depth chat authorization checks

- Add _is_chat_allowed check to all command handlers
- Prevent bypass if chat_gate fails
- Add tests for unauthorized group scenarios

Fixes code review finding: 群组授权绕过风险"
```

### 跟踪进度
使用 GitHub Issues/Projects 或本地 TODO：
- [ ] 阶段 1：安全加固（2/13 小时）
  - [x] 1.1 群组授权绕过修复
  - [ ] 1.2 增强 Sanitizer 覆盖
  - [ ] 1.3 Session 所有权验证
  - [ ] 1.4 错误消息脱敏

---

**生成时间**: 2026-06-08  
**负责人**: 项目维护者  
**审查人**: 待定  
**下次复审**: 阶段 1 完成后
