---
name: research-loop
description: 量化因子研究循环编排器。触发：`/research-loop <run_id?>` 或"跑一轮研究"。完成 brainstorm → runFactor × N → assess 全流程。
---

# Research Loop — 量化因子研究循环编排器

执行一个完整的研究循环：基于现有因子库和经验，brainstorm 新候选 → 让 run-factor-agent 跑每个候选的 write/submit/check → 评估结果写库。所有搬砖操作走 `quant-mcp` MCP server 的工具，不直接用 Bash/Write 操作文件。

## 输入

- `run_id`（可选）：如提供，从该 run 断点续传；否则建新 run。

## ⚠️ 衔接硬规则（不能断流）

本 skill 有 4 个 Step。**每个 Step 完成后，必须立即在同一回合发起下一 Step 的第一个 tool call。**

| 边界 | 必须立即做的第一个 tool call |
|---|---|
| Step 0 → Step 1 | `Skill brainstorm`（或按 IDEA_SOURCE 选 inspiration/hypothesis-pool 抽 coords）|
| Step 1 → Step 2 | 在一个消息内并行发 3 个 `Task` (run-factor-agent) |
| Step 2 → Step 3 | 对第一个 `check_done` factor 调 `Skill assess` |
| Step 3 → Step 4 | `run_save {status: "done", finished_at: ...}` |

**禁止**：在任何 Step 边界输出"brainstorm 已完成"、"候选已生成"、"3 个因子跑完"等**无 tool call 的纯文字回合**——这会结束当前回合导致流程暂停，用户需要手动说"继续"才能恢复。

**如需对用户汇报中间状态**：把汇报文字与下一 Step 的第一个 tool call **放在同一回合**（文字在前，tool call 紧随其后），不允许"先说话回合 + 再行动回合"的两回合拆分。

**唯一例外**：检测到 `state.status == "paused"`（brainstorm 内部连续失败 3 次等情况），此时停止并向用户报告。

## Step 0 · 初始化

- 如未给 `run_id`：
  1. 调 MCP `run_init {}` → 拿到 `run_id`
  2. 调 MCP `run_save {run_id, patch: {parent_session: "<本会话描述，如 'claude-code-session-<date>'>"}}`
- 如给了 `run_id`：
  1. 调 MCP `run_load {run_id}` → 读 state
  2. 检查 `status`：如 `done` 报告"已完成"；如 `paused`/`running` 从断点续（看 `factors[].status` 决定从哪步开始）

**→ 衔接硬规则**：Step 0 完成（拿到 run_id 或读完 state）后，**必须立即在同一回合**进入 Step 1 的第一个 tool call（抽 coords / 调 Skill brainstorm）。禁止输出"已初始化，开始 brainstorm"之类的纯文字回合。

## Step 1 · 假设生成 + 因子候选（hypothesize → brainstorm）

1. **假设生成**（图驱动，替代坐标抽样）：调 Skill `hypothesize`，传 `{run_id}`。
   - hypothesize 内部自主：`graph_select_operation` 动态打分选操作 → 派 `graph-reasoner-agent` 在知识图上做结构化扩展（resolve_contradiction / generalize_from_refutation / fill_chain_gap / orthogonal_branch）→ 派 `reviewer-agent` 对抗审稿 → `graph_add_node` / `graph_add_edges` 落盘
   - 产出：1 个必然假设（necessary/identification）+ argument_chain + necessity_grade + idea_id + operation_used
   - 回主会话：`state.idea` / `state.idea_id`（带 argument_chain + grade）已落盘
   - **卡住处理（无 fallback）**：hypothesize 返回 `{no_hypothesis: true}`（全角度 saturated / 触发点耗尽）→ `run_save {status: "paused", paused_reason: "图推理耗尽，无新假设"}` + 向用户报告 + **停止**（衔接硬规则 paused 例外）
2. **因子候选**（基于假设产 N 实现验证，非坐标拼装）：调 Skill `brainstorm`，传 `{idea: state.idea, idea_id: state.idea_id, n_factors: 3, run_id}`。
   - brainstorm 基于 hypothesize 产的假设，产 N 个因子实现（同一假设的不同验证角度/实现方式——围绕 argument_chain 的核心机制构造）
   - brainstorm skill 内部：MCP 摸底 + 检索 → 生成候选（全品种 feeds）→ `persist_candidates` + run_save(factors)
3. 回主会话后，`state.idea` / `state.idea_id` / `state.factors` 已落盘

**连续失败处理**：brainstorm skill 内部 MCP 连续失败 3 次会自己 `run_save {status: "paused"}` 并停止；主会话检测到 `state.status == "paused"` 时中止后续 Step。

**→ 衔接硬规则**：brainstorm 返回 JSON 后，**必须立即在同一回合**于一个消息内并行发 3 个 `Task` (run-factor-agent) tool call。禁止输出"brainstorm 已完成，3 个候选已生成"之类的纯文字回合——这是本 skill 最易断流的位置，必须严守。

## Step 2 · 每个 factor 跑 runFactor（Task 子代理，并发 3）

把 factors 按每批 3 个分组。对每批：

1. 在**一个消息内**同时发 3 个 Task tool call（parallel tool use），每个：
   - `subagent_type: "run-factor-agent"`
   - `prompt`: 包含 `factor`（含 name/formula/intuition/categories/**tags**/params/hypothesis）+ `idea` + `run_id` + `factor_index`（该 factor 在 state.factors 数组里的下标，agent 用它做 `factors.<index>.xxx` 的 run_save）。**tags 从 state.factors[i].tags 取**（brainstorm 生成），写入 prompt 让 agent 生成 .h frontmatter 时带上
2. 等待 3 个全部返回，收集每个的 `{xname, failure_layer}`（轻量路由信息，agent.md 规定的 return contract）
3. agent 已在最终态自己调 `run_save` 落盘了完整字段（status / failure_layer / evidence / retry_trace / last_rewrite）——主会话**不再写这些**，避免靠 return message 传 state 时被 Claude 总结倾向截断
4. 兜底（**断流根治**）：对每个返回结果，调 `run_load {run_id}` 确认 `factors[i].status` 是终态且字段齐全。**如缺失（agent 停在 write-factor 返回处断流——头号 bug，见 memory `run-factor-agent-stalls`，衔接硬规则 model 会忽略）**：
   ① 先 `ls factors/<name>.h` 确认 .h 已生成；已生成则**重派**同 agent，prompt 明令**禁调任何 Skill（含 write-factor）**、从 `platform_submit_factor` 起步 A→E 跑完——此为已验证的可靠推进方式（硬规则无效，唯禁 Skill + submit 起步有效）。
   ② 重派仍卡 → 才 `run_save {patch: {"factors.<i>.status": "failed", "factors.<i>.failure_layer": "agent_crashed"}}` 兜底，继续其它 factor。
   ③ .h 未生成（write 步就断）→ 兜底 agent_crashed，后续单独调 write-factor 生成 .h 再重派。

5. **迭代回滚**：本批 3 个跑完 + 兜底确认后，扫一遍因子，对 `status==failed` 且 `suggestion_id` 非空的（接续候选 B 没跑成），调 `iteration_reopen {suggestion_id}` 把建议从 in_progress→open，允许下次再接续（不浪费这条精进/重试线索）。check_done 的不回滚（由 assess 的 realize 归档）。

下一批 3 个，直到所有 factor 跑完。

**→ 衔接硬规则**：所有 factor 跑完 + 兜底 `run_load` 确认后，**必须立即在同一回合**进入 Step 3：对第一个 `failure_layer == "check_done"` 的 factor 调 `Skill assess`（若没有 check_done 则直接进 Step 4）。禁止输出"3 个因子全部完成"之类的纯文字回合。

## Step 3 · assess（嵌套调 assess skill，串行）

筛选 `failure_layer == "check_done"` 的 factors（其它跳过）。

对每个 check_done factor（按 index 顺序串行）：

1. 调 Skill `assess`，传 `{run_id, factor_index: i}`
2. assess skill 内部完成：从 state 读 idea/hypothesis/evidence → 基于 7 维数据推理 verdict → persist_factor + run_save(verdict/persisted)
3. 回主会话后，`state.factors[i].verdict` / `state.factors[i].persisted` 已落盘，继续下一个

**→ 衔接硬规则**：最后一个 assess 返回后，**必须立即在同一回合**进入 Step 4：调 `run_save {status: "done", finished_at: <ISO>}`。禁止输出"所有因子评估完成"之类的纯文字回合。

## Step 4 · 汇总报告（support_score 连续，不绝对判断）

1. **汇总结论**——读假设支持度（连续分数，**不判成立/否决**——假设级保留不确定性）：
   - 调 `mcp__quant-mcp__hypothesis_get {idea_id: state.idea_id}` 读 `support_score`（贝叶斯平滑，0-1 连续）+ `evaluated_factor_count` + `necessity_grade`
   - support_score 是连续支持度（necessary 假设 pass 权重高 / identification 次之），不转绝对判断
   - 记 state: `run_save {run_id, patch: {"idea_support_score": <support_score>, "idea_evaluated_count": <count>, "idea_conclusion": "<一句话: 支持度=N, grade=X, N 因子 pass/fail 分布>"}}`
   - 报告：support_score + evaluated_factor_count + necessity_grade + pass/fail 分布 + key 教训（成功经验 / dead_end 方向）

   记 state:`run_save {run_id, patch: {"idea_verdict": "<hypothesis: 成立/否决/部分 | inspiration: 有效/无效/部分>", "idea_conclusion": "<一句话结论>"}}`

2. 调 MCP `run_save {run_id, patch: {status: "done", finished_at: "<ISO timestamp>"}}`
3. 向用户报告:
   - run_id
   - **结论**(`idea_verdict` + `idea_conclusion`:hypothesis 模式=假设成立/否决;inspiration 模式=探索有效/无效 + 教训/方向)
   - N 个因子,各 failure_layer 分布
   - check_done 因子的 verdict 分布(pass/fail 各几)
   - persisted 状态

## 错误处理

| 情况 | 行为 |
|---|---|
| MCP 工具连续失败 3 次 | `run_save {status: "paused"}`，向用户报告，停止 |
| Task 子代理超时/崩溃 | 标 `failure_layer: "agent_crashed"`，继续其它 factor |
| assess 失败（如 eval_metrics 缺失） | verdict=fail，key_weaknesses 写"eval_metrics 缺失"，继续下一个 |
| 断点续传时发现 factor `.h` 已存在但 status 非 done | 子代理先删除该 `.h` 文件再从 write 步重开 |

**status 枚举**：
- factor 级 `factors[i].status`：`pending`（初始，Step 1 写入时）→ `submitting`（run-factor-agent 完成 write 步后）→ `done`/`failed`（终态，Step 2 第 3 步落盘）
- run 级 `status`：`running`（run_init 后默认） / `paused`（断点暂停） / `done`（Step 4 完成）

## 不要做的事

- 不要直接用 Bash 调 `factor-cli.mjs`（已被废弃；用 MCP factor_* 工具）
- 不要直接用 Write/Edit 写因子 `.h` 文件（只有 write-factor skill 通过它的内部流程做）
- 不要用 SDK 风格的 `forkSession`（Claude Code 没有；每个 factor 的隔离靠 run-factor-agent 子代理）
- 不要在主会话里跑 write/submit/check（必须派给 run-factor-agent 子代理）
