---
name: corpus-autoloop
description: 按《道德经》章节驱动的跨领域因子研究循环。逐章抽取原文，不按金融相关性筛选，先尝试来源锚定的可检验假设，再通过现有量化执行器验证；独立则入库，冗余则融合，融合失败按证据最多细化两层。
---

# Corpus-Guided Factor Autoloop

入口：python3 -m core.corpus_autoloop.cli。基础队列详见 docs/corpus-autoloop.md；**真实执行与融合/确认顺序**详见 docs/corpus-execution-adapter.md。

## 不变量

- **抽样源是语料章节**，而不是旧的因子血缘或空泛的“量价主题”。默认《道德经》81 章；不得因为不属于金融知识就跳过章节。
- **强制尝试，不强制伪造成功**。生成一个具有原句锚点、跨域映射、观测预测、反例/替代解释和数据需求的假设。不能生成有效假设时如实报告失败。
- **先有真实执行结果，再决定入库、融合或拆分。** 模型生成的 factor formula 只是规范，不能伪装成已写好、已编译、已提交的 C++ 因子。
- **入库不是只看独立性。** 因子忠实度和预测能力也必须通过；独立候选需要未参与筛选的确认记录以及真实 persist receipt。
- **冗余优先融合。** 使用现有 library snapshot / Ridge-SVD / residual IC 识别近邻因子，设计有限的组合或条件融合，真实运行并在独立确认集检查增量。成功并持久化才结束当前对象。
- **融合失败再拆分。** 使用具体失败报告、原假设、章节原文产生两个不同的机制/条件子假设。每条路径最多 depth=2；同一章节根最多 7 个对象。
- **完整的事件历史和数据隔离。** 每次实验必须记录 executor run_id、结果引用、已使用数据、图谱/因子库版本。模型对自述的“实验成功”没有事实认定权。
- **只能由执行器真实调用工具**：现有 quant-mcp 的 run_init、persist_candidates、写因子、submit/check/assess。不可通过虚构报告将研究对象标记为 terminal_admitted 或 terminal_fused。

## 操作协议

1. 在隔离 SQLite 路径执行 CLI seed（一次即可），再执行 next 返回当前需要处理的 ResearchObject。
2. 若状态为 pending/awaiting_hypothesis，读取原章原文。执行 hypothesis 命令（允许 --response-file 离线测试；真实运行需配置模型端点），生成唯一章节锚定假设。
3. 若状态为 awaiting_factor，确保可观测数据字段确实可从平台取得，执行 factor --capabilities-file /path/to/verified-fields.json；转换为 handoff。
4. 使用 CLI `execution-start` 创建真实 quant-mcp run、`execution-run` 运行已有 write-factor/run-factor-agent，再用 `execution-collect` 读取**原始** state/eval_metrics/ridge_svd；不要用 Agent 文本报告替代实际平台证据。**不要在独立确认前调用旧 `assess` Skill 中的 persist_factor(commit)；该步骤会提早改写生产因子库。**
5. `execution-collect` 必须有当前 .h 的哈希绑定忠实度审核。进入 `awaiting_confirmation` 时用 `execution-confirm` 提交**非重叠 CPU 日期区间**的真实任务；通过并获得完整稳定性/成本审核后 `execution-admit` 才能调用原 persist_factor(commit) 入库。
6. 状态 awaiting_admission：仅使用已确认的 execution-ref 和原始生产工具回执，禁止人工拼接假的 persist_ref。
7. 状态 awaiting_fusion：执行 `fusion-plan → fusion-start → fusion-run → fusion-collect`，只允许一次机制融合；筛选合格还需 `fusion-confirm` 对原候选、近邻及融合因子在同一独立 CPU 期间、相同 Y 目标做对照，并要求真实库内近邻源码、稳定性/交易性与统计审核。通过才入库；失败才产生拆分。
8. 状态 awaiting_split：把当前原文/假设/因子评价/融合失败完整作为拆解依据，执行 CLI split；产生两个子对象。新子对象已有假设，直接从 await_factor 开始。达到 depth=2 禁止再拆。
9. 当前研究对象进入 terminal_ 时，重新执行 next，推进该章节剩余子对象或下一个章节。任何停在等待外部证据的状态都不得通过杜撰结果推进。

## 未集成能力

这个 Skill 是 Agent 编排协议，不是已经启动的后台任务。当前核心模块有语料队列、模型桥、候选规范、判断门禁、split，但不会自动登录外部平台，不会自动搜融合参数，也不会验证外部 evidence_ref 指向的文件确实存在。受控执行后必须先审计正式实验记录，才能把这些能力称为完整自动运行。
