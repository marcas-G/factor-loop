# factor-autoloop 组件架构

量化因子自动挖掘循环。纯 Python(无 node),一条链:**cog-protocol 发现缺口/发明算子 → runFactor 实现验证 → assess 评估入库**。

## 分层架构(单向依赖,无环)

```
config.py     ← 零依赖(路径/环境常量单一真相)
db/           ← config          数据层(SQLite 因子库 + schema 迁移)
platform/     ← config          平台对接(featuretool/factor_check)
infra/        ← config          subprocess 封装 + Airflow 失败分诊
metrics.py    ← 纯函数           7 维评估数据聚合
tools/        ← db + config     AI/IC/embedding 一次性工具
retrieval/    ← db + config     R1-R3 检索 Contract
cog/          ← db+platform+retrieval  认知协议程序化部分
stages/       ← infra+db+metrics 编排(submit/check/persist)
mcp/          ← db+stages+metrics+infra  quant-mcp server(编排层)
```

依赖只能向下,不可向上。路径常量一律从 `core/config.py` import,禁止业务模块拼 `parents[N]`。

## 各层职责

### 编排层(skills,Claude Code 驱动)

| skill | 职责 |
|---|---|
| `research-loop` | 编排器:认知协议 → 跑因子 → 评估 → 循环 |
| `cog-protocol` | 认知协议:因子表示审查 → 新算子发明(8 cog agent) |
| `assess` | 评估:忠实度 + 三维度 + 一票否决,写库 |
| `write-factor` | 写因子 .h(FeedIndicator 框架) |
| `watch-loops` | 后台循环监控 |

### 数据层(core/db)

- `db.py`(2029 行):全部 DB 访问函数(因子/评估/迭代/lesson/idea/图/检索)
- `schema.sql` + `migrations.py`(v15):schema 版本链
- `seed_axioms.py`:23 条理论公理种子

### 检索层(core/retrieval)

3 个 Capability-scoped 检索 Contract(R4 已删——冗余判定改平台 Ridge-SVD R2_X/res_IC, 不再本地 IC 空间检索):

| Contract | 服务阶段 | 问什么 |
|---|---|---|
| R1 `select_research_object` | Step 0 | 下一只最值得研究的 Factor 是谁 |
| R2 `search_operator_closure` | S2.6 minimal-repair | distinction 是否已在 N2 闭包内 |
| R3 `search_factor_realizations` | S3.4 reduction | 新测量是否已被因子库实现过 |

### 认知协议层(core/cog)

- 程序化部分:`factor_profile`(三视图)/`bridge_validator`(Gate C)/`evidence_derive`(50+ 派生维度)/`evidence_query_compiler`/`register_operator`
- `investigation/`:probe 编译/证据卡/xycache(14 原始探针 .xy)
- 8 cog agent(在 `.claude/agents/cog/`)做语义审查与发明,程序化部分只提供数据与判据

### 编排层(core/stages + core/mcp)

- `stages/`:submit/check(失败分层状态机)/persist/rename/write-factor
- `infra/`:run_py(subprocess 封装)+ airflow_log(Airflow 失败分诊)
- `mcp/`:quant-mcp server(mcp 2.0 SDK,45 工具)+ run_store(run state 管理)

## 数据流(一轮 research-loop)

```
Step 0  run_init → R1 选 Research Object
Step 1  cog-protocol:
          assumption(世界模型 F(A)=F(B)) → evidence(matched 程序层)
          → adjudicator(CONTRADICTS) → hypothesis → distinction
          → minimal-repair v3(R2 查 N2 闭包 + identifiability)
          → Operator Invention(R3 查重 + 4 Gate)
          → register_operator(算子=资产,4 Gate 过即注册)
Step 2  write-factor(contract 或修复路径 → .h)
Step 3  run-factor-agent(submit → check → .xy)
Step 4  assess(平台 restest R2_X/res_IC 查冗余 + 忠实度 + 三维度 + 一票否决)
Step 5  persist_factor + iteration 归档
Step 6  汇总 → 换 Research Object 循环
```

## 关键不变量

- **Research Object = Factor**(不是全局 representation/phenomenon/dead_end)
- **视图隔离**:assumption 只看 construction_view,adjudicator 才看 evidence_view(防 IC 泄漏倒推假设)
- **Truth ≠ Explanation ≠ Depth**:adjudicator(事实)/hypothesis(解释)/minimal-repair(深度)
- **算子=资产,因子=产品**:算子 4 Gate 过即注册(不受 ICIR 影响),因子 ICIR 达标才入库
- **证据程序化**:evidence 派生从 14 原始探针自推断,不信平台 Feed::Cancel/Order
- **IC 判定归 assess**:认知协议只做语义审查+发明,不碰 IC

## 数据

- `data/factors.db`:SQLite 主库(schema v15,18+ 表)
- 探针 .xy 缓存:`/home/lgao/tmp/factor-vec-cache`(QUANT_XY_CACHE 可覆盖)
- run state:`~/.quant-runs/<run_id>/state.json`

## 检索层 R1-R3 的设计原则

**Capability-scoped Retrieval**:每个 Contract 先 SQL 硬过滤 capability 约束,再 vec rerank 语义,最后 log coverage。Agent 拿到的是"问什么",不是"搜什么"——防 agent 自己决定该搜什么导致检索偏离职责。
