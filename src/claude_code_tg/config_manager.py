"""配置文件管理器。

提供配置文件搜索、加载和管理功能，支持全局配置目录。
"""

import os
from pathlib import Path

from claude_code_tg.config import RuntimeConfig, load_runtime_config


class ConfigNotFoundError(Exception):
    """配置文件未找到错误。"""


class ConfigManager:
    """配置文件管理器。

    支持多级配置文件搜索：
    1. 命令行参数指定的路径
    2. DOTENV_PATH 环境变量
    3. 当前目录 .env 文件
    4. 全局默认配置 ~/.tgcc/configs/default.env
    """

    # 全局配置目录
    GLOBAL_CONFIG_DIR = Path.home() / ".tgcc" / "configs"
    DEFAULT_CONFIG_NAME = "default.env"

    # 当前目录可能的配置文件名
    LOCAL_CONFIG_NAMES = [".env", "env"]

    def __init__(self) -> None:
        """初始化配置管理器。"""
        pass

    def find_config(self, config_arg: str | None = None) -> Path:
        """查找配置文件。

        搜索优先级（从高到低）：
        1. 命令行参数指定的路径
        2. DOTENV_PATH 环境变量
        3. 当前目录 .env / env
        4. 全局默认配置 ~/.tgcc/configs/default.env

        Args:
            config_arg: 命令行参数指定的配置路径或名称

        Returns:
            Path: 找到的配置文件路径

        Raises:
            ConfigNotFoundError: 如果找不到配置文件
        """
        # 1. CLI 参数
        if config_arg:
            return self._resolve_config_path(config_arg)

        # 2. 环境变量
        if env_path := os.environ.get("DOTENV_PATH"):
            path = Path(env_path)
            if not path.exists():
                raise ConfigNotFoundError(
                    f"DOTENV_PATH 指定的配置文件不存在: {path}"
                )
            return path.resolve()

        # 3. 当前目录
        for name in self.LOCAL_CONFIG_NAMES:
            path = Path.cwd() / name
            if path.exists():
                return path.resolve()

        # 4. 全局默认
        default_path = self.GLOBAL_CONFIG_DIR / self.DEFAULT_CONFIG_NAME
        if default_path.exists():
            return default_path.resolve()

        # 5. 未找到，给出提示
        raise ConfigNotFoundError(
            "未找到配置文件。请：\n"
            "  1. 在当前目录创建 .env 文件，或\n"
            f"  2. 使用 --config 参数指定配置文件，或\n"
            f"  3. 设置 DOTENV_PATH 环境变量，或\n"
            f"  4. 在 {self.GLOBAL_CONFIG_DIR / self.DEFAULT_CONFIG_NAME} 创建默认配置"
        )

    def _resolve_config_path(self, config_arg: str) -> Path:
        """解析配置路径参数。

        支持：
        - 绝对路径: /path/to/config.env
        - 相对路径: ./config.env
        - 配置名称: myproject (自动查找 ~/.tgcc/configs/myproject.env)

        Args:
            config_arg: 配置路径或名称

        Returns:
            Path: 解析后的配置文件路径

        Raises:
            ConfigNotFoundError: 如果配置文件不存在
        """
        path = Path(config_arg)

        # 绝对路径或相对路径
        if path.is_absolute() or "/" in config_arg or "\\" in config_arg:
            if not path.exists():
                raise ConfigNotFoundError(f"配置文件不存在: {path}")
            return path.resolve()

        # 配置名称（在全局目录查找）
        # 支持 "myproject" 或 "myproject.env"
        if not config_arg.endswith(".env"):
            config_arg = f"{config_arg}.env"

        global_path = self.GLOBAL_CONFIG_DIR / config_arg
        if global_path.exists():
            return global_path.resolve()

        # 也尝试在当前目录查找
        local_path = Path.cwd() / config_arg
        if local_path.exists():
            return local_path.resolve()

        raise ConfigNotFoundError(
            f"配置 '{config_arg}' 未找到。查找路径：\n"
            f"  - {global_path}\n"
            f"  - {local_path}"
        )

    def load_config(
        self, config_path: Path | None = None, environ: dict[str, str] | None = None
    ) -> RuntimeConfig:
        """加载配置文件。

        Args:
            config_path: 配置文件路径（None 则自动查找）
            environ: 环境变量字典（用于测试，默认使用 os.environ）

        Returns:
            RuntimeConfig: 解析后的运行时配置

        Raises:
            ConfigNotFoundError: 如果找不到配置文件
        """
        if config_path is None:
            config_path = self.find_config()

        # 临时设置 DOTENV_PATH，让 load_runtime_config 加载指定文件
        original_dotenv = os.environ.get("DOTENV_PATH")
        try:
            os.environ["DOTENV_PATH"] = str(config_path)
            from dotenv import load_dotenv

            load_dotenv(config_path, override=True)
            return load_runtime_config(environ)
        finally:
            # 恢复原始值
            if original_dotenv is not None:
                os.environ["DOTENV_PATH"] = original_dotenv
            elif "DOTENV_PATH" in os.environ:
                del os.environ["DOTENV_PATH"]

    def list_configs(self) -> list[tuple[str, Path]]:
        """列出所有全局配置文件。

        Returns:
            list[tuple[str, Path]]: (配置名称, 配置路径) 列表
        """
        if not self.GLOBAL_CONFIG_DIR.exists():
            return []

        configs = []
        for path in self.GLOBAL_CONFIG_DIR.glob("*.env"):
            name = path.stem  # 去掉 .env 后缀
            configs.append((name, path))

        return sorted(configs, key=lambda x: x[0])

    def ensure_global_dir(self) -> None:
        """确保全局配置目录存在。"""
        self.GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # 设置目录权限为 700（仅所有者可访问）
        self.GLOBAL_CONFIG_DIR.chmod(0o700)
