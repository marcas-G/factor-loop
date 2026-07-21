---
name: hypothesize
description: 知识图驱动假设产生引擎。在分层知识图(AXIOM→DERIVED→HYPOTHESIS)上做结构化扩展(resolve_contradiction/generalize_from_refutation/fill_chain_gap/orthogonal_branch)产生必然假设。触发:/hypothesize、或"图推理产假设"、或被 research-loop Step1 调用。
---

# Hypothesize — 知识图驱动假设产生

在分层知识图(AXIOM→DERIVED→HYPOTHESIS,EVIDENCE/REFUTATION)上做**结构化扩展**产生必然假设。新提案=图的结构化扩展,不是扫网格枚举。无穷来自推理链延伸。

## 输入

- 无参数(默认单轮:产 1 个过 reviewer 的 idea 即返回)。被 research-loop Step1 调用时也是单轮。

## ⚠️ 衔接硬规则(不能断流)

G1→G2→G3→G4→G5,每个 G 完成后**必须立即在同一回合**发起下一 G 的第一个 tool call。**禁止**输出"已选定操作""reasoner 已返回"等无 tool call 的纯文字回合——会结束当前回合导致流程暂停。

汇报中间状态时,文字与下一 tool call 放同一回合(文字在前,call 紧随)。

## G1 · 数据驱动选操作(3 操作)

调 `mcp__quant-mcp__graph_select_operation`——从图状态连续计算分数(trigger × diversity),无魔数 if-else。返回 3 操作的打分:

```
generalize(归纳): trigger = max聚簇大小/10,从反例/成功/混合聚簇归纳
fill(维护):       trigger = 空节数/5,补已有论证链客观空节
explore(拓展):    trigger = fresh比例×饱和比例,往未探索角度产种子
```

**操作层只这 3 个**(方法论层由 graph-reasoner 自选——反例归纳/成功归纳/正交展开/对比归纳)。

返回 `{recommended, scores, trigger, max_cluster, n_gaps, fresh_angles, saturated_angles}`。按 `recommended` 取触发点:

| 操作 | 取触发点 |
|---|---|
| **generalize** | `graph_find_refutation_clusters {min_size:3,limit:1}` → target + members;若有 pass 实现则也查 SUPPORTS 聚簇 |
| **fill** | 查 background_axioms 引用不存在 axiom 的 DERIVED idea,`graph_get_subgraph` 定位断点 |
| **explore** | `fresh_angles` 里选 unexplored 优先,次 thin |
| **angle_discovery** | explore 卡(`fresh_angles` 空)时:`saturated_angles` 选最饱和的(dead_end 最多),走特殊分支(见末尾"angle_discovery 分支")——元归纳新角度突破预定义语言 |

**→ 衔接**:选定操作+触发点后,立即同回合 Task 派 graph-reasoner-agent,prompt 里标注 operation(归纳/维护/拓展)+ 触发点概要。graph-reasoner 自选方法论(看触发点是全 dead_end/有 pass/混合)。

**卡住处理**:推荐 explore 但 `fresh_angles` 空 → **不再直接 no_hypothesis,转 `angle_discovery`**(从 saturated_angles 元归纳新角度,见末尾"angle_discovery 分支")。只有 angle_discovery 也产不出(reviewer reject / 无新维度)→ G5 返回 `{no_hypothesis: true}`。

## G2 · 派 graph-reasoner-agent 执行操作

```
Task({
  subagent_type: "graph-reasoner-agent",
  prompt: "operation: <generalize|fill|explore>\ntrigger: <触发点 ref + 概要>\n按操作框架推理,generalize 时根据触发点性质自选方法论(全dead_end→反例归纳/有pass→成功归纳或正交展开/混合→对比归纳)。返回 {new_nodes,new_edges,methodology,confidence,reasoning_summary}。"
})
```

→ 收返回 JSON。

**→ 衔接**:返回后:
- `new_nodes` 含 ideas 节点且 confidence≥0.3 → 立即 G3 派 reviewer。
- 真·空手(无 ideas / 数据不足)→ 回 G1 选下一触发点(无下一触发点则卡住处理)。

## G3 · 派 reviewer-agent 对抗审稿(模式一·假设审稿)

对 new_nodes 里的每个 ideas 节点:

```
Task({
  subagent_type: "reviewer-agent",
  prompt: "模式一·假设审稿。论证链:\n" + JSON.stringify({text: <node.text>, argument_chain: <node.argument_chain>})
})
```

→ 收 verdict:`{verdict, s2_superadditive, s4_uniqueness, achievable, necessity_grade, defects, degrade_suggestion}`

**→ 衔接**:verdict 返回后立即 G4。

## G4 · 落盘 + fail 分诊

**verdict = pass**(s2 且 s4 都 pass):
1. `mcp__quant-mcp__graph_add_node {table:"ideas", data:{text, argument_chain, necessity_grade:<reviewer 判的 grade>, node_layer:<reasoner 建议的 DERIVED|HYPOTHESIS>}}` → 拿 `idea_id`
2. 把 new_edges 里所有 `<NEW>` 替换为 `idea_id`
3. `mcp__quant-mcp__graph_add_edges {edges: <替换后的 new_edges>}`
4. 若操作=resolve_contradiction:`mcp__quant-mcp__graph_mark_contradiction_resolved {edge_id:<触发边id>, idea_id}`
5. 若操作=fill_chain_gap 且有 patch_to:把补的 axiom/中间节点 graph_add_node 后,更新原 idea 的 argument_chain(persist_argument_chain 或直接说明由主会话回填)
→ G5

**BOUNDS 落盘**(graph-reasoner 返 `verdict_hint="bounded"`,axiom 证伪,跳过 G3):
1. `mcp__quant-mcp__graph_add_edges {edges: <new_edges 里的 BOUNDS 边>}`
2. `mcp__quant-mcp__graph_mark_contradiction_bounded {edge_id:<触发边id>, regime:<BOUNDS 边 properties.regime>, reason:<properties.reason>}`
3. → G5(返回 operation_used="resolve_contradiction(bounded)",无 idea_id——本轮是边界限定,非新假设)

**verdict = fail**,按 `achievable` 分诊:
- `fixable`(论证不足 / C 过宽):回 G2,prompt 带上 reviewer 的 defects 反馈,补论证重试。**最多 2 次**。
- `degrade_suggested`(type 天然不可达):按 degrade_suggestion 降 necessity_grade,回 G3 重审 1 次。
- `unreachable`(无超加性硬核 / Σ 错):该触发点放弃,回 G1 选下一触发点。

**触发点耗尽仍无 pass** → G5 返回 `{no_hypothesis: true, reason: "触发点耗尽"}`(无 fallback,如实返回)。

## G5 · 返回

**正常**(产了假设):
```
{idea_id, text, necessity_grade, argument_chain, operation_used: "<op>"}
```
→ research-loop Step1 进入 Step2(brainstorm 产 N 因子实现验证)。

**卡住**(无 fallback,如实返回):
```
{no_hypothesis: true, reason: "全角度 saturated / 触发点耗尽,图推理产不出新假设"}
```
→ research-loop Step1 收到后 paused(图推理耗尽,不硬凑假设)。

## angle_discovery 分支(突破语言边界,explore 卡时触发)

当 G1 `recommended=angle_discovery`(explore 卡 nFresh=0 + 饱和多)时,**不走 graph-reasoner,走元层**——从 dead_end 聚簇元归纳预定义 12 角度外的新信息角度。这是系统从"组合引擎"升级到"发现引擎"的关键:自己扩展语言边界。

### G2-angle · 派 meta-angle-discoverer-agent(非 graph-reasoner)

```
Task({
  subagent_type: "meta-angle-discoverer-agent",
  prompt: "angle_discovery: 触发角度=<saturated_angles[0]>(最饱和,dead_end 最多)。
    用 graph_angle_coverage 读全 12 角度清单,factor_list/factor_detail 取该角度 dead_end 聚簇(formula/tags/failure_reasons),
    factor_search 捞 dead_end lesson。元归纳这些失败共享的、未被 12 角度捕获的新信息维度。
    返回 {code,name,field_family,extraction,signal_target,theory_axiom,description,novelty_argument}。
    硬约束:code 非现有 12;field_family 落 BookSnapshotInfo 实有族;novelty_argument 说清和最近邻现有角度区别。"
})
```

→ 收候选角度 JSON。

**衔接**:返回后立即 G3 派 reviewer 模式三审。真·空手(无候选/数据不足)→ G5 返回 `{no_hypothesis: true, reason: "angle_discovery 产不出新维度"}`。

### G3-angle · 派 reviewer-agent 模式三(angle 审)

```
Task({
  subagent_type: "reviewer-agent",
  prompt: "模式三·angle 审。候选角度:\n" + JSON.stringify(<候选角度>) + "\n现有 12 角度清单:\n" + JSON.stringify(<angle_coverage>)
})
```

→ 收 `{verdict: accept/reject, nearest_existing_angle, novelty, field_groundable, reason}`。

**衔接**:verdict 返回后立即 G4。

### G4-angle · accept 落库 / reject 回 G1

- **accept**(真新维度):`mcp__quant-mcp__addAngle`(经 MCP;若工具层无,用 persist 或直接 lib)写 angle_ontology(code/name/field_family/extraction/signal_target/theory_axiom/description)。新角度入库后 `query_angle_coverage` 自动算它 unexplored(0 因子)→ explore 下轮能选它产种子。
- **reject**(换皮/无支撑/不落地):回 G1 选下个 saturated 角度重试(最多试 2-3 个 saturated 角度),全 reject → G5 `{no_hypothesis: true}`。

### G5-angle · 返回

```
{angle_discovery: true, angle_code: <新角度 code>, name: ..., field_family: ...,
 operation_used: "angle_discovery", reviewer_novelty: "true_new"}
```

→ research-loop Step1 收到后,本 run 的 explore 有了新角度土壤(下轮 explore 可选它)。

## 关键不变量

- **单一真相源**:节点只写 ideas/axioms 表,边只写 graph_edges。不新建映射表。
- **reviewer 独立**:graph-reasoner 产,reviewer 独立对抗审,主会话据 verdict 落盘。三者职责分离。
- **无 fallback**:图推理耗尽(全饱和/触发点尽)如实返回 `no_hypothesis`,不硬凑假设;research-loop 据 paused。

## 不要做

- ❌ 直接写 ideas/graph_edges 而不经 graph_add_node/graph_add_edges(绕过幂等和 node_layer)。
- ❌ 跳过 reviewer 直接落盘 DERIVED(必然性必须经对抗审)。
- ❌ 把统计 IC 当产生器——IC 是 HYPOTHESIS 节点的裁判(assess 阶段),不是这里的产生器。
- ❌ 纯文字回合断流(见衔接硬规则)。
