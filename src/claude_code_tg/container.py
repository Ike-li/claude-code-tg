"""依赖注入容器。

ServiceContainer 持有所有核心服务实例，支持依赖注入模式。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_tg.interfaces import (
    ConfigProviderInterface,
    ExecutorInterface,
    SessionStoreInterface,
)


@dataclass
class ServiceContainer:
    """依赖注入容器，持有所有服务实例。

    容器模式将服务实例集中管理，便于：
    1. 依赖注入 - 组件通过接口通信，降低耦合
    2. 测试 - 可以轻松替换为 mock 实现
    3. 配置 - 集中管理服务配置
    4. 扩展 - 支持多种实现（如不同的存储后端）
    """

    executor: ExecutorInterface
    """Claude CLI 执行器"""

    session_store: SessionStoreInterface
    """会话存储"""

    config_provider: ConfigProviderInterface
    """配置提供者"""

    project_dir: str
    """项目工作目录"""

    timeout: int
    """默认超时时间（秒）"""

    cli_resume_compat: bool
    """是否启用 CLI resume 兼容模式"""

    draft_preview_enabled: bool
    """是否启用草稿预览功能"""

    @classmethod
    def create_default(
        cls,
        project_dir: str = ".",
        timeout: int = 300,
        queue_max_size: int = 3,
        permission_mode: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        status_file: Path | None = None,
        cli_resume_compat: bool = False,
        draft_preview_enabled: bool = False,
        **extra_config: Any,
    ) -> "ServiceContainer":
        """创建默认配置的容器。

        使用标准实现创建所有服务：
        - Executor: 真实的 CLI 执行器
        - ChatSessionStore: 内存 + 文件持久化
        - SimpleConfigProvider: 简单字典存储

        Args:
            project_dir: 项目工作目录
            timeout: 默认超时时间（秒）
            queue_max_size: 消息队列最大长度
            permission_mode: 默认权限模式
            model: 默认模型
            effort: 默认思考级别
            status_file: 状态文件路径
            cli_resume_compat: 是否启用 CLI resume 兼容模式
            draft_preview_enabled: 是否启用草稿预览
            **extra_config: 其他配置项

        Returns:
            ServiceContainer: 配置好的容器实例
        """
        from claude_code_tg.config import SimpleConfigProvider
        from claude_code_tg.executor import Executor
        from claude_code_tg.sessions import ChatSessionStore

        # 创建执行器
        executor = Executor()

        # 创建会话存储
        session_store = ChatSessionStore(
            queue_max_size=queue_max_size,
            permission_mode=permission_mode,
            model=model,
            effort=effort,
            status_file=status_file,
        )

        # 创建配置提供者
        config_dict = {
            "permission_mode": permission_mode,
            "model": model,
            "effort": effort,
            "cli_resume_compat": cli_resume_compat,
            "draft_preview_enabled": draft_preview_enabled,
            **extra_config,
        }
        config_provider = SimpleConfigProvider(config_dict)

        return cls(
            executor=executor,
            session_store=session_store,
            config_provider=config_provider,
            project_dir=project_dir,
            timeout=timeout,
            cli_resume_compat=cli_resume_compat,
            draft_preview_enabled=draft_preview_enabled,
        )
