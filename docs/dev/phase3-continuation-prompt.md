# 阶段 3 架构优化 - 续接 Prompt

## 🎯 立即开始

```
继续阶段 3 架构优化 - 任务 3.1 依赖注入。

## 当前状态
- ✅ 阶段 1（安全加固）：完成（4/4 任务）
- ✅ 阶段 2（代码质量）：核心完成（Executor.run -75%）
- 📋 阶段 3（架构优化）：开始任务 3.1
- ✅ 所有 815 个测试通过

## 任务 3.1: 引入依赖注入（2 天）

### 目标
创建服务容器和核心接口，为模块解耦奠定基础。

### 步骤 1: 定义核心接口（0.5 天）

创建 `src/claude_code_tg/interfaces.py`，定义以下 Protocol：

**ExecutorInterface** - Claude CLI 执行器接口
```python
@runtime_checkable
class ExecutorInterface(Protocol):
    async def run(
        self,
        prompt: str,
        chat_id: int,
        session_id: str | None = None,
        project_dir: str = ".",
        timeout: int = 300,
        permission_mode: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        cli_resume_compat: bool = False,
        on_event: Callable[[RunEvent], Awaitable[None]] | None = None,
    ) -> ExecutionResult: ...
    
    async def stop(self, chat_id: int) -> bool: ...
    async def shutdown(self) -> None: ...
```

**SessionStoreInterface** - 会话存储接口
```python
@runtime_checkable
class SessionStoreInterface(Protocol):
    def get_session(self, chat_id: int) -> str | None: ...
    def set_session(self, chat_id: int, session_id: str) -> None: ...
    def set_session_if_current(
        self, chat_id: int, session_id: str, version: int
    ) -> None: ...
    def clear_session(self, chat_id: int) -> None: ...
    def session_version(self, chat_id: int) -> int: ...
```

**ConfigProviderInterface** - 配置提供者接口
```python
@runtime_checkable
class ConfigProviderInterface(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def has(self, key: str) -> bool: ...
```

**验证**:
```bash
python -c "from claude_code_tg.interfaces import ExecutorInterface, SessionStoreInterface, ConfigProviderInterface; print('✅ Interfaces defined')"
```

### 步骤 2: 创建服务容器（0.5 天）

创建 `src/claude_code_tg/container.py`：

**ServiceContainer** - 依赖注入容器
```python
@dataclass
class ServiceContainer:
    """依赖注入容器，持有所有服务实例"""
    
    executor: ExecutorInterface
    session_store: SessionStoreInterface
    config_provider: ConfigProviderInterface
    project_dir: str
    timeout: int
    cli_resume_compat: bool
    draft_preview_enabled: bool
    
    @classmethod
    def create_default(
        cls,
        project_dir: str = ".",
        timeout: int = 300,
        **kwargs: Any,
    ) -> "ServiceContainer":
        """创建默认配置的容器"""
        from claude_code_tg.executor import Executor
        from claude_code_tg.sessions import ChatSessionStore
        from claude_code_tg.config import SimpleConfigProvider
        
        return cls(
            executor=Executor(),
            session_store=ChatSessionStore(),
            config_provider=SimpleConfigProvider(kwargs),
            project_dir=project_dir,
            timeout=timeout,
            cli_resume_compat=kwargs.get('cli_resume_compat', False),
            draft_preview_enabled=kwargs.get('draft_preview_enabled', False),
        )
```

创建配置提供者 `src/claude_code_tg/config.py` 的 SimpleConfigProvider：
```python
class SimpleConfigProvider:
    def __init__(self, config: dict[str, Any]):
        self._config = config
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
    
    def has(self, key: str) -> bool:
        return key in self._config
```

**测试**:
创建 `tests/test_container.py` 并验证容器可以创建和访问服务。

### 步骤 3: 重构 TGBot 构造函数（0.5 天）

修改 `src/claude_code_tg/bot.py` 的 `TGBot.__init__`：

**目标**: 支持两种初始化方式（向后兼容）
1. 新方式：传入 ServiceContainer
2. 旧方式：传入所有参数（内部构建容器）

```python
class TGBot(BotMessageProcessor, BotCommandHandlers):
    def __init__(
        self,
        token: str,
        admin_ids: set[int],
        allowed_ids: set[int],
        container: ServiceContainer | None = None,
        # 以下为向后兼容的参数
        project_dir: str = ".",
        timeout: int = 300,
        **legacy_kwargs,
    ):
        # 如果没有传入容器，用旧参数创建
        if container is None:
            container = ServiceContainer.create_default(
                project_dir=project_dir,
                timeout=timeout,
                **legacy_kwargs,
            )
        
        # 从容器获取服务
        self.container = container
        self.executor = container.executor
        self.state = container.session_store
        self.project_dir = container.project_dir
        self.timeout = container.timeout
        self.cli_resume_compat_enabled = container.cli_resume_compat
        self.draft_preview_enabled = container.draft_preview_enabled
        
        # ... 其余初始化保持不变
        self.token = token
        self.admin_ids = admin_ids
        self.allowed_ids = allowed_ids
        # ...
```

**测试**: 运行 `tests/test_bot.py` 确保所有测试通过。

### 步骤 4: 更新 server.py（0.5 天）

修改 `src/claude_code_tg/server.py` 的 `run_bot` 函数：

```python
def run_bot(config: RuntimeConfig) -> None:
    """使用容器模式启动 bot"""
    
    # 创建服务容器
    container = ServiceContainer.create_default(
        project_dir=config.project_dir,
        timeout=config.timeout,
        cli_resume_compat=config.cli_resume_compat,
        draft_preview_enabled=config.draft_preview_enabled,
        permission_mode=config.permission_mode,
        model=config.model,
        effort=config.effort,
    )
    
    # 使用容器创建 bot
    bot = TGBot(
        token=config.token,
        admin_ids=config.admin_ids,
        allowed_ids=config.allowed_ids,
        container=container,
        allowed_chat_ids=config.allowed_chat_ids,
        queue_max_size=config.queue_max_size,
        # ... 其他非容器管理的参数
    )
    
    # ... 其余启动逻辑
```

**手动测试**:
```bash
# 1. 启动 bot 验证能正常运行
uv run python -m claude_code_tg.server --help

# 2. 实际运行（可选）
uv run python -m claude_code_tg.server
```

## 验收标准

完成任务 3.1 后，应满足：

- [x] interfaces.py 创建，定义 3 个 Protocol
- [x] container.py 创建，实现 ServiceContainer
- [x] SimpleConfigProvider 实现
- [x] TGBot 支持容器注入（向后兼容）
- [x] server.py 使用容器模式
- [x] 所有 815 个测试通过
- [x] 手动测试 bot 可以启动

## 提交策略

建议提交顺序：
1. `feat(di): add core interfaces with Protocol definitions`
2. `feat(di): implement ServiceContainer and config provider`
3. `refactor(bot): add container injection to TGBot (backward compatible)`
4. `refactor(server): use ServiceContainer in run_bot`
5. `test(di): add container and interface tests`

## 参考文档

详细实施指南：`docs/dev/phase3-kickoff.md`

## 下一步

完成 3.1 后，继续任务 3.2：重构 bot.py 为组合模式（将 541 行拆分为多个服务类）。
```

---

## 📋 备选 Prompt（如果想直接开始某个具体步骤）

### 如果想从步骤 1 开始：
```
开始阶段 3.1 步骤 1：定义核心接口。

创建 src/claude_code_tg/interfaces.py，定义以下 Protocol：
- ExecutorInterface（执行器接口）
- SessionStoreInterface（会话存储接口）
- ConfigProviderInterface（配置提供者接口）

参考 docs/dev/phase3-kickoff.md 中的接口定义。
完成后验证导入正常，然后进入步骤 2。
```

### 如果想跳到步骤 2：
```
开始阶段 3.1 步骤 2：创建服务容器。

假设 interfaces.py 已完成。

创建：
1. src/claude_code_tg/container.py（ServiceContainer 类）
2. src/claude_code_tg/config.py 中的 SimpleConfigProvider

然后创建 tests/test_container.py 验证容器功能。
```

---

## 💡 提示

1. **渐进式开发**：每完成一个步骤就运行测试
2. **向后兼容**：TGBot 必须同时支持新旧两种初始化方式
3. **频繁提交**：每个独立变更立即提交
4. **测试优先**：确保所有 815 个测试始终通过

预计完成时间：2 天
当前测试状态：✅ 815/815 通过
