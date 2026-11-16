# 02 · 目标架构（TO-BE，逻辑模块）

## 核心目标

TreEvo 是 **Hierarchical Hypothesis Refinement**：从高层经济/市场主题出发，针对证据缺口与解释空白，逐层分析、拆解并细化假设；不是遗传表达式搜索器。

系统不强迫所有主题直接生成公式；一棵研究树可以含大量未解决和不可识别节点。Tree 是研究解释的组织结构，Experiment 是对主张的观察/验证操作，Factor 是其中一种可执行测量实现。

## 双入口 / 同一个实验后端

```text
入口 A（现有，保持兼容）：
    Factor -> profile -> assumption critique -> evidence -> repair/operator
             -> FactorSpec ----------------------------------------------+
                                                                         |
入口 B（TreEvo，新增）：
    Theme -> [Phenomenon/Problem] -> HypothesisNode                      |
      -> refine (机制 / 条件 / 竞争解释 / 路径 / 可观测化)                |
      -> ExperimentDesign -> observable distinction                      |
      -> FactorSpec（可选，达到可测量时才编译） --------------------------+
                                                                         |
                          统一 factor execution (现有) <------------------+
                             write .h -> submit -> check -> restest
                                        -> assess -> persist
                                                 |
                           evidence records / lesson / open questions
                                                 |
                  回写相应 HypothesisNode 状态 + 待进一步细化的缺口
```

没有 ExperimentDesign 或 FactorSpec 的中间节点可以长期保持 OPEN / BLOCKED；**不是失败的因子**。

## 逻辑层次与运行边界

| 逻辑层 | 标准职责 | 现有可复用 | 新增 / 暂不实现 |
|---|---|---|---|
| Theme Intake | 明确宽泛研究主题与观察范围 | 局部的 idea/seed | 主题节点、问题范围 |
| Phenomenon Acquisition | 采集有可追溯来源的观察性矛盾/差异 | `phenomenon_miner` | 现象契约、筛选偏差记录 |
| Hypothesis Refinement | 机制/条件/过程/竞争解释逐层细化 | 认知 agent 的部分语义能力 | 逻辑树节点、typed-edge、细化理由 |
| Experiment Design | 区分性预测、数据来源、控制、混杂与可观测性 | `investigation/contract.py`、探针、编译器 | 通用设计契约与预注册/数据拆分 |
| Factor Compilation | 将成熟测量要求翻译成实现规范 | repair/operator/seed contract, `write-factor` | 版本化的手递手 mapping |
| Execution + Assessment | 运行平台并收集实际证据 | 现有 stages/platform/assess | 原因与结果分离、审计字段 |
| Knowledge Ledger | 节点、证据、选择历史、失败约束 | db ideas/lessons/lineage | typed tree 和独立尝试账本 |
| Session Runtime | 唯一执行状态、隔离、终止、恢复 | run_store/auto-loops | lease、transition guard、idempotent resume |

这张表是**逻辑能力划分**，不是立即移动现有 `core/` 文件夹的重构方案。先通过接口解耦，长期稳定后再考虑物理拆仓。

## TreEvo 的五种细化语义（不预设固定深度）

1. `mechanism_decomposition`：把解释拆成机制角色、活动或相互作用，必须说明每个角色的功能。
2. `condition_specification`：收紧成立条件或分辨边界，必须指出排除/保留了哪些情况。
3. `competing_explanation`：指出可以同时解释现象的另一种机制及它独有的预测。
4. `process_elaboration`：展开事件顺序、时间过程、中间环节/潜在黑箱。
5. `operationalization`：从理论概念转换成可观察量、代理和限制，而不是偷偷等同概念与字段。

每条边都要包含 `refinement_warrant`（为什么这一步构成解释细化）和 `new_information`（增加了何种机制或限制）。**节点内容的长度、树的深度、候选 IC 分数均不能代替有效细化判断。**

## 研究抓手（Phenomenon First，但是树仍从逻辑出发）

当主题过于开放时，系统可用 Phenomenon 作为细化约束；不强迫每个子节点都源自已发现的高分因子。例如：

```text
Theme：量价结合
Phenomenon：相似的 pre-t 失衡量，却存在不同的 t 后价格响应轨迹
Gap：当前描述无法区分这两类路径
Node：冲击响应可能还取决于事件前的承接状态
   ├─ 边 A：mechanism_decomposition → 承接可分成即时深度和补充过程
   └─ 边 B：competing_explanation → 差异也可能由事件前波动状态解释
Experiment：相同基线条件下，分组观察未来响应是否不同
   -> 仅当可观测、时序合法、预注册比较条件后：FactorSpec / 代码
```

此例为概念示意，不是实证事实。“分组观察到差异”不能直接宣称“承接导致价格响应”。

## 不强迫树封闭

- 父节点可以有多个 competing hypotheses。
- 某些子节点的解释可被反驳，同时父节点仍然 OPEN。
- 一个节点可以由多个独立证据引用，不能因为某个因子失败就把整棵树标为 fail。
- 横向交叉关系可在树外用 `related_to` / `tests` / `derived_from` 链接表示，避免为了表现关系将树变成语义不清的 DAG。
- 在未设计隔离数据的条件下，只能声称探索性结果，不应升级为确认性结论。
