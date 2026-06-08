# 全局配置管理和多实例管理方案

**日期**: 2026-06-08  
**状态**: 设计阶段

---

## 1. 目标

### 当前问题
- tgcc 必须在项目目录启动（需要本地 .env 文件）
- 多项目管理不便
- 缺少实例管理命令

### 目标
- ✅ 支持全局配置目录 `~/.tgcc/`
- ✅ 配置文件搜索机制（多路径）
- ✅ 多实例管理（start/stop/list/status）
- ✅ 向后兼容现有启动方式

---

## 2. 全局配置目录结构

```
~/.tgcc/
├── configs/                  # 配置文件目录
│   ├── default.env          # 默认配置
│   ├── project1.env         # 项目1配置
│   ├── project2.env         # 项目2配置
│   └── myapp.env            # 自定义命名
│
├── instances/               # 实例运行时数据
│   ├── project1/
│   │   ├── tgcc.pid
│   │   ├── tgcc.log
│   │   ├── status.json
│   │   └── attachments/
│   ├── project2/
│   │   └── ...
│   └── myapp/
│       └── ...
│
└── registry.json            # 实例注册表
```

### registry.json 格式
```json
{
  "instances": {
    "project1": {
      "config": "/Users/user/.tgcc/configs/project1.env",
      "runtime_dir": "/Users/user/.tgcc/instances/project1",
      "pid": 12345,
      "status": "running",
      "started_at": "2026-06-08T10:30:00Z",
      "project_dir": "/path/to/project1"
    },
    "project2": {
      "config": "/Users/user/.tgcc/configs/project2.env",
      "runtime_dir": "/Users/user/.tgcc/instances/project2",
      "pid": null,
      "status": "stopped",
      "stopped_at": "2026-06-08T09:00:00Z",
      "project_dir": "/path/to/project2"
    }
  }
}
```

---

## 3. 配置文件搜索路径

**优先级顺序**（从高到低）：

1. **命令行参数** - `tgcc --config /path/to/config.env`
2. **环境变量** - `DOTENV_PATH=/path/to/config.env`
3. **当前目录** - `./env` 或 `./.env`
4. **全局默认** - `~/.tgcc/configs/default.env`
5. **报错** - 如果都找不到，提示用户创建配置

### 搜索逻辑
```python
def find_config_file(config_arg: str | None) -> Path:
    # 1. CLI 参数
    if config_arg:
        return resolve_config_path(config_arg)
    
    # 2. 环境变量
    if env_path := os.environ.get("DOTENV_PATH"):
        return Path(env_path)
    
    # 3. 当前目录
    for name in [".env", "env"]:
        if (path := Path.cwd() / name).exists():
            return path
    
    # 4. 全局默认
    if (default := Path.home() / ".tgcc/configs/default.env").exists():
        return default
    
    # 5. 报错
    raise ConfigNotFoundError(...)
```

---

## 4. CLI 命令设计

### 主命令
```bash
tgcc [OPTIONS] [COMMAND]
```

### 子命令

#### 4.1 启动实例
```bash
# 方式1：使用配置名称
tgcc start <name>

# 方式2：指定配置文件
tgcc start --config /path/to/config.env [--name <name>]

# 方式3：自动检测（当前目录 .env）
tgcc start

# 方式4：向后兼容（默认行为）
tgcc
```

**示例**：
```bash
# 启动 project1 实例
tgcc start project1

# 使用自定义配置启动，命名为 myapp
tgcc start --config ~/myproject/.env --name myapp

# 在项目目录直接启动（自动命名）
cd ~/myproject && tgcc start
```

#### 4.2 停止实例
```bash
# 停止指定实例
tgcc stop <name>

# 停止所有实例
tgcc stop --all

# 强制停止
tgcc stop <name> --force
```

#### 4.3 查看实例列表
```bash
# 列出所有实例
tgcc list

# 只显示运行中的
tgcc list --running

# 详细信息
tgcc list --verbose
```

**输出示例**：
```
NAME       STATUS    PID     PROJECT_DIR              UPTIME
project1   running   12345   /path/to/project1        2h 30m
project2   stopped   -       /path/to/project2        -
myapp      running   12346   /home/user/myapp         15m
```

#### 4.4 查看实例状态
```bash
# 查看单个实例详细状态
tgcc status <name>

# 查看所有实例状态
tgcc status --all
```

**输出示例**：
```
Instance: project1
Status: running
PID: 12345
Config: ~/.tgcc/configs/project1.env
Project Dir: /path/to/project1
Runtime Dir: ~/.tgcc/instances/project1
Started: 2026-06-08 10:30:00
Uptime: 2h 30m
Bot Info:
  - Sessions: 3
  - Busy: 1
  - Queue: 2
```

#### 4.5 重启实例
```bash
tgcc restart <name>
```

#### 4.6 查看日志
```bash
# 查看日志（tail -f）
tgcc logs <name>

# 查看最近 N 行
tgcc logs <name> -n 100

# 不跟随
tgcc logs <name> --no-follow
```

#### 4.7 初始化配置
```bash
# 创建全局配置目录
tgcc init

# 创建新配置文件
tgcc config create <name>

# 编辑配置文件
tgcc config edit <name>

# 列出所有配置
tgcc config list
```

---

## 5. 实现计划

### 5.1 新增模块

#### `src/claude_code_tg/config_manager.py`
```python
class ConfigManager:
    """配置文件管理器"""
    
    def find_config(self, config_arg: str | None) -> Path:
        """查找配置文件"""
    
    def load_config(self, config_path: Path) -> RuntimeConfig:
        """加载配置"""
    
    def list_configs(self) -> list[ConfigInfo]:
        """列出所有配置"""
    
    def create_config(self, name: str, template: str = "default") -> Path:
        """创建新配置"""
```

#### `src/claude_code_tg/instance_manager.py`
```python
class InstanceManager:
    """实例管理器"""
    
    def start(self, name: str, config_path: Path) -> None:
        """启动实例"""
    
    def stop(self, name: str, force: bool = False) -> None:
        """停止实例"""
    
    def list(self) -> list[InstanceInfo]:
        """列出所有实例"""
    
    def status(self, name: str) -> InstanceStatus:
        """查看实例状态"""
    
    def restart(self, name: str) -> None:
        """重启实例"""
```

#### `src/claude_code_tg/cli.py`
```python
def main():
    """主 CLI 入口"""
    parser = argparse.ArgumentParser(...)
    subparsers = parser.add_subparsers(...)
    
    # 子命令
    start_parser = subparsers.add_parser("start", ...)
    stop_parser = subparsers.add_parser("stop", ...)
    list_parser = subparsers.add_parser("list", ...)
    # ...
```

### 5.2 修改现有模块

#### `src/claude_code_tg/server.py`
- 保留为服务器启动逻辑
- 由 `cli.py` 调用
- 接收配置路径参数

#### `pyproject.toml`
```toml
[project.scripts]
tgcc = "claude_code_tg.cli:main"  # 新的 CLI 入口
```

---

## 6. 向后兼容

### 兼容性保证

1. **直接运行** - `tgcc` 仍然工作（搜索当前目录 .env）
2. **环境变量** - `DOTENV_PATH` 仍然有效
3. **现有配置** - 项目内的 .env 文件优先级高于全局配置

### 迁移路径

**现有用户**：
```bash
# 继续使用项目内启动（不变）
cd /path/to/project
tgcc

# 或者迁移到全局管理
tgcc init
cp .env ~/.tgcc/configs/myproject.env
tgcc start myproject
```

---

## 7. 实现优先级

### Phase 1（核心功能）
1. ✅ 配置文件搜索机制
2. ✅ 基本的实例注册（registry.json）
3. ✅ `tgcc start <name>` 命令
4. ✅ `tgcc stop <name>` 命令
5. ✅ `tgcc list` 命令

### Phase 2（增强功能）
6. ⏭ `tgcc status <name>` 详细状态
7. ⏭ `tgcc logs <name>` 日志查看
8. ⏭ `tgcc restart <name>` 重启

### Phase 3（配置管理）
9. ⏭ `tgcc init` 初始化
10. ⏭ `tgcc config create/edit/list`

---

## 8. 安全考虑

1. **PID 文件验证** - 检查 PID 是否真实存在
2. **权限检查** - ~/.tgcc/ 目录权限 700
3. **配置文件权限** - .env 文件权限 600
4. **符号链接拒绝** - 配置路径不允许符号链接
5. **实例隔离** - 每个实例独立的运行时目录

---

## 9. 测试计划

### 单元测试
- `test_config_manager.py` - 配置搜索和加载
- `test_instance_manager.py` - 实例管理逻辑
- `test_cli.py` - CLI 参数解析

### 集成测试
- `test_e2e_multiinstance.py` - 多实例启动/停止
- `test_e2e_global_config.py` - 全局配置管理

### 兼容性测试
- 现有启动方式仍然工作
- 环境变量优先级正确
- 向后兼容所有配置选项

---

## 10. 预期成果

### 用户体验改进

**之前**：
```bash
# 必须在项目目录
cd /path/to/project1
tgcc

# 多项目需要多个终端
cd /path/to/project2
tgcc
```

**之后**：
```bash
# 全局管理
tgcc start project1
tgcc start project2
tgcc list
# NAME       STATUS    PROJECT_DIR
# project1   running   /path/to/project1
# project2   running   /path/to/project2

tgcc stop project1
```

### 代码改进
- 更清晰的配置管理
- 统一的实例生命周期管理
- 更好的可测试性

---

**下一步**: 开始实现 Phase 1 核心功能
