---
name: hypothesis-generator
description: 必然假设生成机。从约束耦合矛盾（反常 A vs B）逼出必然假设，产出结构化论证链。触发 `/hypothesis-generator <反常>` 或被 research-loop 调用。替代 brainstorm 的坐标组合式假设生成——生成而非组合。
---

# Hypothesis Generator — 必然假设生成机

## 这个 skill 为什么存在（认识论本质）

**假设 ≠ 对现象的描述，而是对"现象为何是此形态而非彼形态"的必然性断言。**

浅假设给现象贴一个说得通的解释（可替代）；深假设断言现象**依赖**于某机制——抽掉它，现象就崩塌。深浅的分野全在"必然性"。

两种范式根本对立：

- **组合机**（旧 brainstorm）：预先造好零件库（`PROFIT_SOURCES × DIMENSIONS`）→ pick → 拼装 → 测 IC。零件库里没有的东西 pick 再多也 pick 不出来。它产出的是"恰好相关"，不是"必然如此"。
- **生成机**（本 skill）：从一个**约束耦合矛盾**出发 → 施加约束 → **求约束下的必然解**。解不是被选的，是被**逼出来**的——运动方程不是列举的，是被最小作用量原理生成的。

**生成 = 施加约束，求必然解。** 机器只有一个动作——求解，不挑零件。

**必然性的来源**：必然性只能来自约束的**非平凡耦合**（两个约束联合逼出一个它们各自都逼不出的结论）。单独的约束再多，互不牵制，也不产生必然性（这就是"算子硬拼"为何浅——坐标组合但无机制耦合）。所以核心动作是**找到约束之间的耦合**，不是堆砌维度。

一次只产 **1 个深假设**（必然解是被逼出的，不是批量挑选的）。

---

## 输入

### 衔接① · 归纳引擎自动喂（优先：先拉模式卡）

若归纳引擎在跑（`pattern_cards` 有 archived 卡），**先调 `pattern_feed {top_n: 3}`** 拉 archived 高优先 + 未解释的模式卡（统计已验证的异常：F/T/C/S/Y/H/R 坐标 + 证据）。

- **有模式卡**：以其为"已验证异常"，解释它的**机制**（F 为何在 S 结构、C 条件下预测 Y）。模式卡给的是统计事实，本 skill 逼出"为何必然如此"的论证链：用 data-lens 深挖该 F 的机制（`lens_orderflow`/`lens_condition`/`lens_memory`）→ 构造约束耦合矛盾（S 结构常含矛盾，如 bsi_ask 负 vs bsi_bid 正 = 方向不对称耦合）→ S1-S4。**产 idea 后必须调 `link_pattern_idea {pattern_card_id, idea_id}`** 回写（archived→explained），闭合衔接①。
- **无模式卡**（库空/都解释过）：走下面的 lens 自主发现反常。

### lens 自主发现反常（无模式卡时）

**LLM 自主调 data-lens 发现反常，构造约束耦合矛盾（不人给）**：

1. 调 `mcp__data-lens__lens_synthesize`（洞察卡）/ `lens_predictive` / `lens_memory` / `lens_condition` / `lens_orderflow_dynamics` 等观测数据
2. 从观测识别**反常**（违反机制预期 / 跨维度矛盾 / 异常形态）—— 如收益自相关违反 Roll MA(1) 签名、Hurst 偏离 0.5、条件 IC 跨 regime 反向
3. **构造约束耦合矛盾**（反常 vs 机制预期，形式化为约束耦合矛盾 A vs B）—— 这是 LLM 自主发现，不人给
4. 进入 S1-S4 推必要/identification 假设

反常形态：命题矛盾 / 理论 vs 数据 / 认识论缺口 / 上下界夹逼 / 多目标牵制（从 data-lens 观测识别）。

**data-lens 是观测手段**（给 LLM 看数据的能力），不是或然降级渠道。发现的反常仍走 necessary/identification 严筛，不降级 conditional/draft。
- `parent_idea_id`（可选）：迭代/精化某已有假设时填。

### 多轮自适应深挖（AI 自主探索找蛛丝马迹）

不只一次调 lens，**多轮迭代自适应探索**——每轮看上轮结果，决定下轮调哪个 lens/字段/参数，累积反常线索。这是"找蛛丝马迹"的核心：单轮看不全，多轮追线索。

**轮 1 · 广扫圈候选**（覆盖全字段）：
- 调 `mcp__data-lens__lens_predictive`（184 字段 × 5 horizon IC 矩阵）→ 圈跨 horizon 反常 / 异常强或弱的字段
- 调 `mcp__data-lens__lens_synthesize`（洞察卡）→ 多层 join 的综合视角
- 产出：反常候选字段清单（~5-20 个值得深挖的）

**轮 2 · 对候选多维深挖**：
- 调 `mcp__data-lens__lens_condition`（**多维交叉**：session×direction×volatility 组合状态条件 IC）→ 看候选在哪些组合状态反向/突变
- 调 `mcp__data-lens__lens_memory`（Hurst）→ 看候选的记忆性反常（偏离 0.5）
- 调 `mcp__data-lens__lens_interact`（字段×方向交互）→ 看组合反常
- 调 `mcp__data-lens__lens_crosscontract`（跨合约/品种）→ 看传导反常
- 产出：每个候选的多维条件/记忆/交互/传导画像（深挖后的蛛丝马迹）

**轮 3 · 机制视角**（对最深挖的反常）：
- 调 `mcp__data-lens__lens_orderflow_dynamics`（OFI 冲击/衰减τ/惯性）→ 订单流机制
- 调 `mcp__data-lens__lens_event_clustering`（Hawkes 聚类）→ 事件机制
- 调 `mcp__data-lens__lens_state_topology`（PCA/典型态）→ 状态机制
- 产出：反常的机制层解释候选

**自适应**：每轮看上轮结果决定下轮——
- 轮 1 发现 OFI 跨 horizon 非单调 → 轮 2 调 lens_condition 看 OFI 的多维条件（哪个组合状态反向）→ 轮 3 调 lens_orderflow 看 OFI 冲击衰减是否异常
- 轮 1 发现某字段 Hurst 异常 → 轮 2 调 lens_condition 看记忆性是否状态依赖 → 轮 3 调 lens_state_topology 看状态切换
- 追线索，不固定流程

**产出**：累积反常线索 → 选最强（最显著 + 最稳健 + 最深机制可解释）→ 构造约束耦合矛盾（反常 vs 机制预期，A vs B 约束耦合）→ 进入 S1-S4。

**多轮不限 3 轮**——有线索就继续追（轮 4+ 对深挖反常换参数/品种/合约再测）。线索枯竭（无新反常）才停，进 S1-S4。

### 约束耦合矛盾的无知类型标注（决定"可攻"vs"诚实承认"）

构造约束耦合矛盾时，标注它的**无知类型**——决定这个反常能否通过假设减少（值不值得攻）：

| 无知类型 | 含义 | 可减少？ | 系统动作 |
|---|---|---|---|
| **公理性**（经验 vs 理论不相容） | 反常违反理论预期（如 AG 自相关非 Roll MA(1)、imb 因果倒置） | ✅ 可减少 | **攻**——进 S1-S4，假设解释新机制 |
| **解释性**（反常没形式化） | 反常存在但写不成 A vs B 约束耦合 | ✅ 可减少 | 清晰化（形式化为公理性再攻） |
| **群体无知**（未覆盖方向） | 未测品种/lens/条件/参数 | ✅ 可减少 | 扩研究（调 data-lens 测未覆盖） |
| **逻辑性**（Σ 天花板） | S2/S4 反复 fail（K≥3），Σ 内无解 | ❌ 不可减少 | **paradigm 异常**——交人换 Σ |
| **现象学**（混沌/相变） | 本质不可预测的市场现象（如某些相变/临界） | ❌ 不可减少 | **诚实承认**——标现象学，不硬解 |

**优先攻公理性无知**（数据反常违反理论——假设能减少它，产必要/identification）。逻辑性/现象学不可减少——系统诚实承认（paradigm/标注），**不硬解**（避免"封闭的无知"——不愿承认 Σ 外有东西）。

**假设 = 减少无知**：假设的质量 = 减少无知的程度。
- **necessary** = 完全减少（数学唯一，无知消除）
- **identification** = 部分减少（可识别，但机制不唯一——残留可减少的无知）
- **paradigm** = 不可减少（逻辑性无知，换 Σ 才能继续）

这个标注让系统**把精力集中在可减少的无知上**（公理性反常→假设），不在不可减少的（逻辑性/现象学）上浪费（诚实承认即可）。

---

## 流水线 S1-S4 + 对抗审稿

### S1 · 背景公理集 Σ（显式陈述）

显式写出本次接受的背景共识作为 Σ（公理基）。不靠人输入——Σ 错了由 paradigm 检测器兜底（反复卡住报警）。

Σ 是后续推导的起点。每个 Σ 条目必须是**可被独立攻击的经验命题**，不能是定义（定义不可证伪，不能当公理）。例：`"价格变化源于净订单流不平衡"` 是经验命题；`"市场由供需构成"` 是定义，不算。

### S2 · 超加性耦合（从反常逼出 C）★核心动作

从约束耦合矛盾找 A、B、C 满足**三条件**：

```
① A ∧ B ⊢ C        (联合蕴含)
② A ⊬ C 且 B ⊬ C    (超加性:任一单独推不出)
③ C 是 A∧B 的最小非平凡蕴含  (非 C=A∧B 这种平凡)
```

**为什么是这个判据（辩证依据）**：

必然性来自约束的耦合。但"耦合"不能做成类型清单（{矛盾型, 夹逼型, 缺口型, ...}）——那是组合思维的复发，每碰到新形态就加类型，永远枚举不完。三条件是**关系性判据**：它不关心 A/B 是命题、目标还是域条件，只判定它们联合时是否产生**超加性蕴含**（A∧B 蕴含了 A、B 各自都不蕴含的 C）。任何形式的耦合（矛盾/夹逼/缺口/多目标）都是超加性的投影，自动被涵盖。

- ① 是耦合存在（联合能推出新东西）
- ② 是耦合非平凡——**伪耦合检验**：若 C 其实被 A 或 B 单独蕴含，则"耦合"是装的
- ③ 是耦合有内容（不是 A∧B 的平凡重述）

C 是被 A、B 牵制**逼出来**的必然解。约束耦合矛盾就是 A 与 B 牵制的源头。**找不到超加性耦合 = 没有必然性根基 = 这个约束耦合矛盾产不出深假设，换一个。**

### S3 · 固化约束

把 A∧B 写成可解的约束形式。**不预设** conjunctive / multi_objective / domain_conditional——约束的形态是耦合结构的**投影**（多目标牵制自然写成优化、跨域矛盾写成条件约束），不是事先选的类型。

### S4 · 唯一性证明（必然性四来源指导）

唯一性的"必然"从哪来？有且仅有四种来源。选 type 时对照——你的必然性是哪一种？

| 必然性来源 | 含义 | 对应 type | 典范 |
|---|---|---|---|
| **逻辑必然** | 从优化目标+约束解出唯一策略 | `extremum`（严格凹/凸→唯一极值）/ `contraction`（压缩映射→唯一不动点） | Kyle 利润严格凹→唯一最优交易量 |
| **对称/守恒必然** | 某量必须守恒或无套利，否则系统不自洽 | （约束层体现） | Gatheral 无价格操纵→冲击衰减凸非增 |
| **因果必然** | 信息若存在，必然在某可观测量上留痕 | `minimal_sufficient`（最小充分量，去任一分量则失效） | OFI 订单流不平衡必然含信息 |
| **结构必然** | 统计量的符号/形态由底层结构唯一决定 | `equivalence`（可测↔不可测解析等式）/ `zero_dof`（解流形 0 维+Hessian 非奇异） | Roll 负自协方差↔价差 |

**`identification` 是弱类型**（可识别标量，非机制唯一）——用于 equivalence 被反例击穿等"S2 硬但 S4 退化"的诚实降级，pass 时 grade=identification 而非 necessary。

**拒绝伪唯一性**：必须给出对应 type 的**真论证**（extremum 要证严格凹的二阶条件，equivalence 要给非平凡 iff 非移项）。"显然唯一""自然唯一"是断言不是论证——reasoning 去掉后结论若仍成立，说明 reasoning 是装饰。reviewer 会拦。

> 为什么回到四来源：五 type 是操作清单，但选 type 时若不知"必然性从哪来"，就会乱贴标签（声称 extremum 却不证严格凹）。四来源是 type 的**判据根基**——type 必须对应一个真实的必然性来源，否则是类型错配。

### grade 分级（严，不降级）

- **necessary**：S2 真超加性 + S4 真唯一性证明（四来源之一，数学封闭）。严。
- **identification**：S2 硬核 + S4 退化为可识别标量。诚实降级（Roll 式，论文级）。

**不接受 conditional/draft**——不降严谨。data-lens 观测发现的反常，仍走 necessary/identification 严筛。

### 审稿（派 reviewer-agent，session 隔离）

**在一个消息内** Task 派 reviewer-agent，prompt **只含论证链 artifact**（不含作者的推理过程）：

```
Task({
  subagent_type: "reviewer-agent",
  prompt: "对抗式审稿以下论证链（尽力反驳）:\n" + JSON.stringify({text, argument_chain})
})
```

> 为什么 session 隔离：产生（找支持）和验证（找反驳）是**认知相反**的动作。同一 context 做两件事会系统性偏向确认。隔离后审稿人只面对成品（像独立投稿），被迫独立判断。这是角色分离从概念到物理的落地——没有它，"对抗"退化成"自评"。

### fail 后分流（框架的 S8 失效分诊）

reviewer 的 fail 不是"重试"，是按**失效根因定向分诊**。按 `achievable` 字段：

- **`fixable`**：论证不足（entailment/reasoning 缺步骤），或 C 过宽（C 声称了 type 未实际证明的东西）。→ 补论证；或收紧 C 到 type 真证的 scope（C 应是 A∧B 的最小纯蕴含，S2 minimality 要求——若 C 越过了 type 能证的范围，收回）。
- **`degrade_suggested`**：当前 type **天然不可达**（被反例击穿，如 equivalence 被 MA(1) 同构击穿——二阶矩不识别分布）。→ 按 `degrade_suggestion` 降级 type，诚实标注 grade。
- **`unreachable`**：无超加性硬核 / Σ 错。→ paradigm 异常，交回人。

**衔接硬规则**：reviewer 返回后，立即在同一回合发下一步 tool call（pass→persist / fixable→定向修 / degrade→降级重审 / unreachable→paradigm）。禁止纯总结文字回合。

> degrade 的辩证：降级是**诚实标注 grade**（承认 S4 退化），**不是降低 necessary 标准**。necessary 仍要过 S2+S4 真硬证；identification 是"S2 硬但 S4 退化"的合法位置（Roll 式可识别标量）。两者泾渭分明——support_score 聚合时按 grade 加权。

---

## S6 预填（本阶段不审，但 persist 时必含）

- `competing_explanations`：**至少 2 个**竞争解释 + 各自区分观测。这是防 VPIN 式遗漏（VPIN 漏了波动率这个显然竞争解释）。列时问自己："还有没有显然的替代机制被我漏了？"
- `falsifiable_trace`：解→X 的演绎预言。**抽掉机制 X，现象形态应崩塌**——抽掉后现象还在，说明 X 不是必然原因，假设假。

---

## 必然性分级的辩证（grade 不是标签）

| grade | 含义 |
|---|---|
| `necessary` | 过 S2 超加性 + S4 真唯一性证明（数学封闭） |
| `identification` | S2 硬核 + S4 退化为可识别标量（非机制唯一） |
| `conditional` | S2 有、S4 弱 |
| `draft` | 待补 |

**关键辩证**：
- **必然 ≠ 经典**。一个案例发顶刊、被高引、是诺奖工作，**不等于**它是必然假设。ACD（Engle-Russell）是 Econometrica 论文，但它是**类比**（GARCH→duration 结构同构），类比是或然推理，不产生必然性——挡门外。判据独立于案例声誉。
- **框架的严格性由"拒绝什么"定义**。什么接纳的机器没有标准。necessary 标准不动，是为了让框架区别于"枚举所有有效研究"的集合思维。
- **或然假设挡门外不是损失**。框架是"必然假设生成机"，不是"通用研究机"。或然研究走另一套验证（跨域迁移稳健性），不该混入必然框架稀释标准。

---

## 持久化

调 MCP `persist_argument_chain` 写 ideas 表（论证链是**假设**的属性，放 ideas 非 factors——一假设挂多因子，层级不能错）：

```
persist_argument_chain {
  text: "<30-80 字假设陈述>",
  argument_chain: { background_axioms, superadditive_coupling, constraint,
                    uniqueness_proof, competing_explanations, falsifiable_trace },
  necessity_grade: "<reviewer pass 时给的 grade>",
  parent_idea_id: <可选>
}
```

返回 `{idea_id}`——假设的持久身份，贯穿后续因子链路。

---

## 范式异常（哥德尔天花板）

若 S2/S4 反复修正（K≥3）仍过不了 reviewer，且不是 C 过宽/type 不可达能解释的：**可能撞 Σ 天花板**。

- ❌ 不硬解（会在错误公理基上产伪必然性）。
- ✅ 标 `paradigm_anomaly`，交回人，建议「更换背景公理 Σ」。

> 任何固定 Σ 上的机器，受不完备定理约束——只产 Σ-可证的必然解，产不出 Σ-真但不可证的解。Kyle 当年引入"线性定价"假设本身（换 Σ），不是在旧 Σ 内求解——这种 paradigm shift 需要人。机器识别"撞顶"并诚实报告，不假装能自动突破。

---

## 不要做

- ❌ 从 `hypothesis-pool.mjs` / `inspiration-pool.mjs` 抽坐标（组合机，产不出必然性）。
- ❌ 一次产多个浅候选（必然解是被逼出的，不是批量挑选）。
- ❌ 散文 hypothesis（必须结构化论证链——散文无法被逐字段攻击）。
- ❌ 跳过 reviewer 直接 persist（对抗验证是质量引擎，非可选）。
- ❌ 把经典性当必然性（顶刊/诺奖 ≠ 必然，看演绎内核）。
- ❌ 用断言代替论证（"显然唯一"是伪唯一性）。
