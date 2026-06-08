# 代码审查修复计划

**生成日期**: 2026-06-08
**项目版本**: 0.8.4
**审查发现**: 69 个问题（8 高危 + 27 中危 + 26 低危 + 8 信息）

---

## 📊 执行摘要

本计划将 69 个发现分为 4 个阶段，按优先级和依赖关系组织。预计总工作量：**15-20 个工作日**。

### 关键指标
- 🔴 **高危安全问题**: 1 个（群组授权绕过）
- 🟠 **高优先级重构**: 4 个（executor.run、bot_processing、bot.py、stderr 缓冲）
- 🟡 **架构改进**: 6 个（依赖注入、配置管理、状态持久化等）
- 🟢 **代码风格**: 12 个（docstring、类型注解、命名一致性等）
- ⚡ **性能优化**: 8 个（缓存、内存管理、I/O 优化）

---

## 🎯 阶段 1：安全加固（1-2 天）

**目标**: 修复所有高危安全问题，确保系统安全基线
**里程碑**: 安全审计通过

### 1.1 群组授权绕过修复 [HIGH]
**工作量**: 4 小时
**文件**: `bot_commands.py`, `bot.py`

**任务**:
- [ ] 在所有命令处理器添加 `_is_chat_allowed` 检查
  - `handle_new` (line 176)
  - `handle_clear` (line 185)
  - `handle_attach` (line 194)
  - `handle_resume` (line 203)
  - `handle_sessions` (line 274)
  - `handle_stop_command` (line 345)
  - `handle_status` (line 366)
  - `handle_mode` (line 431)
  - `handle_model` (line 470)
  - `handle_effort` (line 509)
  - `handle_permissions` (line 548)
- [ ] 添加单元测试验证未授权群组被拒绝
- [ ] 更新集成测试覆盖群组场景

**验收标准**:
```python
# 每个命令处理器都包含此模式
if not self._is_authorized(user_id):
    return
if not self._is_chat_allowed(chat_id, chat.type):
    return
```

### 1.2 增强 Sanitizer 覆盖 [MEDIUM]
**工作量**: 3 小时
**文件**: `sanitizer.py`, `tests/test_sanitizer.py`

**任务**:
- [ ] 放宽 Anthropic key 长度要求（19+ → 15+）
- [ ] 添加混合大小写环境变量模式
- [ ] 添加 AWS session token 模式
- [ ] 添加 OAuth token 模式
- [ ] 添加 SSH 指纹模式
- [ ] 编写测试用例覆盖新增模式

**代码示例**:
```python
_PATTERNS = [
    # 短格式 API key
    (re.compile(r"\b(sk|key|api)[-_][A-Za-z0-9][A-Za-z0-9_-]{15,}\b"), "***"),
    # 混合大小写环境变量
    (re.compile(r"([A-Za-z_]*(key|secret|token|password)[A-Za-z_]*\s*=\s*)\S+", re.IGNORECASE), r"\1***"),
    # AWS session token
    (re.compile(r"\b(aws_session_token|AWS_SESSION_TOKEN)\s*=\s*\S+"), "***"),
]
```

### 1.3 Session 所有权验证 [MEDIUM]
**工作量**: 4 小时
**文件**: `sessions.py`, `bot.py`

**任务**:
- [ ] 在 `ChatSessionStore` 添加 `session_owners: dict[str, int]` 映射
- [ ] 修改 `_normalize_session_id` 为 `normalize_and_validate_session_id(session_id, chat_id)`
- [ ] 在 `handle_resume` 和 `handle_mini_app_action` 使用新验证函数
- [ ] 记录 session 创建时的所有权
- [ ] 添加测试：用户 A 不能接管用户 B 的 session

### 1.4 错误消息脱敏 [LOW]
**工作量**: 2 小时
**文件**: `message_input.py`, `bot_processing.py`, `executor.py`

**任务**:
- [ ] `message_input.py:120-123` - 隐藏 OSError 详情
- [ ] `bot_processing.py:304` - 使用通用错误消息
- [ ] `executor.py:845` - 过滤路径信息
- [ ] 在 `sanitizer.py` 添加路径脱敏函数

**阶段 1 总计**: 13 小时（约 2 个工作日）

---

## 🏗️ 阶段 2：代码质量重构（4-5 天）

**目标**: 降低代码复杂度，提高可维护性和可测试性
**里程碑**: 代码覆盖率保持 85%+，圈复杂度降低 30%

### 2.1 重构 executor.py run 方法 [HIGH]
**工作量**: 1.5 天
**文件**: `executor.py`, `tests/test_executor.py`

**任务**:
- [ ] 提取 `_start_claude_process()` (50 行)
- [ ] 提取 `_process_event_loop()` (150 行)
- [ ] 提取 `_handle_system_event(event)` (30 行)
- [ ] 提取 `_handle_assistant_event(event)` (40 行)
- [ ] 提取 `_handle_tool_event(event)` (50 行)
- [ ] 提取 `_handle_usage_event(event)` (20 行)
- [ ] 提取 `_finalize_execution()` (30 行)
- [ ] 更新所有相关测试

**重构前后对比**:
```
Before: run() - 354 lines, complexity ~45
After:  run() - 60 lines, complexity ~8
        + 7 helper methods (avg 30 lines each)
```

### 2.2 重构 bot_processing.py _process_message [HIGH]
**工作量**: 1 天
**文件**: `bot_processing.py`, `tests/test_bot_processing.py`

**任务**:
- [ ] 提取 `_initialize_run(chat_id, user_id, prompt)` (40 行)
- [ ] 提取 `_setup_status_monitoring(run_view)` (50 行)
- [ ] 提取 `_execute_and_monitor(executor_params)` (60 行)
- [ ] 提取 `_handle_run_result(result, run_view)` (40 行)
- [ ] 提取 `_cleanup_and_drain_queue(chat_id)` (30 行)
- [ ] 更新测试覆盖所有子方法

### 2.3 提取重复的验证逻辑 [MEDIUM]
**工作量**: 0.5 天
**文件**: `executor.py`

**任务**:
- [ ] 创建通用函数 `_normalize_enum_value()`
- [ ] 重构 `normalize_permission_mode()` 使用通用函数
- [ ] 重构 `normalize_model()` 使用通用函数
- [ ] 重构 `normalize_effort()` 使用通用函数
- [ ] 添加单元测试

### 2.4 提取重复的设置处理方法 [MEDIUM]
**工作量**: 0.5 天
**文件**: `bot_commands.py`

**任务**:
- [ ] 创建通用方法 `_apply_setting_choice()`
- [ ] 重构 `_apply_permission_choice()`
- [ ] 重构 `_apply_model_choice()`
- [ ] 重至 `_apply_effort_choice()`

### 2.5 优化异常处理 [MEDIUM]
**工作量**: 0.5 天
**文件**: `executor.py`, `bot_processing.py`, `attachment_cleanup.py`

**任务**:
- [ ] `executor.py:753` - 精确捕获异常类型
- [ ] `bot_processing.py:302` - 按异常类型分类处理
- [ ] `attachment_cleanup.py:87` - 添加错误处理
- [ ] 创建自定义异常类（`AttachmentRejectedError` 等）

**阶段 2 总计**: 4 天

---

## 🚀 阶段 3：架构优化（5-7 天）

**目标**: 改善系统架构，提高扩展性和灵活性
**里程碑**: 依赖注入实现，模块解耦完成

### 3.1 引入依赖注入 [HIGH]
**工作量**: 2 天
**新文件**: `container.py`, `interfaces.py`

**任务**:
- [ ] 定义核心接口（Protocol）
  - `ExecutorInterface`
  - `SessionStoreInterface`
  - `ConfigProviderInterface`
- [ ] 创建 `ServiceContainer` 类
- [ ] 重构 `server.py` 使用容器
- [ ] 重构 `TGBot.__init__` 接受依赖
- [ ] 更新所有测试使用 mock 依赖

**架构图**:
```
ServiceContainer
├── config: RuntimeConfig
├── executor: ExecutorInterface
├── session_store: SessionStoreInterface
├── input_builder: TelegramInputBuilder
└── sanitizer: SanitizerInterface

TGBot(container: ServiceContainer)
```

### 3.2 重构 bot.py 为组合模式 [HIGH]
**工作量**: 2 天
**新文件**: `services/command_service.py`, `services/message_service.py`, `services/session_service.py`

**任务**:
- [ ] 创建 `CommandService` - 处理所有命令
- [ ] 创建 `MessageService` - 处理消息
- [ ] 创建 `SessionService` - 管理会话
- [ ] 创建 `AttachmentService` - 处理附件
- [ ] 重构 `TGBot` 为协调器（<200 行）
- [ ] 更新 `bot_app.py` 的处理器注册

**重构前后**:
```
Before: TGBot(527 lines, 30+ methods)
After:  TGBot(150 lines, 10 methods)
        + 4 service classes
```

### 3.3 统一配置管理 [MEDIUM]
**工作量**: 1 天
**新文件**: `config_manager.py`

**任务**:
- [ ] 创建 `ConfigurationManager` 类
- [ ] 集中所有验证逻辑（normalize_*）
- [ ] 支持多数据源（env、文件、CLI）
- [ ] 添加配置变更通知机制
- [ ] 迁移 `config.py` 逻辑

### 3.4 抽象状态持久化层 [MEDIUM]
**工作量**: 1.5 天
**新文件**: `repository.py`, `repositories/file_repository.py`

**任务**:
- [ ] 定义 `SessionRepository` 接口
- [ ] 实现 `FileSystemSessionRepository`
- [ ] 重构 `ChatSessionStore` 使用 Repository
- [ ] 添加序列化/反序列化层
- [ ] 为 Redis/Database 预留扩展点

### 3.5 命令注册框架 [MEDIUM]
**工作量**: 1 天
**新文件**: `command_registry.py`

**任务**:
- [ ] 创建 `CommandRegistry` 类
- [ ] 定义 `Command` 接口
- [ ] 支持装饰器注册
- [ ] 实现命令路由器
- [ ] 添加中间件支持（鉴权、日志、限流）

**阶段 3 总计**: 7.5 天

---

## ⚡ 阶段 4：性能优化与文档（2-3 天）

**目标**: 优化性能热点，补齐文档
**里程碑**: 性能提升 20%+，文档覆盖率 90%+

### 4.1 性能优化 [各 0.5 天]
