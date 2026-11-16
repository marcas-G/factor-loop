# 03 · 核心数据契约（RFC 0.1）

本目录中的 JSON Schema 为**拟议的输入边界**；当前仓库生产数据库和 MCP API 还不消费它们。不能将 schema 存在解释为功能已实现。

## 对象之间的关系

```text
ResearchTheme(id, text)
   ├─ Phenomenon(id, source/data provenance) ----------+
   └─ HypothesisNode(id, tree_id, claim, unknowns) <-----+
          | refinement warrant
          v
      HypothesisNode(child)
          | tests
          v
      ExperimentDesign(id, competing_predictions, time boundary)
          | optional translation
          v
      FactorSpec(name, formula, params, categories) --> existing persist_candidates
          | execution
          v
      Evaluation/EvidenceResult --> evidence link to experiment and node
```

已有 `ideas.parent_idea_id`、`factor_lineage_edges` 等结构保持原语义，不做字段复用式迁移。

## 契约索引

| 契约 | 对应文件 | 必填的关键语义 |
|---|---|---|
| `Phenomenon` | [schemas/phenomenon.schema.json](schemas/phenomenon.schema.json) | 观测差异、匹配条件、来源数据/窗口、是观察不是解释 |
| `HypothesisNode` | [schemas/hypothesis-node.schema.json](schemas/hypothesis-node.schema.json) | 单一可描述主张、机制角色、前提、未知项、证据状态、继续细化的问题 |
| `RefinementEdge` | [schemas/refinement-edge.schema.json](schemas/refinement-edge.schema.json) | 父子节点、细化操作、refinement_warrant、new_information |
| `ExperimentDesign` | [schemas/experiment-design.schema.json](schemas/experiment-design.schema.json) | 竞争解释及独有预测、控制与变化、混杂、数据权限、时间先后 |
| `FactorHandoff` | [schemas/factor-handoff.schema.json](schemas/factor-handoff.schema.json) | 将可实现假设交给现有 `persist_candidates` 需要的 factor 字段、来源链路 |

## HypothesisNode 不是 Fact，也不是 Factor

- `statement` 为当前主张；`unknowns` 是当前仍欠缺的信息。
- `node_status` 表示研究推进（open, ready_to_test, blocked, archived）；`evidence_status` 表示证据认识状态（untested, provisional_support, provisional_conflict, mixed, unidentifiable）。二者必须独立。
- `source_phenomena` 只引用观察记录；不能把观察当成已经完成的因果解释。
- 可选附加的 `factor_xname` 只能在真实运行形成因子后存在；Tree 节点永远不能以 `factor_xname` 为主键。

## Refine(node) 的最低接受条件

- 新主张相对父节点产生了**可陈述的信息增量**；禁止同义改写伪装。
- 必须给出 `refinement_type` 与 `refinement_warrant`，说明角色、条件、机制、区分性预测或可观察要求改变了什么。
- 不允许静默更换研究问题。若子节点改变了问题而不是细化父节点，应独立建新树或用相关引用。
- 如果存在多个可能机制，竞争解释和证据状态应保留，不强迫选出“赢家”。
- 不能以是否得到高 IC 替代解释细化是否成立的判断。

## ExperimentDesign 与当前 Test Contract 的接口

当前 `core/cog/investigation/contract.py` 强制以下概念：`challenged_equivalence`、`task_context`、`controls.must_hold_similar`、`variation.dimensions_allowed_to_change`、`competing_predictions.H1/H2/H3/H0`、观察要求、成功/失败模式、混杂、数据要求。

TreEvo 的 `ExperimentDesign` 在**上游**记录较通用的独特预测和数据访问边界；需要通过显式 adapter 编译为现有 `Test Contract`。不能直接把拟议 JSON 当作当前 `contract.validate()` 的合法输入。

编译过程必须检查：
- 抽象概念与数据代理的映射是否有效（DIRECT / DERIVABLE / PROXY_ONLY / UNIDENTIFIABLE）。
- `feature_end_offset_ms <= label_start_offset_ms < label_end_offset_ms`。
- 观测设计与真正随机干预必须区分；只使用历史行情时 `causal_claim_level` 限定为 `associational`。
- 训练/探索/筛选/确认数据权限，避免在确认集上自适应继续探索。
- H0 和每个竞争机制至少有独立可判别的观测预测；不足则保持 OPEN，不强制执行。

## FactorHandoff 对现有执行流程的映射

`FactorHandoff.factor_spec` 中：
- `name`, `formula`, `intuition`, `tags`, `params`, `categories`, `hypothesis` → 可映射到现有 `persist_candidates.factors[]`。
- `categories` 在当前执行接口中的语义是品种代码，**不是分类标签**。
- `source_node_id`、`experiment_id`、`derivation_reason` 等上游来源元数据**暂不受现有 API 保障**；需要先增加专门的持久化关系或日志索引，不能盲传未知字段并假设已落库。
- 设计支持由多个假设/实验生成同一个或不同因子；一个因子实验失败不构成父机制的逻辑否定。

## 证据归属

程序层证据：实验配置、数据版本、程序状态、结果路径、统计量与对照结果。
Agent 层解释：为什么这些结果与某种机制相容、矛盾或无信息。
权威层：外部程序核验的执行记录与可重算结果引用。Agent 不能自行声明测试执行完毕。

所有样例都标为 `illustrative_only`，不可用于真实结果展示。
