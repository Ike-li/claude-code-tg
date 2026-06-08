"""核心接口定义，用于依赖注入和解耦。

这些 Protocol 定义了系统中主要组件的接口，允许通过依赖注入实现松耦合架构。
使用 Protocol（PEP 544 结构化子类型）而不是 ABC，提供更灵活的接口实现方式。
"""

from typing import Any, Protocol, runtime_checkable
from collections.abc import Awaitable, Callable

from claude_code_tg.executor import ExecutionResult, RunEvent


@runtime_checkable
class ExecutorInterface(Protocol):
    """Claude CLI 执行器接口。

    负责执行 Claude Code CLI 命令并管理子进程生命周期。
    """

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
        on_tool_use: Callable[[int], Awaitable[None]] | None = None,
        on_event: Callable[[RunEvent], Awaitable[None]] | None = None,
    ) -> ExecutionResult:
        """执行一个 Claude 提示并返回结果。

        Args:
            prompt: 用户输入的提示
            chat_id: Telegram 聊天 ID
            session_id: Claude 会话 ID（None 表示新会话）
            project_dir: 项目工作目录
            timeout: 超时时间（秒）
            permission_mode: 权限模式（如 "bypassPermissions"）
            model: 模型名称（如 "claude-opus-4"）
            effort: 思考级别（如 "high", "xhigh"）
            cli_resume_compat: 是否启用 CLI resume 兼容模式
            on_tool_use: 工具使用回调
            on_event: 事件流回调

        Returns:
            ExecutionResult: 包含执行结果和元数据
        """
        ...

    async def stop(self, chat_id: int) -> bool:
        """停止指定聊天的正在运行的进程。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            bool: 是否成功停止进程
        """
        ...

    async def shutdown(self) -> None:
        """关闭执行器，清理所有资源。"""
        ...

    def new_session_id(self) -> str:
        """生成一个新的会话 ID。

        Returns:
            str: UUID 格式的会话 ID
        """
        ...


@runtime_checkable
class SessionStoreInterface(Protocol):
    """会话存储接口。

    管理聊天会话状态、队列和配置覆盖。
    """

    sessions: dict[int, str]
    """chat_id -> session_id 映射"""

    busy: set[int]
    """当前忙碌的聊天 ID 集合"""

    def get_or_create_session(self, chat_id: int) -> tuple[str | None, bool]:
        """获取或创建会话。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            tuple[str | None, bool]: (session_id, 是否已存在)
        """
        ...

    def normalize_and_validate_session_id(
        self, session_id: str, chat_id: int
    ) -> str | None:
        """验证并规范化会话 ID，检查所有权。

        Args:
            session_id: 要验证的会话 ID
            chat_id: 请求访问的聊天 ID

        Returns:
            str | None: 规范化后的 UUID，如果无效或所有权不匹配则返回 None
        """
        ...

    def session_version(self, chat_id: int) -> int:
        """获取会话版本号，用于并发控制。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            int: 当前会话版本号
        """
        ...

    def set_session_if_current(
        self, chat_id: int, session_id: str, expected_version: int
    ) -> bool:
        """条件性设置会话（仅当版本匹配时）。

        Args:
            chat_id: Telegram 聊天 ID
            session_id: 新的会话 ID
            expected_version: 期望的版本号

        Returns:
            bool: 是否成功设置
        """
        ...

    def bump_session_version(self, chat_id: int) -> int:
        """递增会话版本号。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            int: 新的版本号
        """
        ...

    def effective_permission_mode(self, chat_id: int) -> str | None:
        """获取有效的权限模式（覆盖或默认）。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            str | None: 权限模式字符串
        """
        ...

    def effective_model(self, chat_id: int) -> str | None:
        """获取有效的模型（覆盖或默认）。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            str | None: 模型名称
        """
        ...

    def effective_effort(self, chat_id: int) -> str | None:
        """获取有效的思考级别（覆盖或默认）。

        Args:
            chat_id: Telegram 聊天 ID

        Returns:
            str | None: 思考级别字符串
        """
        ...

    def write_status(self) -> OSError | None:
        """将状态持久化到磁盘。

        Returns:
            OSError | None: 如果写入失败则返回错误
        """
        ...

    def restore_sessions(self) -> int:
        """从磁盘恢复会话状态。

        Returns:
            int: 恢复的会话数量
        """
        ...


@runtime_checkable
class ConfigProviderInterface(Protocol):
    """配置提供者接口。

    提供键值对配置存储和访问。
    """

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值。

        Args:
            key: 配置键
            default: 默认值

        Returns:
            Any: 配置值或默认值
        """
        ...

    def set(self, key: str, value: Any) -> None:
        """设置配置值。

        Args:
            key: 配置键
            value: 配置值
        """
        ...

    def has(self, key: str) -> bool:
        """检查配置键是否存在。

        Args:
            key: 配置键

        Returns:
            bool: 是否存在
        """
        ...
