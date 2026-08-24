---
name: research-loop
description: 量化因子研究循环编排器。触发：`/research-loop <run_id?>` 或"跑一轮研究"。完成 cog-protocol(发现缺口+发明算子) → runFactor × N → assess 全流程。
---

# Research Loop — 量化因子研究循环编排器

执行一个完整的研究循环：**认知协议发现缺口/发明算子(起点)** → write-factor 实现候选 → run-factor-agent 跑 write/submit/check → assess 评估写库。所有搬砖操作走 `quant-mcp` MCP server 的工具，不直接用 Bash/Write 操作文件。

## 输入

- `run_id`（可选）：如提供，从该 run 断点续传；否则建新 run。

## ⚠️ 衔接硬规则（不能断流）

本 skill 有 5 个 Step。**每个 Step 完成后，必须立即在同一回合发起下一 Step 的第一个 tool call。**

| 边界 | 必须立即做的第一个 tool call |
|---|---|
| Step 0 → Step 1 | `Skill cog-protocol`（认知协议: 发现缺口+发明算子 → operator contract）|
| Step 1 → Step 2 | 把 contract 交给 write-factor → 产候选 factor |
| Step 2 → Step 3 | 写 `.tmp/agent_task.json` 后串行派 1 个 `run-factor-agent` |
| Step 3 → Step 4 | 对第一个 `check_done` factor 调 `Skill assess` |
| Step 4 → Step 5 | `run_save {status: "done"}`(算子注册已在 Step 1 认知协议 4 Gate 过时完成) |

**禁止**：在任何 Step 边界输出"认知协议已完成"、"候选已生成"、"3 个因子跑完"等**无 tool call 的纯文字回合**——这会结束当前回合导致流程暂停，用户需要手动说"继续"才能恢复。

**如需对用户汇报中间状态**：把汇报文字与下一 Step 的第一个 tool call **放在同一回合**（文字在前，tool call 紧随其后），不允许"先说话回合 + 再行动回合"的两回合拆分。

**唯一例外**：检测到 `state.status == "paused"`（认知协议连续无产出 3 次等情况），此时停止并向用户报告。

## Step 0 · 初始化

- 如未给 `run_id`：
  1. 调 MCP `run_init {}` → 拿到 `run_id`
  2. 调 MCP `run_save {run_id, patch: {parent_session: "<本会话描述，如 'claude-code-session-<date>'>"}}`
- 如给了 `run_id`：
  1. 调 MCP `run_load {run_id}` → 读 state
  2. 检查 `status`：如 `done` 报告"已完成"；如 `paused`/`running` 从断点续（看 `factors[].status` 决定从哪步开始）
- 定向接力：若 state 有 `next_research_object`，本轮 Research Object **直接用该 xname**，跳过随机/R1 选择；进入 Step 1 后调 `run_save {patch: {next_research_object: null}}` 清掉定向标记。

**→ 衔接硬规则**：Step 0 完成（拿到 run_id 或读完 state）后，**必须立即在同一回合**进入 Step 1 的第一个 tool call（若饱和则调 Skill reseed，否则调 Skill cog-protocol）。禁止输出"已初始化"之类的纯文字回合。

## Step 1 · 认知协议（发现缺口 + 发明算子, 循环起点）

**循环逻辑**: 对每个 Research Object 跑认知协议, 三种产出各走不同路径:

```
选 Research Object(dead_end/故事节点/现象)
  → 调 factor_saturation_status
     ├─ saturated (branch max_depth > 5)
     │    → Skill reseed → 产出单个 Measurement Seed
     │    → Step 2(seed_spec → write-factor)
     └─ not saturated
          → Skill cog-protocol
    → 产出什么?

      ① NEW OPERATOR + contract (S2.6 判 STRUCTURE + S3 4 Gate 全过)
        → 立即 register_operator(operators 表 source='cog', 不受 ICIR 影响)
        → Step 2(contract → write-factor)

      ② FACTOR_ITERATION 方向 (S2.6 判 STANDARD, 有明确修复路径)
        → 这是有产出的! 不是"换因子"
        → 主会话按修复路径直接写因子(formula/intuition/tags/params)
        → Step 2(和 ① 走同一个 write-factor, 只是输入来源不同)

      ③ INSUFFICIENT / CONSISTENT / OOD (evidence 不支持假设)
        → 换下一个 Research Object, 重跑认知协议
        → 直到产出 ① 或 ②, 或 Research Object 耗尽(本轮 done)
```

**深度判定是硬门槛**: 每个 Research Object 在进 cog-protocol 前必须调
`mcp__quant-mcp__factor_saturation_status {xname}`。`saturated == true` 时走 reseed,
不允许继续原认知协议深挖; `saturated == false` 才走 cog-protocol。

调 `Skill reseed <xname?>` 或 `Skill cog-protocol <xname?>`:
- **① NEW OPERATOR + contract**: 4 Gate 过 → 立即 register_operator → Step 2
- **② FACTOR_ITERATION**: minimal-repair 产出 **repair_contract**(结构化: preserved_signals/new_signals/forbidden_drops/gating_logic/output_composition)→ 主会话把它原样传给 write-factor → Step 2
- **③ RESEED SEED**: reseed 产出 **seed_spec**(measurement_object/operation/distinction/observability/independence)→ 主会话把它传给 write-factor → Step 2
- **④ 无产出**: 换 Research Object 重跑

**关键: FACTOR_ITERATION 不是终点, 是 Step 2 的另一个入口。且 repair_contract 是结构化 spec, write-factor 只能翻译不能自由发挥(防"推理天衣无缝、代码垃圾")。**

## Step 2 · 候选 factor(write-factor)

三个入口汇聚到此:

**入口 A (Step 1 ① NEW OPERATOR)**: 认知协议产出 operator contract → 主会话翻译成 formula/intuition/tags/params → write-factor 生成 .h

**入口 B (Step 1 ② FACTOR_ITERATION)**: minimal-repair 产出 repair_contract → 主会话把 repair_contract **原样**传给 write-factor 作为 spec → write-factor 严格按 preserved_signals/new_signals/forbidden_drops/gating_logic/output_composition 翻译成 .h

**入口 C (Step 1 ③ RESEED SEED)**: reseed 产出 seed_spec → 主会话把 seed_spec 传给 write-factor，按 measurement_object + operation 实现最小直接公式，禁止复杂化。

两个入口都产出候选 factor 对象(name/formula/intuition/tags/params/categories)。

**⚠️ 入口 B 的忠实度要求**: repair_contract 的 `preserved_signals`(必须保留的信号)和 `forbidden_drops`(禁止丢弃的信号)是硬约束——write-factor 写 .h 时, 每个 preserved_signal 和 forbidden_drop 都必须出现在代码里。主会话在写完后核对: 代码里有没有丢了 forbidden_drops 里的信号? 丢了 → 重写。

**⚠️ categories 语义(易错, P0)**:`categories` = **品种代码数组** `["AG"]` / `["AG","CU"]`,合法值仅 `AG/AU/CU/AL/NI`(沪金银铜铝镍)。**不是 tags**、**不是 xname**。空数组 `[]` = 用默认品种(SHFE-AG,SHFE-CU)。填错会被 `platform_submit_factor` 拦截返回 `config_error`(防拼出畸形 feeds 导致 DAG failed)。
- 若 contract 直接给了实现(如算子实现), 按基底换绑定产因子候选

候选数组后:

1. **persist_candidates**: 调 MCP `persist_candidates {run_id, idea_text: "<cog: Research Object X → operator Y + 基底 Z>", factors: [候选]}` 存 state。
2. 回主会话后, `state.factors` 已落盘(候选, 含 formula/intuition/tags/params/hypothesis)。

**→ 衔接硬规则**：persist_candidates 返回后, **必须立即进入第一个 factor 的任务文件交接**（Codex 环境）或 `Task` 派发（Claude Code 环境）。禁止输出"候选已生成"之类的纯文字回合——这是本 skill 最易断流的位置, 必须严守。

## Step 3 · 每个 factor 跑 runFactor（Task 子代理，串行）

对 factors 按 index 逐个执行（Codex 环境禁止并发派发，避免多个子代理抢占同一任务文件）：

1. 先把完整派发 JSON 写入 `.tmp/agent_task.json`：
   ```json
   {
     "task": "按 run-factor-agent.md 状态机执行单个 factor，终态落盘后返回轻量路由信息",
     "input": {
       "factor": {"name": "...", "formula": "...", "intuition": "...", "categories": ["AG"], "tags": ["..."], "params": {}, "hypothesis": "..."},
       "idea": "<state.idea>",
       "run_id": "<run_id>",
       "factor_index": <i>
     },
     "expect": {"xname": "<name>", "failure_layer": "check_done | ..."}
   }
   ```
   `factor` 必须含 name/formula/intuition/categories/**tags**/params/hypothesis；**tags 从 state.factors[i].tags 取**，供 .h frontmatter 使用。
2. `spawn_agent(task_name="run_factor_<i>", fork_turns="none", message="读取 .tmp/agent_task.json 并执行")`。等待终态，收集 `{xname, failure_layer}`；随后删除 `.tmp/agent_task.json`，再进入下一个 factor。
3. agent 已在最终态自己调 `run_save` 落盘了完整字段（status / failure_layer / evidence / retry_trace / last_rewrite）——主会话**不再写这些**，避免靠 return message 传 state 时被 Claude 总结倾向截断
4. 兜底（**断流根治**）：对每个返回结果，调 `run_load {run_id}` 确认 `factors[i].status` 是终态且字段齐全。**如缺失（agent 停在 write-factor 返回处断流——头号 bug，见 memory `run-factor-agent-stalls`，衔接硬规则 model 会忽略）**：
   ① 先 `ls factors/<name>.h` 确认 .h 已生成；已生成则**重派**同 agent，prompt 明令**禁调任何 Skill（含 write-factor）**、从 `platform_submit_factor` 起步 A→E 跑完——此为已验证的可靠推进方式（硬规则无效，唯禁 Skill + submit 起步有效）。
   ② 重派仍卡 → 才 `run_save {patch: {"factors.<i>.status": "failed", "factors.<i>.failure_layer": "agent_crashed"}}` 兜底，继续其它 factor。
   ③ .h 未生成（write 步就断）→ 兜底 agent_crashed，后续单独调 write-factor 生成 .h 再重派。

5. **迭代回滚**：所有 factor 跑完 + 兜底确认后，扫一遍因子，对 `status==failed` 且 `suggestion_id` 非空的（接续候选 B 没跑成），调 `iteration_reopen {suggestion_id}` 把建议从 in_progress→open，允许下次再接续（不浪费这条精进/重试线索）。check_done 的不回滚（由 assess 的 realize 归档）。

**→ 衔接硬规则**：所有 factor 跑完 + 兜底 `run_load` 确认后，**必须立即在同一回合**进入 Step 4：对第一个 `failure_layer == "check_done"` 的 factor 调 `Skill assess`（若没有 check_done 则直接进 Step 5）。禁止输出"3 个因子全部完成"之类的纯文字回合。

## Step 4 · assess（嵌套调 assess skill，串行）

筛选 `failure_layer == "check_done"` 的 factors（其它跳过）。

对每个 check_done factor（按 index 顺序串行）：

1. 调 Skill `assess`，传 `{run_id, factor_index: i}`
2. assess skill 内部完成：从 state 读 idea/hypothesis/evidence → 基于 7 维数据推理 verdict → persist_factor + run_save(verdict/persisted)
3. 回主会话后，`state.factors[i].verdict` / `state.factors[i].persisted` 已落盘，继续下一个

**→ 衔接硬规则**：最后一个 assess 返回后，**必须立即在同一回合**进入 Step 5：调 `run_save {status: "done"}`。禁止输出"所有因子评估完成"之类的纯文字回合。

## Step 5 · 收尾（算子注册已在 Step 1 完成）

**算子注册不在此步**——认知协议 S3 产出 operator contract（语义 4 Gate 过）时**立即注册** operators 表（source='cog'）。算子=资产（语义层可复用测量方法），先沉淀；因子=产品（实证验证），assess 管 ICIR 判定和因子入库。**算子注册不受 ICIR 影响**——ICIR 不达标不否定算子（可能是算子实现/基底选错），只否定该次因子实现。

**再播种定向接力**：若本轮有 factor 来自 reseed（`state.factors[i].tags` 含 `reseed` 或 `state.factors[i].reseed_from` 非空），在该因子 persist 后调：

```text
run_save {run_id, patch: {next_research_object: "<seed factor xname>"}}
```

下一轮 Step 0 直接用它做 Research Object，不随机/R1 选择。

## Step 6 · 汇总报告（support_score 连续，不绝对判断）

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
- **❌ 绝对禁止 kill MCP server 进程**(quant-mcp 是 stdio server,Claude Code 管理其生命周期)。stdio server 被 kill 后不会自动重连——kill 会导致 quant-mcp 工具全部不可用,主会话陷入死循环误调其他工具。如需重连:让用户 `/mcp` reconnect 或 `/exit` 重开 session。
- **❌ 禁止 kill 自己依赖的任何 MCP server 进程**。改了 MCP server 源码后,代码在下次 session 重启时自然生效,不要主动 kill。
