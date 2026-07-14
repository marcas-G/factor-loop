# 因子项目重构方案

## Context — 为什么重构

研究循环（brainstorm → runFactor → evaluate）跑通了，但**阅读调试特别累**，四个痛点并存：
- **A 找代码累**：pipeline-mcp 根目录散落 5+ 大文件 + lib/ 与 mcp/lib/ 分两处 + stages/ 与 mcp/tools/ 同名两套，找个功能要在多处猜
- **B 改巨石累**：factor_check.py 2141 行、factor-db.mjs 682 行，改一处怕牵一发动全身
- **C 跨语言契约累**：py 产 CSV / mjs 硬编码解析字段，py 改字段名 mjs 静默返回 null 不报错
- **D skill↔工具协作散**：research-loop/run-factor-agent 的状态机、state 字段约定全靠 SKILL.md 文本，调试要在多份 markdown + 代码间跳

一次全推风险太大。分 4 阶段，每阶段独立可验证、可回滚，按风险从低到高。

## 现状（agent 探索结论）

**pipeline-mcp 分层其实是合理的，问题是根目录散落 + 层级乱**：
- `mcp/server.mjs` 注册 5 类工具（health/factor-db/state/persist/platform）
- `mcp/tools/`（MCP 包装层）→ 调 `stages/`（业务逻辑层）→ 调 `lib/` + 根散落脚本
- `lib/`（config/metrics，通用）vs `mcp/lib/`（run-store，MCP专用）分工合理，**不需合并**
- `stages/`（persist/submit/check/rename/write-factor）现役，**不是旧残留**
- 根散落：`factor-db.mjs`(682 DB库) / `run-py.mjs`(py封装) / `airflow-log.mjs`(分诊) / `inspiration-pool.mjs`+`hypothesis-pool.mjs`(被外部 skill node 调，库内无 import)

**factor_check.py 已半模块化**：compute_*/save_* 自包含（仅依赖 daily_dfs 参数，无全局变量），可独立抽出。只有 `run_analysis_batch`(464行) + `cmd_run`(混平台交互+评估) 耦合紧。

**契约硬编码点**：`metrics.mjs:155-281` 逐字段硬编码（screening/session_ic/vol_regime/zero/train_test/bucket/deep_summary），字段缺失经 `num()` 静默转 null。

## 四阶段方案

| 阶段 | 痛点 | 做什么 | 风险 | 验证 |
|---|---|---|---|---|
| **1. mcp 目录重组** | A | 根散落归位（factor-db→lib/，pools→pools/，run-py/airflow-log→infra/），更新 ~10 处 import + SKILL.md pool 路径 | 低（纯移动+import） | MCP server 启动 + tests + 一次 brainstorm 抽 coords |
| **2. factor_check.py 拆分** | B | compute_*/save_* 抽到 pipeline-py/stages/（按阶段分模块），主流程只编排；解耦 run_analysis_batch/cmd_run | 中 | 同一因子拆分前后输出 diff 一致 |
| **3. py↔mjs 契约显式化** | C | 新建 contract.json（CSV 字段名 + analysis/metric 路由单一源），py 产出 + mjs 解析都引用它，字段缺失报错而非静默 | 中高 | 改字段名 → mjs 立即报错 |
| **4. skill 流程代码化** | D | state.json schema + run-factor-agent 状态机 + research-loop 衔接，从 SKILL.md 文本抽到代码（schema/状态机定义） | 高 | 单测状态机 + 一轮 research-loop 端到端 |

---

## 阶段 1 详细（先做这个）

### 目标目录结构
```
pipeline-mcp/
├── mcp/                  # MCP 服务层（不动）
│   ├── server.mjs
│   ├── tools/            # 5 个工具包装（不动）
│   └── lib/run-store.mjs # MCP 专用（不动）
├── lib/                  # 通用库
│   ├── config.mjs        # （不动）
│   ├── metrics.mjs       # （不动）
│   └── factor-db.mjs     # ← 从根移入（682行 DB库）
├── pools/                # 思维框架（新建）
│   ├── inspiration-pool.mjs  # ← 从根移入
│   └── hypothesis-pool.mjs   # ← 从根移入
├── infra/                # 基础设施（新建）
│   ├── run-py.mjs        # ← 从根移入（py 封装）
│   └── airflow-log.mjs   # ← 从根移入（失败分诊）
├── stages/               # 业务逻辑层（不动）
│   ├── persist.mjs / submit.mjs / check.mjs / rename-factor.mjs / write-factor.mjs
└── server 入口在 mcp/server.mjs
```

### import 更新清单（~10 处 + SKILL.md）
移动后逐个改 import 路径：
- `factor-db.mjs` → `lib/factor-db.mjs`：`stages/persist.mjs`、`mcp/tools/persist.mjs`、`mcp/tools/factor-db.mjs`、`mcp/tools/platform.mjs`、`mcp/server.mjs`（5处）
- `run-py.mjs` → `infra/run-py.mjs`：`stages/submit.mjs`、`stages/check.mjs`、`factor-db.mjs` 内动态 import（3处）
- `airflow-log.mjs` → `infra/airflow-log.mjs`：`stages/check.mjs`（1处）
- `inspiration-pool` / `hypothesis-pool` → `pools/`：库内无 import，但 `.claude/skills/research-loop/SKILL.md` + `brainstorm/SKILL.md` 里 node 调用写死绝对路径，需更新

### 验证
1. `node pipeline-mcp/mcp/server.mjs` 能启动（或 health 工具 ok）
2. `node pipeline-mcp/mcp/tests/*.test.mjs` 全过
3. 跑一次 brainstorm 的 coords 抽取（node import pools/hypothesis-pool.mjs）确认路径通
