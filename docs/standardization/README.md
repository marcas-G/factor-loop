# Factor Autoloop 标准化总览（Architecture RFC 0.1）

状态：**提案 / additive-only**。基于仓库 main 分支 `ccd54a59a9f5dc6b2298fa84242114f60ab6cc13` 的静态代码审阅（2026-11-16）；未连接市场数据和实际运行环境，未证明 TreEvo 有效果。

目的：把已有因子研究闭环标准化为清晰的职责、契约、状态机和可验证边界，并为 TreEvo **从高层逻辑逐步分析、分解和细化假设**增加一条独立入口。**不**把 TreEvo 误写成遗传算法或纯表达式树搜索。

## 阅读顺序

1. [01-current-system.md](01-current-system.md)：真实现有模块/对象与已知错位
2. [02-target-architecture.md](02-target-architecture.md)：双入口 + 共同实验后端
3. [03-data-contracts.md](03-data-contracts.md)：结构化假设/细化/现象/实验契约
4. [04-state-and-operations.md](04-state-and-operations.md)：三套独立状态机与可靠性边界
5. [05-migration-plan.md](05-migration-plan.md)：渐进迁移、验收与非目标
6. [schemas/](schemas/)：拟议 JSON Schema，不是现网数据库迁移
7. [examples/](examples/)：**纯教学**样例，不是真实市场发现
8. `python3 docs/standardization/validate.py`：静态契约校验，需 `jsonschema>=4`

## 统一术语

| 术语 | 定义 | 是否已存在 |
|---|---|---|
| Research Theme | 高层研究主题，如量价关系；无须已有因子 | 新概念 |
| Phenomenon | 可追溯的观察差异，不包含机制性归因 | `core/cog/phenomenon_miner.py` 存在原型，未标准化 |
| Hypothesis Node | 带前提、解释空白、待分解问题的假设单元 | `ideas` 可存散文，不等于此节点 |
| Refinement Edge | 解释父子假设为何构成有效细化的关系；必须说明“新增了什么” | 新概念 |
| Experiment Design | 竞争假设、控制/变化维度、可观察结果、时序边界和证据限制 | `core/cog/investigation/contract.py` 已有更窄 Test Contract |
| Factor Spec | 可执行因子候选（公式、品种、参数、实现约束） | 现有 `persist_candidates` |
| Factor Lineage | 实际因子之间修复/迭代/算子应用血缘 | 现有 `factor_lineage_*`；**禁止**当作 Hypothesis Tree |
| Run State | 一次执行 run 的持久状态 | 现有 `core/mcp/run_store.py` |

## 不变量

- **先解释，再实现**：主题与假设不必预先含因子公式；只有进入明确测试/实现边界时才构造因子。
- **细化必须增量可解释**：任何细化边都说明新增机制角色、成立条件、竞争解释、时间过程或可观测约束；不能仅换同义词。
- **观察≠解释≠因果**：观察记录、假设、模型判断、平台实验结果分别归档，不允许自动升级成因果结论。
- **不能拿预测指标替代假设证实**：高 IC、ICIR 或低冗余不证明所述机制成立；忠实度和证据边界必须保留。
- **双路径并存**：现有 factor-driven 路径继续工作；新 theme-driven / TreEvo 路径仅在版本化契约成熟后接入。
- **单一执行权威**：run state 由工具/存储层持久化；Agent 只提交结构化意图和引用，不负责猜测任务是否完成。
- **评估数据隔离**：探索、筛选和独立确认具有不同权限；不可在用过的确认数据上继续适应式提出假设后声称独立验证。
- **不破坏现网**：不修改 `.agents/skills`、`core/`、`auto-loops.sh`、现有 SQLite schema 或评估阈值；本 RFC 只新增文档、示例、静态校验。

## 相关现有资料

- [架构](../architecture.md)
- [研究循环全景](../research-loop-framework.md)
- [研究数据流](../research-data-flow.md)
- [数据模型（含设计稿部分）](../data-model.md)

注意：这些旧文档来自不同迭代期，包含“已实现”“规划中”和历史阈值混写的地方。本 RFC 在 `01-current-system.md` 中明确已核实源码与待实现扩展的界限。
