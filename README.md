# factor-autoloop

量化因子自动挖掘循环 —— 基于 Claude Code 的 `/research-loop` skill,无人值守批量产出因子。
自动完成 **brainstorm → write/submit/check → evaluate** 全流程,所有搬砖走 `quant-mcp` MCP server。

## 架构

```
auto-loops.sh                 tmux 单车道循环驱动器(拉起 /research-loop, state.json 检测完成)

.claude/skills/               循环编排 skill 链
  research-loop/              编排器
  brainstorm/                 Step1 候选生成
  write-factor/               写因子 .h(agent 内调)
  submit/                     提交打包(agent 内调)
  evaluate/                   Step3 评估写库
.claude/agents/
  run-factor-agent.md         单因子 write→submit→check→rewrite 状态机

runtime/                      quant-mcp server(submit/check/run_save/persist 走它)
core/
  db/                         因子库 db.py + schema.sql + migrations
  retrieval/                  R1-R4 检索 Contract + 派生表
  cog/                        cog-protocol 链路(assumption→evidence→发明)
  platform/                   featuretool.py + factor_check.py(平台对接)
  tools/                      AI/IC/embedding 工具 + 测试
factors/                      因子 .h 产物
data/                         factors.db(运行数据,不入库)
```

## 起循环

### 1. 装依赖
```bash
cd runtime && npm install              # quant-mcp server 依赖
pip install pandas numpy sqlite-vec sentence-transformers  # 建议装到独立 venv

# runtime 调 python 时用此 venv(系统 python3 缺上述部分包,必需)
export QUANT_VENV_PY=/path/to/your/venv/bin/python
# export QUANT_VEC0_SO=/path/to/vec0.so   # 可选,不设则自动探测
```

### 2. 建空因子库
```bash
python core/db/init_db.py            # 用 schema.sql 建空 factors.db
```

### 3. 配 MCP
```bash
cp .claude/settings.example.json .claude/settings.json
# 编辑 settings.json,把 QUANT_MCP_RUNS_ROOT 改成你的 run state 目录
```

### 4. 跑循环
```bash
mkdir -p logs/loops
nohup bash auto-loops.sh 1 > logs/loops/auto.out 2>&1 &
tail -f logs/loops/auto.out
```
用法/停止/参数见 `auto-loops.sh` 头部注释。

## 数据说明

`factors.db`、`check-output/`、`logs/` 等运行数据与产物均不入库(见 `.gitignore`)。
clone 后用 `core/db/schema.sql` / `init_db.py` 重建空库即可。
