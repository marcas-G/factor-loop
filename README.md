# factor-autoloop

量化因子自动挖掘循环 —— 基于 Claude Code 的 `/research-loop` skill,无人值守批量产出因子。
全流程纯 Python,自动完成 **cog-protocol(认知协议发现缺口/发明算子)→ runFactor(write→submit→check)→ assess(评估入库)** 全流程,所有搬砖走 `quant-mcp` MCP server。

## 架构

```
auto-loops.sh                 tmux 单车道循环驱动器(拉起 /research-loop, state.json 检测完成)

.claude/skills/               循环编排 skill 链
  research-loop/              编排器(认知协议 → 跑因子 → 评估)
  cog-protocol/               认知协议(因子表示审查 → 新算子发明,8 cog agent)
  assess/                     评估(忠实度 + 三维度 + 一票否决,写库)
  write-factor/               写因子 .h(agent 内调)
  watch-loops/                后台循环监控

.claude/agents/
  cog/                        认知协议 8 agent(assumption→...→reduction)+ 世界模型
  executors/run-factor-agent  单因子 write→submit→check→rewrite 状态机
  reasoners/reviewer-agent    假设忠实度审稿

core/                         全部代码(纯 Python,无 node)
  config.py                   全局路径/环境常量(单一真相,叶子层)
  db/                         因子库 db.py + schema.sql + migrations + seed
  retrieval/                  R1-R3 检索 Contract + 派生表
  cog/                        cog-protocol 程序化部分(evidence 派生/探针/算子注册)
  platform/                   featuretool.py + factor_check.py(平台对接)
  tools/                      AI/IC/embedding 工具 + 测试
  metrics.py                  7 维评估数据聚合(check output → eval_metrics)
  stages/                     submit/check/persist/rename/write-factor 编排
  infra/                      run_py(subprocess 封装)+ airflow_log(失败分诊)
  mcp/                        quant-mcp server(mcp 2.0 SDK)+ 45 工具 + run_store

factors/                      因子 .h 产物(19 个:14 探针 + 5 入库因子)
data/                         factors.db(运行数据,不入库)
```

## 起循环

### 1. 装依赖(纯 Python,无需 node)

```bash
# 用 quant-venv(含 sqlite_vec/pandas/sentence_transformers/mcp 2.0)
export QUANT_VENV_PY=/path/to/quant-venv/bin/python

# MCP SDK(Claude Code 连 quant-mcp 用)
$QUANT_VENV_PY -m pip install mcp -i https://mirrors.aliyun.com/pypi/simple/
```

### 2. 建空因子库

```bash
$QUANT_VENV_PY core/db/init_db.py   # schema.sql 建空库 + 预填 23 axiom
```

### 3. 配 MCP

`.mcp.json` 已指向 `$QUANT_VENV_PY core/mcp/server.py`。改 `QUANT_MCP_RUNS_ROOT` 指向你的 run state 目录(默认 `~/.quant-runs`)。

### 4. 跑循环

```bash
mkdir -p logs/loops
nohup bash auto-loops.sh 1 > logs/loops/auto.out 2>&1 &
tail -f logs/loops/auto.out
```

用法/停止/参数见 `auto-loops.sh` 头部注释。

## 数据说明

`data/factors.db`、`check-output/`、`logs/` 等运行数据与产物均不入库(见 `.gitignore`)。
clone 后用 `core/db/init_db.py` 重建空库即可。

## 分层依赖规则

依赖只能向下,不可向上:

```
config     ← 零依赖(叶子,路径常量)
db         ← config
platform   ← config
infra      ← config
metrics    ← 纯函数
tools      ← db + config
retrieval  ← db + config
cog        ← db + platform + retrieval + config
stages     ← infra + db + metrics
mcp        ← db + stages + metrics + infra
```
