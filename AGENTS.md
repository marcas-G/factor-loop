# 量化工作区

本环境用于量化策略研究、因子分析、回测开发等量化金融任务。

- 数据处理脚本使用 pandas/numpy
- 涉及实盘操作前需确认

## Skills / Agents 目录约定

- 项目级 skill → `.agents/skills/`（ZCode + Claude Code 都读）
- 项目级 subagent → `.zcode/agents/`（ZCode 真实源）；`.claude/agents` 是指向它的软链（给 Claude Code）
- 不再向 `.claude/skills/` 添加新内容（已弃用）
- skill/agent 间引用用相对于项目根的路径或 `${CLAUDE_PROJECT_DIR}` 变量
