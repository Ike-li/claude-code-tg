# 下一会话 Prompt

复制以下内容到下一个会话开始：

---

继续阶段 3 架构优化 - 任务 3.2 重构 bot.py 为组合模式。

## 当前状态
- ✅ 阶段 1（安全加固）：完成（4/4 任务）
- ✅ 阶段 2（代码质量）：核心完成（Executor.run -75%）
- ✅ 阶段 3.1（依赖注入）：完成（所有 815 个测试通过）
- 📋 阶段 3.2（组合模式）：准备开始

## 任务 3.2: 重构 bot.py 为组合模式（2 天，5 步骤）

**目标**: 将 TGBot (541 行) 拆分为多个服务类

### 职责分析
当前 TGBot 的职责：
1. **命令处理** (15+ 个命令方法) → CommandService
2. **消息处理** (_process_message, _drain_queue) → MessageService
3. **会话管理** (_get_or_create_session, _restore_sessions) → SessionService
4. **附件处理** (_attachment_cleanup_roots, _run_attachment_retention_cleanup) → AttachmentService
5. **配置管理** (_effective_permission_mode, _effective_model, _effective_effort)
6. **权限校验** (_is_authorized, _is_chat_allowed)
7. **状态记录** (_write_status, _record_periodic_status)

### 步骤 1: 创建 CommandService（0.5 天）
创建 `src/claude_code_tg/services/command_service.py`：
- 处理所有 Telegram 命令（/start, /new, /session, /stop 等）
- 移动自 bot.py 的所有命令处理方法
- 约 150 行

### 步骤 2: 创建 MessageService（0.5 天）
创建 `src/claude_code_tg/services/message_service.py`：
- process_message() - 处理单个消息
- drain_queue() - 排空消息队列
- 移动自 bot_processing.py
- 约 100 行

### 步骤 3: 创建 SessionService（0.5 天）
创建 `src/claude_code_tg/services/session_service.py`：
- get_or_create_session() - 获取或创建会话
- restore_sessions() - 从磁盘恢复会话
- 约 50 行

### 步骤 4: 创建 AttachmentService（0.5 天）
创建 `src/claude_code_tg/services/attachment_service.py`：
- cleanup_roots() - 返回需要清理的根目录
- run_retention_cleanup() - 执行保留期清理
- 约 50 行

### 步骤 5: 重构 TGBot 为协调器（0.5 天）
修改 `src/claude_code_tg/bot.py`：
- 组合各个服务类
- 保留简单的权限校验和协调逻辑
- 目标：541 行 → ~150 行（-72%）

## 预期成果
```
Before: TGBot (541 lines, 40 methods)
After:  TGBot (~150 lines, ~10 methods)
        + CommandService (~150 lines)
        + MessageService (~100 lines)
        + SessionService (~50 lines)
        + AttachmentService (~50 lines)
```

## 验收标准
- [ ] 创建 4 个服务类
- [ ] TGBot 重构为协调器（<200 行）
- [ ] 所有 815 个测试通过
- [ ] 功能完全保持不变

## 参考文档
- 详细指南：`docs/dev/phase3-kickoff.md`（第 201-368 行）
- 任务 3.1 完成报告：`docs/dev/phase3-task3.1-completion-report.md`

请开始步骤 1：创建 CommandService
