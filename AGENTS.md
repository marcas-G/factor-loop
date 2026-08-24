# 量化工作区

本环境用于量化策略研究、因子分析、回测开发等量化金融任务。

- 数据处理脚本使用 pandas/numpy
- 涉及实盘操作前需确认

## Skills / Agents 目录约定

- 项目级 skill → `.agents/skills/`（ZCode + Claude Code 都读）
- 项目级 subagent → `.zcode/agents/`（ZCode 真实源）；`.claude/agents` 是指向它的软链（给 Claude Code）
- 不再向 `.claude/skills/` 添加新内容（已弃用）
- skill/agent 间引用用相对于项目根的路径或 `${CLAUDE_PROJECT_DIR}` 变量

## 子代理任务文件协议（Codex 环境兜底）

当前 Codex 桌面环境的 `spawn_agent` 不会把任务正文注入子代理上下文，子代理只会收到空 `NEW_TASK`。统一改用**固定任务文件 + 干净 fork + 串行派发**：

- 派发方：spawn 前把任务写成 `.tmp/agent_task.json`（含 `task` / `input` / `expect` 字段），再 `spawn_agent(..., fork_turns="none")`；message 只写“读取 `.tmp/agent_task.json` 并执行”。等待该 agent 终态后删除任务文件，再派发下一个。
- 接收方：回合开始先读 `.tmp/agent_task.json`；存在则执行其中的 `task` 并返回结果，不存在则只返回 `NO_TASK_FILE`。
- 绝对禁止：接收方为完成任务再派发子代理、修改或删除任务文件；同一时刻只允许一个未完成子代理，避免并发抢占同一固定文件。
