# 下一会话 Prompt

复制以下内容到下一个会话开始：

---

继续阶段 3 架构优化 - 任务 3.1 依赖注入。

## 当前状态
- ✅ 阶段 1（安全加固）：完成（4/4 任务）
- ✅ 阶段 2（代码质量）：核心完成（Executor.run -75%）
- 📋 阶段 3（架构优化）：开始任务 3.1
- ✅ 所有 815 个测试通过

## 任务 3.1: 引入依赖注入（2 天，4 步骤）

### 步骤 1: 定义核心接口（0.5 天）
创建 `src/claude_code_tg/interfaces.py`，定义 3 个 Protocol：
- ExecutorInterface（执行器接口）
- SessionStoreInterface（会话存储接口）
- ConfigProviderInterface（配置提供者接口）

### 步骤 2: 创建服务容器（0.5 天）
创建 `src/claude_code_tg/container.py`：
- ServiceContainer 类（持有所有服务实例）
- create_default() 工厂方法

创建 SimpleConfigProvider 在 `src/claude_code_tg/config.py`

### 步骤 3: 重构 TGBot 构造函数（0.5 天）
修改 `src/claude_code_tg/bot.py`：
- 支持传入 ServiceContainer（新方式）
- 向后兼容旧参数（内部构建容器）

### 步骤 4: 更新 server.py（0.5 天）
修改 `src/claude_code_tg/server.py`：
- run_bot() 使用容器模式创建 bot

## 验收标准
- [ ] 3 个 Protocol 定义完成
- [ ] ServiceContainer 实现完成
- [ ] TGBot 支持容器注入（向后兼容）
- [ ] server.py 使用容器模式
- [ ] 所有 815 个测试通过
- [ ] 手动测试 bot 可启动

## 参考文档
- 详细指南：`docs/dev/phase3-kickoff.md`
- 续接 prompt：`docs/dev/phase3-continuation-prompt.md`

请开始步骤 1：创建 interfaces.py
