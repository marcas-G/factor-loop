# factor-autoloop

量化因子自动挖掘循环 —— 基于 Claude Code 的 `/research-loop` skill,无人值守批量产出因子。
全流程纯 Python,自动完成 **cog-protocol(认知协议发现缺口/发明算子)→ runFactor(write→submit→check)→ assess(评估入库)** 全流程,所有搬砖走 `quant-mcp` MCP server。

框架全景文档: [docs/research-loop-framework.md](docs/research-loop-framework.md)(设计哲学/各 Step 机制/横切质量保障/实证样本)。

## 架构

```
auto-loops.sh                 tmux 单车道循环驱动器(拉起 /research-loop, state.json 检测完成)

.claude/skills/               循环编排 skill 链
  research-loop/              编排器(认知协议 → 跑因子 → 评估)
  cog-protocol/               认知协议(因子表示审查 → 新算子发明,9 cog agent)
  assess/                     评估(忠实度 + 三维度 + 一票否决,写库)
  reseed/                     新基底再播种(饱和分支的去名化换根)
  write-factor/               写因子 .h(agent 内调)
  watch-loops/                后台循环监控

.claude/agents/
  cog/                        认知协议 9 agent(assumption→概念编译→...→reduction)+ 世界模型
  executors/run-factor-agent  单因子 write→submit→check→rewrite 状态机
  reasoners/reviewer-agent    假设忠实度审稿

core/                         全部代码(纯 Python,无 node)
  config.py                   全局路径/环境常量(单一真相,叶子层)
  db/                         因子库 db.py + schema.sql + migrations + seed
  retrieval/                  R1-R3 检索 Contract + 派生表
  cog/                        cog-protocol 程序化部分
                              - evidence_investigate.py   证据引擎 v2(分裂检测/一致性/UNTESTABLE 分流,
                                                          agent contract 优先 + 词表 fallback)
                              - evidence_derive.py        14 原始探针 → 89 派生维度(检验弹药库)
                              - factor_profile.py         双视图隔离(配方袋/成绩袋,盲态假设的地基)
  platform/                   featuretool.py + factor_check.py(平台对接)
  tools/                      AI/IC/embedding 工具 + 测试
  metrics.py                  7 维评估数据聚合(check output → eval_metrics)
  stages/                     submit/check/persist/rename/write-factor 编排
  infra/                      run_py(subprocess 封装)+ airflow_log(失败分诊)
  mcp/                        quant-mcp server(mcp 2.0 SDK)+ 45 工具 + run_store

data/concept_lexicon.json     概念词表(人话关键词→派生列映射,概念编译 agent 的缓存,逐轮生长)
factors/                      因子 .h 产物(92 个:14 探针 + 78 实验因子;库内 evaluated 19 / dead_end 50)
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

⚠️ `data/concept_lexicon.json`(概念词表)目前也落在被 ignore 的 `data/` 下——它是跨轮生长的共享资产,
严格说应受版本控制,待迁移。

## 因子看板

实时看板(纯 stdlib API + React 前端,详见 `dashboard/README.md`)。直接启动:

```bash
python3 dashboard/server.py            # 默认 8765,读 data/factors.db,托管 frontend/dist
python3 dashboard/server.py --port 8901 --db data/factors.db
```

或用 docker compose 部署:

```bash
cd dashboard/frontend && npm run build   # 先构建前端
docker compose -f dashboard/docker-compose.yml up -d --build
# 访问 http://<host>:8765 ; data/ 以只读挂载进容器
```

页面支持搜索、状态/标签/闸门筛选、多列排序、冗余度×预测强度散点、代际趋势、血缘图谱、因子详情、迭代记录与 CSV 导出;筛选/选中状态同步到 URL hash。数据更新不整页刷新,只亮角标,点击才应用。

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
