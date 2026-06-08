# 阶段 3 架构优化 - 启动指南

**日期**: 2026-06-08  
**状态**: 准备中  
**预计工作量**: 5-7 天

---

## 📋 前置条件检查

### ✅ 已完成
- [x] 阶段 1：安全加固（4/4 任务完成）
- [x] 阶段 2：代码质量重构（主要任务完成）
- [x] 测试覆盖：91/91 测试通过（100%）
- [x] 代码审查：核心模块已重构

### 📊 当前状态
- **bot.py**: 541 行，40 个方法
- **executor.py**: 已重构（91 行主方法 + 6 个辅助方法）
- **bot_processing.py**: 部分重构（212 行）
- **架构**: 单体结构，紧耦合

---

## 🎯 阶段 3 目标

**总目标**: 改善系统架构，提高扩展性和灵活性

### 核心改进
1. **依赖注入** - 解耦组件依赖
2. **服务化拆分** - TGBot 541 行 → ~150 行
3. **统一配置** - 集中配置管理
4. **抽象持久化** - 支持多种存储后端
5. **命令框架** - 可扩展的命令系统

---

## 📝 任务清单

### 3.1 引入依赖注入 [HIGH] - 2 天

**目标**: 创建服务容器，定义核心接口

#### 步骤 1: 定义核心接口 (0.5 天)

创建 `src/claude_code_tg/interfaces.py`：

```python
from typing import Protocol, runtime_checkable
from collections.abc import Awaitable

@runtime_checkable
class ExecutorInterface(Protocol):
    """Claude CLI 执行器接口"""
    async def run(
        self,
        prompt: str,
        chat_id: int,
        session_id: str | None = None,
        **kwargs
    ) -> ExecutionResult: ...
    
    async def stop(self, chat_id: int) -> bool: ...

@runtime_checkable
class SessionStoreInterface(Protocol):
    """会话存储接口"""
    def get_session(self, chat_id: int) -> str | None: ...
    def set_session(self, chat_id: int, session_id: str) -> None: ...
    def clear_session(self, chat_id: int) -> None: ...

@runtime_checkable
class ConfigProviderInterface(Protocol):
    """配置提供者接口"""
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
```

**验证**:
```bash
python -c "from claude_code_tg.interfaces import ExecutorInterface; print('OK')"
```

#### 步骤 2: 创建服务容器 (0.5 天)

创建 `src/claude_code_tg/container.py`：

```python
from dataclasses import dataclass
from typing import Any

from claude_code_tg.executor import Executor
from claude_code_tg.sessions import ChatSessionStore
from claude_code_tg.interfaces import (
    ExecutorInterface,
    SessionStoreInterface,
    ConfigProviderInterface,
)

@dataclass
class ServiceContainer:
    """依赖注入容器，持有所有服务实例"""
    
    executor: ExecutorInterface
    session_store: SessionStoreInterface
    config_provider: ConfigProviderInterface
    project_dir: str
    timeout: int
    
    @classmethod
    def create_default(
        cls,
        project_dir: str = ".",
        timeout: int = 300,
        **config_overrides: Any,
    ) -> "ServiceContainer":
        """创建默认配置的容器"""
        from claude_code_tg.config import SimpleConfigProvider
        
        executor = Executor()
        session_store = ChatSessionStore()
        config_provider = SimpleConfigProvider(config_overrides)
        
        return cls(
            executor=executor,
            session_store=session_store,
            config_provider=config_provider,
            project_dir=project_dir,
            timeout=timeout,
        )
```

**验证**:
```bash
uv run pytest tests/test_container.py -v
```

#### 步骤 3: 重构 TGBot 构造函数 (0.5 天)

修改 `src/claude_code_tg/bot.py`：

```python
class TGBot(BotMessageProcessor, BotCommandHandlers):
    def __init__(
        self,
        token: str,
        admin_ids: set[int],
        allowed_ids: set[int],
        container: ServiceContainer,  # 新增：注入容器
        **legacy_args,  # 向后兼容
    ):
        # 如果传入了 legacy_args，构建容器
        if legacy_args:
            container = ServiceContainer.create_default(**legacy_args)
        
        self.container = container
        self.executor = container.executor
        self.state = container.session_store
        # ...
```

**验证**:
```bash
uv run pytest tests/test_bot.py -v
```

#### 步骤 4: 更新 server.py (0.5 天)

修改 `src/claude_code_tg/server.py`：

```python
from claude_code_tg.container import ServiceContainer

def run_bot(config: RuntimeConfig) -> None:
    container = ServiceContainer.create_default(
        project_dir=config.project_dir,
        timeout=config.timeout,
        permission_mode=config.permission_mode,
        model=config.model,
        effort=config.effort,
    )
    
    bot = TGBot(
        token=config.token,
        admin_ids=config.admin_ids,
        allowed_ids=config.allowed_ids,
        container=container,
    )
    
    bot.run()
```

**验证**:
```bash
# 手动测试启动
uv run python -m claude_code_tg.server --help
```

---

### 3.2 重构 bot.py 为组合模式 [HIGH] - 2 天

**目标**: 将 TGBot (541 行) 拆分为多个服务类

#### 当前 TGBot 的职责分析

通过分析 40 个方法，可以分为以下职责：

1. **命令处理** (15+ 个命令方法)
   - `/start`, `/new`, `/session`, `/stop`, `/status`, etc.
   
2. **消息处理** (来自 BotMessageProcessor)
   - `_process_message`
   - `_drain_queue`
   
3. **会话管理**
   - `_get_or_create_session`
   - `_restore_sessions`
   - Session 相关的 getters/setters
   
4. **附件处理**
   - `_attachment_cleanup_roots`
   - `_run_attachment_retention_cleanup`
   
5. **配置管理**
   - `_effective_permission_mode`
   - `_effective_model`
   - `_effective_effort`
   
6. **权限校验**
   - `_is_authorized`
   - `_is_chat_allowed`
   
7. **状态记录**
   - `_write_status`
   - `_record_periodic_status`

#### 步骤 1: 创建 CommandService (0.5 天)

创建 `src/claude_code_tg/services/command_service.py`：

```python
class CommandService:
    """处理所有 Telegram 命令"""
    
    def __init__(self, bot: "TGBot"):
        self.bot = bot
    
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        # 移动自 bot.py 的 _handle_start
        ...
    
    async def handle_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /new 命令"""
        # 移动自 bot.py 的 _handle_new
        ...
    
    # ... 其他命令
```

#### 步骤 2: 创建 MessageService (0.5 天)

创建 `src/claude_code_tg/services/message_service.py`：

```python
class MessageService:
    """处理消息和队列"""
    
    def __init__(self, container: ServiceContainer):
        self.container = container
        self.executor = container.executor
        self.session_store = container.session_store
    
    async def process_message(self, chat_id: int, user_id: int, prompt: str, ...):
        """处理单个消息"""
        # 移动自 bot_processing.py 的 _process_message
        ...
    
    async def drain_queue(self, chat_id: int, ...):
        """排空消息队列"""
        # 移动自 bot_processing.py 的 _drain_queue
        ...
```

#### 步骤 3: 创建 SessionService (0.5 天)

创建 `src/claude_code_tg/services/session_service.py`：

```python
class SessionService:
    """管理会话状态"""
    
    def __init__(self, session_store: SessionStoreInterface):
        self.session_store = session_store
    
    def get_or_create_session(self, chat_id: int) -> tuple[str | None, bool]:
        """获取或创建会话"""
        ...
    
    def restore_sessions(self, project_dir: str):
        """从磁盘恢复会话"""
        ...
```

#### 步骤 4: 创建 AttachmentService (0.5 天)

创建 `src/claude_code_tg/services/attachment_service.py`：

```python
class AttachmentService:
    """处理附件上传和清理"""
    
    def __init__(self, attachment_dir: Path, max_bytes: int, retention_days: float):
        self.attachment_dir = attachment_dir
        self.max_bytes = max_bytes
        self.retention_days = retention_days
    
    def cleanup_roots(self) -> list[tuple[str, Path]]:
        """返回需要清理的根目录"""
        ...
    
    def run_retention_cleanup(self) -> tuple[int, int, int]:
        """执行保留期清理"""
        ...
```

#### 步骤 5: 重构 TGBot 为协调器 (目标 <200 行)

修改 `src/claude_code_tg/bot.py`：

```python
class TGBot:
    """Bot 协调器 - 组合各个服务"""
    
    def __init__(
        self,
        token: str,
        admin_ids: set[int],
        allowed_ids: set[int],
        container: ServiceContainer,
    ):
        self.token = token
        self.admin_ids = admin_ids
        self.allowed_ids = allowed_ids
        self.container = container
        
        # 组合服务
        self.commands = CommandService(self)
        self.messages = MessageService(container)
        self.sessions = SessionService(container.session_store)
        self.attachments = AttachmentService(...)
    
    def _is_authorized(self, user_id: int) -> bool:
        """简单的权限校验"""
        return user_id in self.admin_ids or user_id in self.allowed_ids
```

**重构前后对比**:
```
Before: TGBot (541 lines, 40 methods)
After:  TGBot (~150 lines, ~10 methods)
        + CommandService (~150 lines)
        + MessageService (~100 lines)
        + SessionService (~50 lines)
        + AttachmentService (~50 lines)
```

---

### 3.3 统一配置管理 [MEDIUM] - 1 天

**目标**: 创建统一的配置管理系统

#### 步骤 1: 创建 ConfigurationManager (0.5 天)

创建 `src/claude_code_tg/config_manager.py`：

```python
class ConfigurationManager:
    """统一配置管理"""
    
    def __init__(self):
        self._config: dict[str, Any] = {}
        self._validators: dict[str, Callable] = {}
        self._listeners: list[Callable] = []
    
    def register_validator(self, key: str, validator: Callable):
        """注册配置验证器"""
        self._validators[key] = validator
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """设置配置值（带验证）"""
        if key in self._validators:
            value = self._validators[key](value)
        self._config[key] = value
        self._notify_listeners(key, value)
    
    def subscribe(self, listener: Callable):
        """订阅配置变更"""
        self._listeners.append(listener)
```

#### 步骤 2: 迁移 normalize_* 函数 (0.5 天)

将 `executor.py` 中的验证函数移动到 ConfigurationManager：

```python
class ConfigurationManager:
    def __init__(self):
        super().__init__()
        # 注册内置验证器
        self.register_validator("permission_mode", normalize_permission_mode)
        self.register_validator("model", normalize_model)
        self.register_validator("effort", normalize_effort)
```

---

### 3.4 抽象状态持久化层 [MEDIUM] - 1.5 天

**目标**: 为会话存储创建抽象层，支持多种后端

#### 步骤 1: 定义 Repository 接口 (0.5 天)

创建 `src/claude_code_tg/repository.py`：

```python
from typing import Protocol

class SessionRepository(Protocol):
    """会话持久化接口"""
    
    def save(self, chat_id: int, session_id: str) -> None: ...
    def load(self, chat_id: int) -> str | None: ...
    def delete(self, chat_id: int) -> None: ...
    def list_all(self) -> dict[int, str]: ...
```

#### 步骤 2: 实现 FileSystemSessionRepository (0.5 天)

创建 `src/claude_code_tg/repositories/file_repository.py`：

```python
class FileSystemSessionRepository:
    """基于文件系统的会话存储"""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
    
    def save(self, chat_id: int, session_id: str) -> None:
        """保存会话到文件"""
        ...
    
    def load(self, chat_id: int) -> str | None:
        """从文件加载会话"""
        ...
```

#### 步骤 3: 重构 ChatSessionStore (0.5 天)

修改 `src/claude_code_tg/sessions.py`：

```python
class ChatSessionStore:
    def __init__(self, repository: SessionRepository | None = None):
        self.repository = repository or FileSystemSessionRepository(...)
        self._sessions: dict[int, str] = {}
    
    def get_session(self, chat_id: int) -> str | None:
        # 优先从内存读取
        if chat_id in self._sessions:
            return self._sessions[chat_id]
        # 降级到持久化层
        return self.repository.load(chat_id)
```

---

### 3.5 命令注册框架 [MEDIUM] - 1 天

**目标**: 创建可扩展的命令系统

#### 步骤 1: 创建 CommandRegistry (0.5 天)

创建 `src/claude_code_tg/command_registry.py`：

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class Command:
    name: str
    handler: Callable
    description: str
    admin_only: bool = False

class CommandRegistry:
    """命令注册表"""
    
    def __init__(self):
        self._commands: dict[str, Command] = {}
    
    def register(
        self,
        name: str,
        description: str,
        admin_only: bool = False,
    ):
        """装饰器：注册命令"""
        def decorator(handler: Callable):
            self._commands[name] = Command(
                name=name,
                handler=handler,
                description=description,
                admin_only=admin_only,
            )
            return handler
        return decorator
    
    def get(self, name: str) -> Command | None:
        return self._commands.get(name)
```

#### 步骤 2: 使用装饰器注册命令 (0.5 天)

修改 CommandService：

```python
class CommandService:
    def __init__(self, bot: "TGBot"):
        self.bot = bot
        self.registry = CommandRegistry()
        self._register_commands()
    
    def _register_commands(self):
        """注册所有命令"""
        
        @self.registry.register("start", "开始使用")
        async def start(update, context):
            await self.handle_start(update, context)
        
        @self.registry.register("new", "新建会话", admin_only=True)
        async def new(update, context):
            await self.handle_new(update, context)
```

---

## 🧪 测试策略

### 单元测试
- `tests/test_container.py` - ServiceContainer
- `tests/test_interfaces.py` - 接口定义
- `tests/test_command_service.py` - 命令服务
- `tests/test_message_service.py` - 消息服务
- `tests/test_session_service.py` - 会话服务
- `tests/test_attachment_service.py` - 附件服务
- `tests/test_config_manager.py` - 配置管理
- `tests/test_repository.py` - 存储抽象

### 集成测试
- `tests/integration/test_bot_with_container.py` - Bot + 容器
- `tests/integration/test_end_to_end.py` - 端到端

### 回归测试
确保所有现有的 91 个测试继续通过。

---

## 📈 预期收益

### 架构改进
- **解耦**: 组件之间通过接口通信
- **可测试**: 可以轻松 mock 依赖
- **可扩展**: 新增服务无需修改 TGBot
- **可维护**: 每个服务职责单一

### 代码质量
- **TGBot**: 541 → ~150 行（-72%）
- **模块化**: 4 个独立服务类
- **复用**: 配置、存储抽象可复用

### 未来扩展
- 支持 Redis 会话存储
- 支持数据库持久化
- 支持多 Bot 实例
- 支持插件系统

---

## ⚠️ 风险和注意事项

### 高风险点
1. **向后兼容性**: 必须保持现有 API 不变
2. **测试覆盖**: 每次拆分后必须验证所有测试通过
3. **渐进式重构**: 不要一次性修改太多

### 缓解策略
1. **并行保留旧接口**: 在过渡期支持两种初始化方式
2. **频繁测试**: 每完成一个步骤就运行完整测试套件
3. **小步提交**: 每个独立变更立即提交

---

## 📚 参考资料

### 设计模式
- **依赖注入**: Martin Fowler - Inversion of Control Containers
- **Repository 模式**: Domain-Driven Design
- **Service 层模式**: Patterns of Enterprise Application Architecture

### Python 最佳实践
- **Protocol**: PEP 544 - Structural Subtyping
- **dataclass**: PEP 557 - Data Classes
- **Type Hints**: PEP 484, 585, 604

---

## 🚀 下一步行动

### 立即开始
```bash
# 1. 创建新分支
git checkout -b feat/phase3-architecture

# 2. 创建接口文件
touch src/claude_code_tg/interfaces.py

# 3. 开始编写 Protocol 定义
code src/claude_code_tg/interfaces.py

# 4. 运行测试
uv run pytest -v
```

### 会话建议
由于阶段 3 工作量大，建议分多个会话完成：
- **会话 1**: 任务 3.1 - 依赖注入
- **会话 2**: 任务 3.2 前半 - 创建服务类
- **会话 3**: 任务 3.2 后半 - 重构 TGBot
- **会话 4**: 任务 3.3 + 3.4 - 配置和存储
- **会话 5**: 任务 3.5 - 命令框架

---

## 📝 续接 Prompt

当开始下一个会话时，使用：

```
继续阶段 3 架构优化。

当前进度：
- 阶段 1（安全加固）：✅ 完成
- 阶段 2（代码质量）：✅ 核心任务完成
- 阶段 3（架构优化）：准备开始

下一个任务：3.1 引入依赖注入
- 创建 interfaces.py（定义 Protocol）
- 创建 container.py（ServiceContainer）
- 重构 TGBot 构造函数
- 更新 server.py

参考文档：docs/dev/phase3-kickoff.md
```
