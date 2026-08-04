---
name: concept-invent
description: 测量概念发明（通道B候选源）。触发 `/concept-invent <phenomenon_id?>` 或被 research-loop Step1 嵌套调用。现象卡 → 新测量问题 → 测量契约 → 候选因子。复用现有 persist_candidates → run-factor-agent → assess 全链路。
---

# Concept-Invent — 测量概念发明

基于现象分歧和闭包验证的非典型算子提案（通道B：算子发明，区别于通道A：算子演化）。

**核心方法论**：不沿已有算子变异，而是——发现当前测量语言无法区分的市场状态（现象卡）→ 提出新的测量问题 → 定义潜在量 → 用已有数学工具实现。新算子不是旧算子的远亲，而是此前没被问过、但能被数据回答的新问题。

## 输入

- `phenomenon_id`（可选）：从 `factor_db/concept_cards/cards/index.json` 取卡。未提供则先跑 `python3 factor_db/phenomenon_miner.py` 重新扫描生成卡。
- `registry_path`（可选）：问题注册表 `factor_db/concept_cards/question_registry.json`（批评器去重基准，未批注则跳过问题级去重）。
- `run_id`（被 research-loop 嵌套调用时传入）：用于写 state.factors。

## 工作环境

- 纯程序模块（factor_db/）：
  - `phenomenon_miner.py` — factor_ic_daily → 高置信检测（尺度失配/镜像不对称/regime翻转）
  - `phenomenon_cards.py` — 检测 → 方向中性现象卡（匿名 inventor_view / 溯源 memory_view）
  - `concept_critic.py` — 四检查（问题级去重/概念不可约/多实现/方向性质）→ `review()`
  - `question_registry.py` — 272 因子 → 问题族（批评器去重基准）
- 中间产物：`factor_db/concept_cards/`（detections.json / cards/ / question_registry.json）

## 流程

### Step 1 · 拿现象卡

- 给定了 `phenomenon_id`：读 `factor_db/concept_cards/cards/<id>.json` 的 `inventor_view`（匿名视图）。
- 未给定：跑 `Bash python3 factor_db/phenomenon_miner.py` 重新扫描 → 读 `detections.json` → 从 `cards/` 挑一张未用过的卡（查 lessons 里 `seed_phenomenon` 避免重复）。

### Step 2 · 概念发明器（LLM，主 agent 亲自做，不派子代理）

用以下提示词（只给 LLM 卡 + 数据能力 + 注册表摘要，不给因子名/机制词）：

```text
你是盘口测量概念发明器。目标：提出当前算子语言中不存在的测量问题。

输入：
1. 现象卡（匿名，不含因子名/机制词/买卖方向词）
2. 数据能力声明（可观测/不可观测）
3. 问题注册表（已问过的问题——你的问题必须在其之外）

规则：
- 禁止输出公式，禁止修改已有算子，禁止引用已有算子名
- 概念必须方向中性（INVARIANT / EQUIVARIANT / PAIRED）
- 概念必须能解释现象卡中的不可区分性/分歧
- 概念必须允许多个数值实现（≥2，不是单公式命名）
- 不预设答案（不要说"需要容量归一化"等已有变换）

现象卡：
{card.inventor_view}

数据能力声明：
{"frequency":"500ms_snapshot","feeds":["AG_MAIN","AG_NEXT","CU_MAIN","CU_NEXT"],
 "observable":["bid_ask_prices","multi_level_depth","midprice","spread",
   "snapshot_differences","directional_flow_proxies","daily_ic_vectors"],
 "unobservable":["individual_order_identity","exact_add_cancel_trade_sequence",
   "queue_position","true_order_event_time","real_intervention"]}

问题注册表摘要（问题族）：{registry 摘要}

输出 JSON 数组（最多 3 个候选）：
[
  {
    "measurement_question": "…",       # 动词开头的测量问题
    "latent_construct": "…",           # 潜在量命名
    "why_needed": "…",                 # 该概念为何解释卡中现象
    "direction_property": "INVARIANT|EQUIVARIANT|PAIRED",
    "expected_distinction": "…",       # 期望区分卡中哪两类
    "falsification": ["…"],            # 若成立应观察到什么，否则拒绝
    "candidate_implementations": ["…", "…"]  # ≥2 种估计思路（描述，非公式）
  }
]
只输出 JSON，不要其他文字。
```

### Step 3 · 程序化批评（concept_critic.py）

对每个候选调 `python3 factor_db/concept_critic.py --candidate <json>` 或主 agent 内嵌调用 `concept_critic.review(candidate)`：

- **问题级去重**：measured_object 是否已被注册表族占用
- **概念不可约**：latent_construct 是否命中旧概念词（imbalance/order_flow/depth/cancel/spread/impact/recovery/...）
- **多实现**：candidate_implementations ≥ 2 且实质不同
- **方向性质**：direction_property 合法且描述一致

`decision == "ACCEPT"` 的候选进入下一步；REJECT 的丢弃（不重试改参数——那是演化不是发明）。

### Step 4 · 编译成候选因子（对齐 brainstorm 格式）

每个 ACCEPT 候选编译成 factor 对象（persist_candidates 格式）：

- `name`：PascalCase 类名，由 latent_construct + 实现序号组成（如 `StateMaintenanceBurdenA`）；swap 变体加 `_sw` 后缀（方向行为验证用，同 run 提交）
- `formula`：用 500ms 快照可观测数据（bid/ask 深度、midprice、spread、成交流代理）写出计算描述——事件时间/订单级依赖禁止
- `intuition`：测量问题 + 为何解释现象卡
- `hypothesis`：**可证伪声明**（"若 <概念> 成立应观察到 X；若观察到 Y 则拒绝"——assess 忠实度用它）
- `tags`：从 latent_construct + direction_property 派生
- `params`：1 组固定参数，禁止窗口/阈值/档位自动遍历（最小实现门）
- `categories`：["AG"]

约束（最小实现门）：每卡最多 2 个候选 × 每个实现 1 个主版本 + 1 个 swap 变体。不做参数扫描。

### Step 5 · persist_candidates

调 MCP `persist_candidates {run_id, idea_text: "概念发明: <现象卡ID> → <latent_construct>", factors: [编译好的候选]}`。

**→ 衔接硬规则**：persist_candidates 返回后，必须立即在同一回合进入 research-loop Step 2（并行发 run-factor-agent）——概念发明是 research-loop Step1 通道B，候选与变换引擎候选合并后走同一流水线。

## 评估（交 assess skill，附加概念级验收）

候选因子跑完 check_done 后，走 `assess` skill（忠实度 + 闸门 + 冗余度）。概念发明的附加验收（四闭包→五级状态）用 `factor_db/concept_assess.py`：

- 问题闭包：问题是否已在注册表（发明时已查，复核）
- 结构闭包：实现是否只是现有变换词组合
- IC行为闭包：滚动 OOS 残差 ≥0.5 或 OOS 残差相关 ≥0.5 且最高 pearson <0.7
- 方向行为闭包：swap 变体 IC 与主实现关系是否符合 direction_property

五级状态：`IMPLEMENTATION_NOVEL → REPRESENTATION_CANDIDATE → BEHAVIOR_OUTSIDE_CLOSURE → SIGNAL_OUTSIDE_CLOSURE → FULL_NON_TYPICAL_PASS`
（信号闭包当前数据源不可得，最高状态 = BEHAVIOR_OUTSIDE_CLOSURE + SIGNAL PENDING）

## 不要做的事

- 不要让 LLM 直接生成公式（先有测量问题，再有实现）
- 不要沿已有算子变异（改窗口/换字段/加门控 = 通道A，不是本 skill）
- 不要用买卖方向词定义概念（方向中性是硬约束）
- 不要给概念发明器看因子名/公式（会锚定旧概念）
- 不要在现象卡里预设答案（"需要容量归一化"之类是污染）
