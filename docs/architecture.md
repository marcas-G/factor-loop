# factor-autoloop 组件架构

> 量化因子研究自动化系统。本文是组件架构导览——逐环节读的地图。
>
> 重构背景:7 阶段组件架构重构(完成 1-5;阶段6 经核查 research-loop 已近纯编排,跳过)。目标——在 Claude Code 框架内重组件**分层 + 职责 + 契约**,让组件清晰、解耦、可读。

---

## 分层架构(单向依赖,无环)

```
入口层    research-loop          唯一研究入口,纯编排 Step0-4
            │ 调(清晰契约)
能力层    hypothesize │ brainstorm │ write-factor │ assess
         (假设产生)   (候选生成)   (写 .h)       (评估)
            │ 派推理 / 调执行
推理层    reasoners/graph-reasoner │ reviewer      纯推理,输入数据→输出判断
执行层    executors/run-factor                       write→submit→check 状态机
            │ 调
工具层    MCP quant-mcp(42 工具,领域前缀)
         factor_* │ graph_* │ run_* │ platform_* │ persist_* │ discover_* │ ...
            │
数据层    factors.db(db.py + factor-db.mjs 双端 + schema 版本化 + graph_constants 防漂移)

方法论层  hypothesis-framework.md(横切:被推理层/能力层引用,是真相基底)
```

**依赖规则**:入口 → 能力 → 推理/执行 → 工具 → 数据,单向无环。方法论横切(被各层 skill/agent 引用,不向下依赖具体实现)。

> 注:`execute` 能力未独立成 skill——由 `run-factor-agent`(执行层) + `research-loop Step2`(批量编排)共同承担(阶段5 评估:execute 包装层价值不明,且与阶段6 耦合,故不建)。

---

## 各层职责 + 组件 + 契约

### 入口层

| 组件 | 职责 | 契约 |
|---|---|---|
| `research-loop` | 唯一研究入口。纯编排 Step0-4:初始化→假设/候选→执行→评估→汇总。衔接硬规则(每 Step 完成立即下个 tool call,禁止纯文字回合断流)+ 容错兜底 | in: `run_id?`(给则续传) → out: done run + verdict 分布 + idea support_score |

### 能力层(按研究阶段,单一职责)

| 组件 | 职责 | 契约 |
|---|---|---|
| `hypothesize` | 假设产生主入口。知识图驱动 5 操作。卡住(全饱和/触发点尽)返回 `no_hypothesis`,无 fallback | in: `{run_id}` → out: `{idea_id,...}` 或 `{no_hypothesis:true}` |
| `brainstorm` | 候选生成。基于假设产 N 个差异化因子实现(非坐标拼装) | in: `{idea, n_factors, run_id}` → out: factors[] + `persist_candidates` |
| `write-factor` | 写 .h(FeedIndicator 框架规范)。被 run-factor 内嵌调,也可独立触发 | in: spec / diagnosis(诊断驱动修改) → out: `.h` 文件 |
| `assess` | 评估。双轨:忠实度(reviewer 模式二)+ 经验(三维度+一票否决) | in: `{run_id, factor_index}` → out: `verdict{verdict, key_strengths, key_weaknesses, suggested_iteration}` |

### 推理层(`agents/reasoners/`)

| 组件 | 职责 | 契约 |
|---|---|---|
| `graph-reasoner` | 图扩展单步推理。在知识图结构特征处(矛盾/断点/正交缺口/反例)逼出假设,按 S1-S4 + 三道门槛 | in: `{operation, trigger}` → out: `{new_nodes, new_edges, confidence, reasoning_summary}`(不写库) |
| `reviewer` | 对抗式审稿。模式一(假设必然性 S2/S4)/ 模式二(因子实现忠实度)。session 隔离(只收 artifact,不收推理过程) | in: argument_chain(+ 可选 .h) → out: verdict(不写库) |

### 执行层(`agents/executors/`)

| 组件 | 职责 | 契约 |
|---|---|---|
| `run-factor` | 单因子 write→submit→check 状态机。诊断驱动 rewrite,失败分层(failure_layer) | in: `{factor, idea, run_id, factor_index}` → out: `{xname, failure_layer}`(agent 自调 run_save 落盘完整字段) |

### 工具层(MCP `quant-mcp`,42 工具,领域前缀)

按领域 dot-style 前缀(下划线实现,非 dot——MCP 规范允许 dot 但客户端有过滤风险,见重构记录§4):

| 域 | 工具 |
|---|---|
| `factor_*` | search / list / detail / similar / semantic_search / ic_correlate / ic_refresh / counts / recent_lessons / **residual_ic_strength** |
| `graph_*` | query_contradictions / get_subgraph / neighborhood / find_refutation_clusters / stats / add_node / add_edges / mark_contradiction_resolved / mark_contradiction_bounded / angle_coverage |
| `run_*` | init / load / save / list |
| `persist_*` | idea / factor / candidates / argument_chain |
| `hypothesis_*` | get |
| `iteration_*` | open / realize / reopen / list_open |
| `coverage_*` | gaps / map |
| `discover_*` | failed_hypotheses / recent_dead_ends |
| `platform_*` | submit_factor / check_factor |
| — | health |

**双端实现**:Python(`factor_db/db.py`,研究脚本用)+ Node(`pipeline-mcp/lib/factor-db.mjs`,MCP server 用),共读 `graph_constants.json` 防判据漂移。

### 数据层(`factors.db`)

SQLite + sqlite-vec(向量) + FTS5(全文)。
- **schema 版本化**:`schema_version` 表 + `factor_db/migrations.py` 迁移链(当前 v4:baseline / graph_core / graph_bounds / angle)。新库 schema.sql 直建到最新并标版本;老库 `migrate()` 幂等补齐。双端版本同步(test 断言)。
- **分层知识图表**:axioms(AXIOM) / ideas(DERIVED+HYPOTHESIS) / graph_edges(跨表语义边) / lessons / factors / factor_evals / iterations / angle_ontology 等。

### 方法论层(`hypothesis-framework.md`)

**真相基底**,被 4 个执行体(reviewer / graph-reasoner / hypothesize / assess)引用。
- 必然性四级:necessary / identification / conditional / draft
- 假设形式化骨架 argument_chain(S1 Σ / S2 超加性 / S3 约束 / S4 唯一性五type / S6 竞争解释+可证伪trace)
- 三道质量门槛(闭环 L1-L5 / 因果链七节+微观E / 复杂度)
- 双轨验证(忠实度 + 经验三维度)
- **2026-07 共识**:数据驱动默认 conditional,necessary 是 stretch;底线=闭环闭合 + 可证伪 trace

---

## 数据流(一轮 research-loop)

```
Step0  run_init/run_load          初始化或续传 run state
  ↓
Step1  hypothesize {run_id}        产 1 个必然假设(idea_id + argument_chain + grade)
       brainstorm {idea, n:3}      围绕假设产 3 个因子候选 → persist_candidates
  ↓
Step2  Task(run-factor) × N 并发   每个 factor: write .h → submit → check
       (每批 3,兜底 run_load 确认 + 断流根治 + 迭代回滚)
  ↓
Step3  assess {run_id, factor_index} × check_done   双轨评估 → verdict + persist_factor
  ↓
Step4  hypothesis_get support_score + 汇总报告    run_save {status: done}
```

**所有搬砖操作走 MCP 工具**,主会话不直接 Bash/Write 文件(只有 write-factor 通过其内部流程写 .h)。

---

## 重构记录(组件架构重构 7 阶段)

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | agent 分层:`agents/` → `reasoners/` + `executors/` | ✅ |
| 2 | 数据层 schema 版本化:schema_version 表 + migrations.py 迁移链 + 双端同步 test | ✅ |
| 3 | 方法论重写:hypothesis-framework 从反推叙事重写为必然性论证链(argument_chain/S1-S4);消 conditional 矛盾(hypothesis-generator 对齐 reviewer/graph-reasoner) | ✅ |
| 4 | MCP 42 工具领域前缀(下划线,非 dot——规范允许 dot 但客户端有过滤风险) | ✅ |
| 5 | 能力层改名:graph-engine→hypothesize, evaluate→assess(务实子集:不合并 hypothesis-generator/write-factor,不新建 execute) | ✅ |
| 6 | research-loop 纯编排 | ⏭ 跳过(核查:已近纯编排,领域业务规则在能力 skill,下沉目标 execute 未建,无实质工作) |
| 7 | 文档 + 清理:本架构文档 + start-mr 移出 | ✅ |
| 后续 | 删除 hypothesis-generator(去 lens fallback):hypothesize 卡住返回 `no_hypothesis`,research-loop 据 paused。配套修 explore 换角度机制(angle_code 回灌 + 动态优先级 `select_graph_operation`) | ✅ |

---

## 逐环节读导览

想理解某层,从对应文件入手:

| 想理解 | 入口文件 |
|---|---|
| 整体流程怎么跑 | `.claude/skills/research-loop/SKILL.md` |
| 假设怎么产生 | `.claude/skills/hypothesize/SKILL.md` + `agents/reasoners/graph-reasoner-agent.md` |
| 假设怎么审 | `.claude/agents/reasoners/reviewer-agent.md` |
| 因子候选怎么设计 | `.claude/skills/brainstorm/SKILL.md` |
| 因子 .h 怎么写 | `.claude/skills/write-factor/SKILL.md` |
| 单因子怎么跑(write→submit→check) | `.claude/agents/executors/run-factor-agent.md` |
| 结果怎么评估 | `.claude/skills/assess/SKILL.md` |
| 方法论基底(必然性/论证链/门槛) | `.claude/hypothesis-framework.md` |
| MCP 工具有哪些/怎么调 | `pipeline-mcp/mcp/tools/*.mjs`(按领域分文件) |
| 数据库 schema/迁移 | `factor_db/schema.sql` + `factor_db/migrations.py` + `factor_db/db.py` |
| 双端判据防漂移 | `factor_db/graph_constants.json` |

---

## 关键不变量

- **单向依赖**:入口→能力→推理/执行→工具→数据,无环。方法论横切。
- **职责分离**:产生(graph-reasoner)/ 验证(reviewer)/ 落盘(主会话)三者分离;agent 不写库(只 return JSON),主会话据 verdict 落盘。
- **单一真相**:DDL=schema.sql;判据=graph_constants.json;方法论=hypothesis-framework.md。各一处,双端/多组件共读。
- **无 fallback**:图推理耗尽(全饱和/触发点尽)如实返回 `no_hypothesis`,不硬凑假设;research-loop 据 paused。
