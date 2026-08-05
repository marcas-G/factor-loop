---
name: concept-invent
description: 算子驱动的因子挖掘（通道B）。触发 `/concept-invent <故事节点xname?>` 或被 research-loop Step1 嵌套调用。故事节点→想缺口→查算子库（复用or发明）→实现→评估→抽算子入库。算子为主体，因子为应用实例。
---

# Concept-Invent — 算子驱动的因子挖掘

**核心认知**：
- **因子是产品，算子是资产。** 挖因子的真正产出是算子（可复用测量方法），不是那个因子。
- **故事是生长的树。** 四个基底（Imbalance/Mom/Activity/OiChange）是根，每个已挖因子是新故事节点，任何节点都能继续挖。
- **算子要复用也要发明，由 AI 主观判断**（不套客观规则）。但判断前提是脑子里有算子库（记忆）。
- **缺口判断和算子匹配必须两步分离。** 先独立想缺口（不看库）→ 再拿缺口查库。一起给会生搬硬套。

## 工作环境

- **算子库**（主体，v12 新建）：`operators` 表 + `operator_family_edges`（撞族边界）。查库用 SQL 或 `factor_db/concept_query.py`。
- **故事树**：`iterations` 表（from→to + op_id）。任何因子的故事节点都能当挖掘起点。
- 辅助：`concept_critic.py`（四检查）/ `concept_compiler.py`（契约→实现）/ `concept_assess.py`（四闭包→五级状态）。

## 流程（五步）

### Step 1 · 选故事节点（主观）

- 给了 `<xname>`：从该因子的故事出发挖（读 `factor_detail` 的 intuition/formula）。
- 没给：AI 主观选一个故事节点——可以是基底根（Imbalance/Mom/Activity/OiChange），也可以是任何已挖因子（BreachRunPersistence/ShockAbsorption/...）。**选哪个都行，只要那个故事有可挖的缺口。**

读故事时只读它的 intuition + formula（机制叙述），理解它在讲什么市场现象。

### Step 2 · 想缺口（隔离算子库！）

**这一步禁止看算子库。** AI 只看故事，独立想：

> 这个故事哪里没讲完？什么力量/状态/过程没被量化？

纪律：
- **缺口定义用故事自己的语言**（"对手挡不挡""消耗速率""弹性怎么变"），**禁止借算子库的词**（不能说"用对手吸收算子"）。
- 缺口要落到机制层面，不落到公式（"需要量：连击推力发生时被冲击侧资源被消耗的速率"，不是"bid-ask size 的 EMA 变化"）。
- 一个故事可挖多个缺口（五问辅助：时间结构/状态条件/力量来源/对手/失效边界），但每个缺口独立成条。

输出：缺口列表（纯故事语言，每条一个未量化的机制）。

### Step 3 · 查算子库匹配（复用 or 发明）

拿 Step 2 的每个缺口，查 `operators` 表全貌（定义 + 撞族边界 + 配过什么基底）。**AI 主观判断**：

- **缺口像某个已有算子？** → **复用**：用该算子，但换一个**未试过 / 未撞族**的基底。
  - 查该算子的 `operator_family_edges`：× 哪些基底撞过哪个族，避开已撞的。
  - 例：缺口像"对手吸收"算子 → 查它的撞族边界 → ×size 撞了 imbalance → 换 ×成交量 / ×spread / ×OI 基底。
- **缺口不像任何已有算子？** → **发明**：定义新算子（纯抽象，方向中性，多实现，可证伪）。来源任选：五问挖强因子 / 失败教训反推 / 市场微观结构理论。

这一步的判断全由 AI 主观，不套饱和度阈值、不套连续失败计数。看着库，自己判断像不像。

### Step 4 · 实现成因子（算子 × 基底 × 参数）

把选定的（算子 + 基底）编译成具体因子：
- 复用路径：已有算子的 abstract_structure + 新基底字段 → 具体 .h
- 发明路径：新算子定义 → 用 500ms 快照可观测数据写出实现（事件时间/订单级依赖禁止）
- 调 `write-factor` skill 生成 .h（复用现有流程）
- 约束：≤2 实现、1 组固定参数、swap 变体验证方向性质（最小实现门）

### Step 5 · 评估 + 抽算子入库（反馈）

跑 `platform_submit_factor` → `platform_check_factor` → `assess`（复用全链路）。

**无论因子 pass/fail，都要回写算子库**（这是资产沉淀）：
1. **新算子** → 入 `operators` 表（主体：纯抽象定义 + input_roles + abstract_structure + direction_property）
2. **撞族边界** → 入 `operator_family_edges`（本次算子×基底 → 撞了哪个族 / 闭包外）
   - 撞族判定：`factor_ic_correlate` 最高 |pearson| ≥0.7 + `factor_residual_ic_strength` 残差 <0.5
   - 记 base_type / family / pearson / residual / tested_on / verdict
3. **应用实例** → `iteration_open/realize` 时带 `op_id`（iterations.op_id 记本次迭代用了哪个算子）

## 判定尺子（assess 时用）

- **IC 门槛**：ICIR≥0.3 + |rank_ic|≥0.01（过闸门才能谈闭包外）
- **闭包外**：滚动残差≥0.5 或 OOS 残差相关≥0.5，且最高 |pearson|<0.7
- **撞族**：最高 |pearson|≥0.7 → 该算子×该基底撞族，记边界
- 五级状态（`concept_assess.py`）：IMPLEMENTATION_NOVEL → REPRESENTATION_CANDIDATE → BEHAVIOR_OUTSIDE_CLOSURE → SIGNAL_OUTSIDE_CLOSURE → FULL_NON_TYPICAL_PASS

## 不要做的事

- **不要 Step 2 看算子库**（会生搬硬套：看到库就反向构造能套上的缺口）
- **不要把算子定义绑死因子**（"BreachRun 的吸收"不对，"对手吸收"才对——算子纯抽象）
- **不要撞了族就放弃算子**（撞族 = 这个算子×这个基底失效，换基底复用，算子本身没死）
- **不要只复用不发明**（算子库饱和后必须发明扩边界，AI 自己判断何时该发明）
- **不要凭空发明**（发明来源：强因子五问 / 失败教训 / 市场理论，三选一，有依据）
- **不要让缺口定义借算子库的词**（Step 2 的纯度决定 Step 3 匹配的真实性）
