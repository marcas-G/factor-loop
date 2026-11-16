# 01 · 现状清单（AS-IS）

## 真实执行主链

```text
auto-loops.sh                     负责 tmux 会话启动、监控和续传
  -> research-loop Skill          主会话分阶段编排（原路径以 Factor 为研究对象）
      -> factor selection         R1 / suggestions / dead_end / reseed
      -> factor_profile           construction_view 与 evidence_view 分离
      -> assumption analysis      认知子代理提出隐含假设
      -> concept compilation      自然语言的 held / collapsed 映射到可观测变量
      -> evidence investigation   程序探针、分层比较与 evidence_card
      -> adjudication            反驳 / 相容 / 不足 / 域外
      -> repair / operator        可复用算子合同或修复合同
      -> persist_candidates       idea + 因子候选写入 run state
      -> run-factor-agent         生成 .h -> submit -> check -> restest
      -> assess                   忠实度 + 经验评价 + 冗余审查
      -> persist                 保存 factor / lesson / lineage / iteration
core/mcp/server.py                quant-mcp 的统一工具边界
core/mcp/run_store.py             单 run 的 state.json 与原子写入
core/db/schema.sql                生产研究资产数据库
```

## 责任地图（代码中的事实）

| 位置 | 已存在的职责 | 不承担的职责 |
|---|---|---|
| `auto-loops.sh` | tmux 车道、STOP、resume、轮询 run state | 不负责判断科学证据 |
| `.agents/skills/research-loop` | 调用顺序、续传与子代理交接 | 不直接实现平台执行 |
| `.agents/skills/cog-protocol` & `.zcode/agents/cog` | 假设审查、证据解释、表示修复和算子发明 | 不应自己决定统计验收 |
| `core/cog/phenomenon_miner.py` | 从库中提取 A–D 四类观察异常，输出无解释现象 | 当前是扫描脚本，不是通用生产研究对象选择器 |
| `core/cog/investigation/contract.py` | 校验表示挑战的 Test Contract（控制、变化、H0–H3、预测、混杂） | 不包含 TreEvo 的父子假设关系 |
| `core/retrieval/r1_select_research_object.py` | 从既有 factors 库中选择下一只值得研究的 Factor | 无法天然从空因子库启动广义主题树 |
| `core/mcp/run_store.py` | 生成 run_id、`state.json` 点路径合并更新、单进程内 run 级锁 | 不强制检查所有字段/状态转移；锁不跨进程 |
| `core/stages` / `core/platform` | 因子提交、失败分诊、平台评价结果 | 不自动证明某个因果解释 |
| `core/db/schema.sql` | factors/ideas/iterations/lessons/operators/lineage 等事实记录 | `ideas.parent_idea_id` 不等于有类型且可审计的假设细化边 |

## 已存在、值得复用的基础设施

1. `phenomenon_miner.py` 已有观察优先原型：成功因子的局部裂缝、两因子行为冲突、跨 feed 异常、多尺度差异。仍需要数据覆盖、分组稳健性、选择偏差与时间顺序检查；不得把脚本输出直接当成立的现象。
2. `factor_profile.py` 的构造 / 表现视图分离，是避免“看完收益倒推隐含假设”的现成机制。
3. `evidence_investigate.py`、`investigation/contract.py` 和概念编译子代理，可为新实验设计提供部分能力，但当前协议围绕 Factor 表示挑战而不是任意上层机制假设。
4. `ideas`、`operators`、`lessons`、`factor_lineage_edges` 是有价值的下游资产，不应迁移为统一万能节点表。
5. `core/retrieval/multiple_testing.py` 已记录单 idea 下历史尝试和当前候选数，但不能当成覆盖整个适应性研究树/所有实验的完整多重检验登记。

## 明确不等价的结构

- **Factor Lineage**：两个因子实现之间的派生/修复关系，可为 DAG；测量对象是已存在 Factor。
- **Hypothesis Tree**：两个科学主张之间的解释性细化关系，当前没有独立的 typed-edge、refinement warrant、unknowns、证据状态与版本化契约。
- **Observation Link**：Phenomenon 作为问题切入证据，可能支持多个树节点；它不是父子层级边。
- **Experiment Link**：一个实验可以检验多个竞争假设，且同一个节点可能有多个实验。

**研究逻辑树 ≠ 因子血缘树 ≠ 因果图**。前两者代表不同类型的来源关系；第三者要求额外的识别与干预假设。

## 需纳入后续治理的问题（仅审查结果，本 PR 不修复）

- `auto-loops.sh` 的续传路径将 `before=resume`，却只在 `latest != before` 时读取完成状态；同一 run 完成可能被漏检。
- `auto-loops.sh` 把 `paused` 和 `done` 一起走正常完成标记，暂停原因无法正确阻止下一新 run。
- N>1 车道通过全局 `latest_run` 判断归属，源码注释也承认存在竞态。
- 默认 `claude --permission-mode bypassPermissions` 需要明确的隔离/权限/预算策略，不能把它当通用安全默认值。
- `run_store.py` 有单进程线程锁和 temp-rename，但缺少跨进程 lease、乐观版本检查和明确的 transition guard。
- 部分评估/研究文档是历史截面；新规范与运行时以代码检查和真实运行证据为准。
