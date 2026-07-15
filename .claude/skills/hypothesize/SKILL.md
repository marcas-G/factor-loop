---
name: hypothesize
description: 知识图驱动假设产生引擎。在分层知识图(AXIOM→DERIVED→HYPOTHESIS)上做结构化扩展(resolve_contradiction/generalize_from_refutation/fill_chain_gap/orthogonal_branch)产生必然假设,替代 hypothesis-generator 的统计扫描。触发:/hypothesize、或"图推理产假设"、或被 research-loop Step1 调用。
---

# Hypothesize — 知识图驱动假设产生

在分层知识图(AXIOM→DERIVED→HYPOTHESIS,EVIDENCE/REFUTATION)上做**结构化扩展**产生必然假设。新提案=图的结构化扩展,不是扫网格枚举。无穷来自推理链延伸。

## 输入

- 无参数(默认单轮:产 1 个过 reviewer 的 idea 即返回)。被 research-loop Step1 调用时也是单轮。

## ⚠️ 衔接硬规则(不能断流)

G1→G2→G3→G4→G5,每个 G 完成后**必须立即在同一回合**发起下一 G 的第一个 tool call。**禁止**输出"已选定操作""reasoner 已返回"等无 tool call 的纯文字回合——会结束当前回合导致流程暂停。

汇报中间状态时,文字与下一 tool call 放同一回合(文字在前,call 紧随)。

## G1 · 动态优先级选操作

调 `mcp__quant-mcp__graph_select_operation`——按图状态(角度饱和度 / 聚簇所在角度 / 操作历史 diversity)动态打分,返回推荐操作 + 分数 + 理由。

**替代旧的固定优先级表**(resolve>generalize>...>explore)——固定表让 generalize 总赢 explore,导致深度优先扎堆(卡在饱和角度反复深挖)。动态打分:角度 saturated 时 explore 升到 0.85 > generalize(聚簇在饱和角度 ×0.3)→ 换角度;连续多次深挖时 +diversity。

返回 `{recommended, score, scores, reason, saturated_angles, fresh_angles}`。按 `recommended` 操作取触发点 ref:

| 操作 | 取触发点 |
|---|---|
| resolve_contradiction | `graph_query_contradictions {resolved:false,limit:1}` → edge_id + axiom + evidence |
| generalize_from_refutation | `graph_find_refutation_clusters {min_size:3,limit:1}` → target + members |
| fill_chain_gap | `graph_get_subgraph {table:"ideas",node_id:<id>}` 定位断点 |
| orthogonal_branch | `graph_neighborhood {table:"ideas",node_id:<id>,edge_types:["INSTANTIATES"]}` |
| explore_uncovered_angle | 返回的 `fresh_angles` 里选 unexplored 优先,次 thin |

**→ 衔接**:选定操作+触发点后,立即同回合 Task 派 graph-reasoner-agent。

**fallback**:推荐 explore 但 `fresh_angles` 空(所有角度都 saturated)→ 调 `Skill hypothesis-generator`(旧 lens 多轮路径)。

## G2 · 派 graph-reasoner-agent 执行扩展操作

```
Task({
  subagent_type: "graph-reasoner-agent",
  prompt: "operation: <op>\ntrigger: <触发点 ref + axiom/evidence/cluster 概要>\n拉取完整输入后按你的操作框架(S1-S4+三道门槛)推理,返回 {new_nodes,new_edges,confidence,reasoning_summary}。"
})
```

→ 收返回 JSON。

**→ 衔接**:返回后,三分支:
- `new_nodes` 含 ideas 节点且 confidence≥0.3 → 立即 G3 派 reviewer。
- `new_edges` 含 BOUNDS 边且无 ideas 节点(`verdict_hint="bounded"`,axiom 证伪)→ 跳过 G3,直接进 G4 的 BOUNDS 落盘段。
- 真·空手(无 BOUNDS 无 ideas / 数据不足)→ 回 G1 选下一触发点(无下一触发点则 fallback)。

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

**触发点耗尽仍无 pass** → fallback:`Skill hypothesis-generator`。

## G5 · 返回

返回给调用方:
```
{idea_id, text, necessity_grade, argument_chain, operation_used: "<op>"}
```

被 research-loop Step1 调用时,这个返回进入 Step2(brainstorm 产 N 个因子实现验证该假设)。

## 关键不变量

- **单一真相源**:节点只写 ideas/axioms 表,边只写 graph_edges。不新建映射表。
- **reviewer 独立**:graph-reasoner 产,reviewer 独立对抗审,主会话据 verdict 落盘。三者职责分离。
- **可回退**:hypothesis-generator 永远在作 fallback,新旧产生器并存可对比。

## 不要做

- ❌ 直接写 ideas/graph_edges 而不经 graph_add_node/graph_add_edges(绕过幂等和 node_layer)。
- ❌ 跳过 reviewer 直接落盘 DERIVED(必然性必须经对抗审)。
- ❌ 把统计 IC 当产生器——IC 是 HYPOTHESIS 节点的裁判(assess 阶段),不是这里的产生器。
- ❌ 纯文字回合断流(见衔接硬规则)。
