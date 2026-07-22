---
name: brainstorm
description: 量化因子候选生成。触发 `/brainstorm [idea]` 或被 research-loop 嵌套调用。基于现有因子库和经验生成 N 个差异化候选因子，写 ideas/factors 表和 state。
---

# Brainstorm — 量化因子候选生成

基于现有因子库（factors/lessons）和经验，生成 `n_factors` 个差异化候选因子，并调 MCP 持久化 idea 和候选。所有数据检索走 `quant-mcp` 工具，不直接用 Bash 调 factor-cli.mjs。

## 输入

- `idea`（可选）：研究 idea 文本（30-80 字）。未提供则按 `source` 从对应 pool 抽 coords 翻译/构造一句。
- `source`（可选）：idea 来源，`inspiration`（默认，发散思维）或 `hypothesis`（收敛验证——读 `.claude/hypothesis-framework.md` 按三道门槛构造合规假设）。
- `n_factors`（可选）：候选数，默认 3。
- `run_id`（被 research-loop 嵌套调用时传入）：用于写 state.factors。

## 工作环境 — factors.db 结构

库分两层：

【实体层】
- `factors` 表（每因子一行，xname 唯一）：xname, class_name, formula_text, params, status, latest_ic, latest_icir, latest_sharpe, latest_rank_ic, created_ts
  - status 枚举：
    - `draft` — 已写未评估
    - `evaluated` — verdict=pass（正交新颖,通过判据,算子可借鉴演进；新>优:低 icir 弱信号只要不冗余也是 evaluated）
    - `dead_end` — verdict=fail（冗余/纯噪声,方向避雷）
    - `failed` — 评估彻底失败（通常平台问题）
- `factor_evals` 表（评估快照）：factor_xname, ts, ic_mean, icir, sharpe, rank_ic, eval_mode, raw_path
- `iterations` 表（迭代链 from→to）：from_xname, to_xname, change_note, outcome, icir_delta
- `ideas` 表：id, text, status

【经验层】
- `lessons` 表（原子经验）：type: `dead_end` / `success_pattern`

## 可用 MCP 工具（quant-mcp）

| 工具 | 用途 |
|---|---|
| `factor_counts {}` | 库规模摸底（factors / lessons / evaluated 三数）|
| `factor_list {k}` | 最近 k 个因子（含 status / latest_icir / formula_text）|
| `factor_recent_lessons {k}` | 最近 k 条 lesson |
| `factor_semantic_search {query_text, k}` | **语义检索（首选）**：给定 idea/formula 文本，向量查相似因子 |
| `factor_search {query, k}` | 全文检索 lessons（trigram，关键词 ≥3 字）—— 语义检索的补充，找历史教训文本 |
| `factor_detail {xname}` | 单因子全貌：基本信息 + 最近 10 条 evals + 迭代链 + tags |
| `factor_similar {xname, k}` | 给定 xname 找相似（要求因子已入库，brainstorm 一般用不上）|
| `iteration_list_open {top_k, source_status?}` | **检索待接续的迭代建议**（open suggestions，按 priority 降序）。库内 pass 精进 / dead_end 重试的未兑现建议。有相关的就接续成候选，演进链往下长 |
| `graph_angle_coverage {}` | **角度饱和度**(新>优核心):各信息角度的因子数/dead_end 数,标 unexplored/thin/partial/saturated。saturated=已挖透新候选大概率 IC 冗余;fresh=未探索更可能正交 |

## 全品种约束

候选因子 `categories` 必须含全部 feeds **[AG, CU, AU, AL, NI]**(白银/铜/黄金/铝/镍),全品种适用,不挑不缺。

## 研究流程

### 第 1 步 · 摸底（每项调一次）

- `factor_counts {}` — 看库规模
- `factor_recent_lessons {k:10}` — 最近经验
- `factor_list {k:20}` — 最近因子状态
- `graph_angle_coverage {}` — **角度饱和度**(新>优核心输入):saturated 角度(已挖透,新候选大概率 IC 冗余)vs fresh(unexplored/thin,更可能正交)。候选方向据此
- **冗余模式避雷**(D):从 recent_lessons 识别"冗余毙"的 dead_end(key_weaknesses 含"冗余"/"pearson"/"残差"),记"X 角度+Y 算子 → 已和 Z 因子 IC 冗余"模式——候选须避开(换算子/角度/信号源)

### 第 2 步 · 围绕 idea 检索

**首选语义检索**（向量，匹配 formula 语义）：

- `factor_semantic_search {query_text: <idea 全文或核心句>, k: 10}` — 拿最相似的 k 个因子
- 命中 `evaluated` 因子 → `factor_detail` 看演进路径，学成功经验
- 命中 `dead_end` 因子 → 在候选的 `db_research.found_dead_ends` 记下方向，候选差异化避开

**补充关键词检索**（FTS5，匹配 lessons 文本）：

- 用 1-2 个具体术语（如 `大单冲击` / `撤单偏度`）调 `factor_search`，捞语义检索漏掉的历史教训
- 只在语义检索结果不够覆盖 idea 时用，不要取代语义检索

**检索待接续的迭代建议**（接续演进链）：

- `iteration_list_open {top_k: 5}` — 拿 priority 最高的待接续建议（pass 精进优先、强因子优先）
- 若某建议的 from 因子与 idea 相关、或 priority 很高：**优先把它接续成本轮一个候选**（标 `iterates_from` + `suggestion_id`，在 `coord_usage` 说明接续与差异）。这让库内"已验证方向"演进下去，而不是每轮从零随机
- 这是"软注入"：不强制名额，但**接续高价值建议 > 凭空新造**

### 第 3 步 · 基于证据出候选

生成 `n_factors` 个差异化候选，每个候选在 `db_research` 字段显式回答：
- `searched`：用了哪些检索词
- `found_dead_ends`：命中的 dead_end lesson / dead_end 因子（如有，候选怎么避开）
- `found_similar`：命中的相似因子（如有，候选怎么差异）
- `borrowed_from`：借鉴了哪个 success_pattern / evaluated 因子的算子

## 候选硬要求

**🎯 新 > 优**:候选宁可预期指标低,也要在算子/角度上和 `found_similar` 实质差异——冗余在 assess/persist 硬卡(pearson≥0.6 / 残差<0.5),指标低(纯噪声<0.05 外)不否决。这里只做文本预筛,真正卡口在下游。

1. 公式/伪代码必须可回测（写得出 .h 实现）
2. `n_factors` 个候选必须差异化（算子/窗口/变换任一维度不同；品种**不作差异化维度**——每个候选都全品种适用）
3. `intuition` 具体到市场机制（如"套保资金在换月期的行为模式"），不泛泛"市场非有效"
4. `diff_check`：去掉关键 [维度] 后会退化成什么标准因子？本质差异在哪？
5. `coord_usage`：本因子如何用 idea 中的研究要素（数据/算子/时间/关系/变换/状态）
6. **接续优先**：若第 2 步检索到与 idea 相关的 open iteration 建议，至少 1 个候选应是接续候选（带 `iterates_from` + `suggestion_id`），并在 `coord_usage`/`diff_check` 里说明接续关系与差异点。没有相关 open 建议时，全部新造
7. **角度新颖**(A·新>优):候选倾向 fresh/unexplored 角度(从 idea 的 angle 出发往未饱和子方向发散);落 saturated 角度的候选,`diff_check` 必须附"正交论证"——和同角度已有因子预期 IC 行为不同的具体依据(不同算子/不同 horizon/不同信号源)
8. **冗余避雷**(D):候选须避开第1步捞到的"冗余模式"(X 角度+Y 算子→已和 Z 冗余),在 `db_research.found_redundancy` 记命中模式 + 说明本候选怎么避开(换算子/角度/信号源)

## 持久化（写完候选后必须做）

**只调一次** `persist_candidates`，把上面输出的候选 JSON 整体传入，工具内部完成存 idea + 完整候选 factors（自动补全 status 等 schema 字段，保留 intuition/db_research）：

```
persist_candidates {
  run_id,
  idea_text: <idea 文本>,
  factors: <上面"输出格式"的 factors 数组，原样整体传入>
}
```

不要逐候选 run_save（多次调用易在输出大 JSON 后停止 + 点路径覆盖丢 schema 字段）。`persist_candidates` 一次搞定，返回 `{idea_id, n_factors}`。

## 输出格式

严格 JSON，无其他文字：

```json
{
  "factors": [
    {
      "name": "类名(PascalCase)",
      "formula": "公式或伪代码",
      "intuition": "为什么有效 - 直觉假设（市场机制层面）",
      "diff_check": "去掉 [X 维度] 后会退化成什么标准因子？差异点是什么？",
      "coord_usage": "本因子如何使用 idea 中的研究要素（数据/算子/时间/关系/变换/状态）",
      "categories": ["AG","CU","AU","AL","NI"],  // 全品种适用,不挑不缺
      "tags": ["按算子/数据/变换给 3-5 个英文标签，从 formula+intuition 提炼，参考库内老因子风格(order_book/imbalance/cancel_flow/spoofing/exponential_decay/hhi/weighted_depth 等)"],
      "params": {},
      "iterates_from": "接续 open iteration 时填（来自 iteration_list_open 的 from_xname）；不接续则省略",
      "suggestion_id": "接续时填（来自 iteration_list_open 的 suggestion_id）；不接续则省略",
      "db_research": {
        "searched": ["检索词1", "检索词2"],
        "found_dead_ends": ["命中的 dead_end 教训或因子（如无写 [])"],
        "found_similar": ["命中的相似因子 xname（如无写 [])"],
        "found_redundancy": ["命中的冗余模式(X 角度+Y 算子→冗余 vs Z)(如无写 [])"],
        "borrowed_from": "借鉴的具体因子/经验（一句话）"
      }
    }
  ]
}
```

## 错误处理

- 任何 MCP 工具连续失败 3 次 → `run_save {run_id, patch: {status: "paused"}}` 然后停止，向用户报告失败原因
- 单个检索失败 → 跳过该检索词，继续其它
