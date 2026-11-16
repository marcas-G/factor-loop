# 06 · TreEvo 可运行最小树原型（P2-a）

状态：**独立可运行原型**（非现有 \`research-loop\` 的执行入口）。

代码：\`core/tre_evo/\`。此模块只操作单独的 SQLite 文件，**不修改 \`data/factors.db\`、\`core/db/schema.sql\`、\`auto-loops.sh\`、\`research-loop\` 或 \`assess\`**。其中的树存储模块不直接驱动 LLM：原始 CLI 由模型或人工提供节点/细化边后进行确定性验证；**另外新增的模型候选生成与人工审核层见 [07-refinement-agent.md](07-refinement-agent.md)**。它仍未连接现有因子执行。

## 依赖和隔离

Python 3.11+；\`pip install "jsonschema>=4,<5"\`。只有执行 \`mine-candidates\` 时才需要 \`numpy\`（因原有 \`core/cog/phenomenon_miner.py\` 使用它）。数据库由 \`TREEVO_DB_PATH\` 或命令行 \`--db\` 指定，默认 \`~/.quant-tre-evo/trees.sqlite3\`，使用 SQLite WAL 与事务版本检查。

先下载仓库，在项目根目录执行：

\`\`\`bash
python3 -m pip install "jsonschema>=4,<5"
DB="$(mktemp -d)/tre-evo.sqlite3"
EX=docs/standardization/examples

# 1. 建立纯理论主题；此时不要求已有 factor
python3 -m core.tre_evo.cli --db "$DB" create-root --node "$EX/hypothesis-root.json"

# 2. 登记完整、带出处的观察示例（仅教学，非实测）
python3 -m core.tre_evo.cli --db "$DB" record-phenomenon --record "$EX/phenomenon.json"

# 3. 明确父子逻辑与细化理由；要求预期树版本（初始 revision=1）
python3 -m core.tre_evo.cli --db "$DB" add-refinement \
  --edge "$EX/refinement-edge.json" \
  --child "$EX/hypothesis-child.json" --expected-revision 1

# 4. 查看树快照、细化类型、来源引用和当前 revision
python3 -m core.tre_evo.cli --db "$DB" show-tree --tree-id TREE-DEMO-001
\`\`\`

示例里的 market/price/imbalance 不表示已经测得的市场现象；\`example_status=illustrative_only\`。生产环境不得将这些示例作为量化实证依据。

## 接入原现象发现器：只读、两阶段

原始 \`core/cog/phenomenon_miner.py\` 的 \`mine(conn)\` 返回四类候选：局部裂缝、同族冲突、跨 feed、跨时间尺度，但通常缺少完整数据窗口和独立复核信息。**不能直接赋予 \`Phenomenon\` 身份或把“MODERATE”当成已核实证据。**

\`\`\`bash
python3 -m pip install numpy
python3 -m core.tre_evo.cli --db "$DB" mine-candidates \
  --source-db /absolute/path/to/your/existing/factors.db
python3 -m core.tre_evo.cli --db "$DB" list-candidates
\`\`\`

适配器以 SQLite \`mode=ro\` 打开源数据库。也可导入原有矿工产出的 JSON 数组：

\`\`\`bash
python3 -m core.tre_evo.cli --db "$DB" import-candidates \
  --input /path/to/phenomena.json \
  --source-ref "factor-db-snapshot-2026-11-16"
\`\`\`

原始数据放到 \`phenomenon_candidates\` 表，标记为 \`unverified\`；按来源和观察内容去重，忽略旧代码的批内序号。导入不会修改任何已存在的树，也不会触发回测、写因子或调用 LLM。

若要将候选正式用于假设细化，研究者需要先调查来源/样本窗口/未来时序/筛选偏差，建立合格的 \`Phenomenon\` JSON，再执行 \`record-phenomenon\`。只有已登记的现象 ID 能出现在 \`HypothesisNode.source_phenomena\`。该记录工作不自动声称因果关系。

## 数据模型和完整性

| 表 | 含义 |
|---|---|
| \`trees\` | tree_id、root_node_id、递增 revision |
| \`nodes\` | 版本化契约的 HypothesisNode JSON，复合主键 tree_id/node_id |
| \`edges\` | Typed RefinementEdge，唯一子节点约束、外键 |
| \`phenomena\` | 满足 Phenomenon Schema 的来源记录 |
| \`phenomenon_candidates\` | 旧 miner 的未审核候选 + 原始 JSON + source_ref |

创建子节点是**单个原子事务**：校验 Schema、父节点存在、细化理由、非自环、未归档、现象引用、树版本，再一次性插入 Node + Edge 并增加 revision。新节点只能由一个已存在的父节点扩展且不可重新挂接，因而不产生环。

同一 \`edge_id\` / \`node_id\`、完全相同内容的重复请求返回 \`created=false\`；否则拒绝冲突。不同分支并行细化时使用 \`expected_revision\` 防止丢更新。一个分支建立后仍可以通过新的版本继续展开。

**能力边界**：程序只能确认结构约束和明确的关联，不能保证语言模型给出的机制在经济学或市场统计意义上正确；\`refinement_warrant\` 仍需要人工/独立评审判断内容有效性。现象字段有 evidence_ref 不表示引用真实可复核；外部审计仍必须检查。当前只有“新增节点/查询树”，没有修改节点、重挂接、删除树、自动多模型评分或多 Agent 编排。

## 测试

\`\`\`bash
python3 -m pip install "jsonschema>=4,<5" "numpy>=1.24,<3"
python3 docs/standardization/validate.py
python3 -m unittest discover -s tests -p 'test_tre_evo_tree.py' -v
\`\`\`

测试覆盖持久化、幂等重试、版本冲突、分叉、非法父子关系、来源保护、时序检查、CLI 端到端和只读 miner 接口。所有样例都为合成数据，**未验证真实因子收益或树的研究有效性**。

## 下一步（未实现）

1. 已有 10 个仅供人工校准的审查种子；接下来需要独立人工盲审的正式小样本评测集（语义新信息、机制合理性、错误关联）。
2. 引入独立的节点状态更新事件及证据审计；谨慎定义研究状态与执行状态的界限。
3. 评估 Phenomenon 候选的统计有效性（时间窗、样本选择、稳定性），再将其转为可靠的研究线索。
4. 建立实验设计适配层，**通过明确的 contract adapter** 进入现有 \`investigation\`，不要直接将 \`ExperimentDesign\` 当成现有 \`Test Contract\`。
5. P1 现有 \`auto-loops.sh\` 续传/paused/车道归属问题仍独立待修复。
