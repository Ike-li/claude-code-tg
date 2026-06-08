"""实例管理器。

管理多个 tgcc 实例的生命周期（启动、停止、状态查询）。
"""

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InstanceInfo:
    """实例信息。"""

    name: str
    """实例名称"""

    config_path: Path
    """配置文件路径"""

    runtime_dir: Path
    """运行时目录"""

    pid: int | None
    """进程 ID（None 表示未运行）"""

    status: str
    """状态：running / stopped / unknown"""

    project_dir: str | None
    """项目目录"""

    started_at: str | None
    """启动时间（ISO 格式）"""

    stopped_at: str | None
    """停止时间（ISO 格式）"""


class InstanceManager:
    """实例管理器。

    管理所有 tgcc 实例，支持：
    - 启动新实例
    - 停止运行中的实例
    - 查询实例状态
    - 列出所有实例
    """

    # 全局实例目录
    INSTANCES_DIR = Path.home() / ".tgcc" / "instances"
    REGISTRY_FILE = Path.home() / ".tgcc" / "registry.json"

    def __init__(self) -> None:
        """初始化实例管理器。"""
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        """确保必要的目录存在。"""
        self.INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
        self.INSTANCES_DIR.chmod(0o700)

    def _load_registry(self) -> dict[str, Any]:
        """加载实例注册表。

        Returns:
            dict: 注册表数据
        """
        if not self.REGISTRY_FILE.exists():
            return {"instances": {}}

        try:
            with open(self.REGISTRY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load registry: %s", e)
            return {"instances": {}}

    def _save_registry(self, registry: dict[str, Any]) -> None:
        """保存实例注册表。

        Args:
            registry: 注册表数据
        """
        self.REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        self.REGISTRY_FILE.chmod(0o600)

    def _is_process_running(self, pid: int) -> bool:
        """检查进程是否在运行。

        Args:
            pid: 进程 ID

        Returns:
            bool: 是否在运行
        """
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _generate_instance_name(self, config_path: Path) -> str:
        """生成实例名称。

        Args:
            config_path: 配置文件路径

        Returns:
            str: 实例名称
        """
        # 使用配置文件名（去掉 .env 后缀）
        name = config_path.stem
        if name == ".env":
            # 如果是 .env，使用父目录名
            name = config_path.parent.name

        # 确保名称唯一
        base_name = name
        counter = 1
        while self._instance_exists(name):
            name = f"{base_name}-{counter}"
            counter += 1

        return name

    def _instance_exists(self, name: str) -> bool:
        """检查实例是否存在。

        Args:
            name: 实例名称

        Returns:
            bool: 是否存在
        """
        registry = self._load_registry()
        return name in registry.get("instances", {})

    def start(
        self, config_path: Path, name: str | None = None, daemon: bool = True
    ) -> str:
        """启动实例。

        Args:
            config_path: 配置文件路径
            name: 实例名称（None 则自动生成）
            daemon: 是否以守护进程模式启动

        Returns:
            str: 实例名称

        Raises:
            ValueError: 如果实例已存在
        """
        # 生成或验证名称
        if name is None:
            name = self._generate_instance_name(config_path)
        elif self._instance_exists(name):
            # 检查是否正在运行
            info = self.status(name)
            if info.status == "running":
                raise ValueError(f"实例 '{name}' 已在运行（PID: {info.pid}）")

        # 创建运行时目录
        runtime_dir = self.INSTANCES_DIR / name
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.chmod(0o700)

        log_file = runtime_dir / "tgcc.log"
        pid_file = runtime_dir / "tgcc.pid"

        # 启动进程
        env = os.environ.copy()
        env["DOTENV_PATH"] = str(config_path)

        if daemon:
            # 守护进程模式
            with open(log_file, "a") as log_fp:
                process = subprocess.Popen(
                    [sys.executable, "-m", "claude_code_tg.server"],
                    env=env,
                    stdout=log_fp,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # 创建新会话
                )
            pid = process.pid
        else:
            # 前台模式（阻塞）
            process = subprocess.Popen(
                [sys.executable, "-m", "claude_code_tg.server"],
                env=env,
            )
            pid = process.pid

        # 写入 PID 文件
        pid_file.write_text(str(pid))
        pid_file.chmod(0o600)

        # 注册实例
        registry = self._load_registry()
        registry["instances"][name] = {
            "config": str(config_path),
            "runtime_dir": str(runtime_dir),
            "pid": pid,
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stopped_at": None,
            "project_dir": None,  # 可以从配置中读取
        }
        self._save_registry(registry)

        logger.info("Started instance '%s' (PID: %d)", name, pid)
        return name

    def stop(self, name: str, force: bool = False, timeout: int = 10) -> bool:
        """停止实例。

        Args:
            name: 实例名称
            force: 是否强制停止（SIGKILL）
            timeout: 等待超时时间（秒）

        Returns:
            bool: 是否成功停止

        Raises:
            ValueError: 如果实例不存在
        """
        if not self._instance_exists(name):
            raise ValueError(f"实例 '{name}' 不存在")

        info = self.status(name)
        if info.status != "running" or info.pid is None:
            logger.info("Instance '%s' is not running", name)
            # 更新注册表状态
            registry = self._load_registry()
            if name in registry["instances"]:
                registry["instances"][name]["status"] = "stopped"
                registry["instances"][name]["pid"] = None
                registry["instances"][name]["stopped_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                self._save_registry(registry)
            return True

        pid = info.pid

        # 发送终止信号
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            logger.warning("Process %d not found", pid)
            return True

        # 等待进程退出
        for _ in range(timeout * 10):
            if not self._is_process_running(pid):
                break
            time.sleep(0.1)
        else:
            # 超时，强制 kill
            if not force:
                logger.warning("Timeout waiting for PID %d, force killing", pid)
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)

        # 更新注册表
        registry = self._load_registry()
        if name in registry["instances"]:
            registry["instances"][name]["status"] = "stopped"
            registry["instances"][name]["pid"] = None
            registry["instances"][name]["stopped_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            self._save_registry(registry)

        logger.info("Stopped instance '%s' (PID: %d)", name, pid)
        return True

    def status(self, name: str) -> InstanceInfo:
        """查询实例状态。

        Args:
            name: 实例名称

        Returns:
            InstanceInfo: 实例信息

        Raises:
            ValueError: 如果实例不存在
        """
        registry = self._load_registry()
        instances = registry.get("instances", {})

        if name not in instances:
            raise ValueError(f"实例 '{name}' 不存在")

        data = instances[name]
        pid = data.get("pid")

        # 验证进程是否真实存在
        if pid and not self._is_process_running(pid):
            # 进程已死，更新状态
            data["status"] = "stopped"
            data["pid"] = None
            self._save_registry(registry)
            pid = None

        return InstanceInfo(
            name=name,
            config_path=Path(data["config"]),
            runtime_dir=Path(data["runtime_dir"]),
            pid=pid,
            status=data.get("status", "unknown"),
            project_dir=data.get("project_dir"),
            started_at=data.get("started_at"),
            stopped_at=data.get("stopped_at"),
        )

    def list(self) -> list[InstanceInfo]:
        """列出所有实例。

        Returns:
            list[InstanceInfo]: 实例信息列表
        """
        registry = self._load_registry()
        instances = registry.get("instances", {})

        result = []
        for name in sorted(instances.keys()):
            with contextlib.suppress(ValueError):
                result.append(self.status(name))

        return result

    def restart(self, name: str) -> str:
        """重启实例。

        Args:
            name: 实例名称

        Returns:
            str: 实例名称
        """
        info = self.status(name)
        self.stop(name)
        time.sleep(1)  # 等待资源释放
        return self.start(info.config_path, name=name)
