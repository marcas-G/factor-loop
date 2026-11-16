# 04 · 状态机、恢复与操作标准

## 三套状态不能混用

1. **研究节点状态** `HypothesisNode.node_status`：`open → ready_to_test / blocked / archived`。可能从 blocked 回到 open（获得新数据）；不自动由因子 IC 判定。
2. **认识论状态** `HypothesisNode.evidence_status`：`untested / provisional_support / provisional_conflict / mixed / unidentifiable`。可多次更新，并且保留历史证据；不是永久“true/false”标签。
3. **执行 run 状态**：当前运行时代码使用 `running / paused / done`；因子候选使用 `pending / submitting / done / failed`。**这些是现有生产值**，不是假设树状态。建议未来增加有原因的失败/取消分类，但必须通过版本化迁移，不能直接把新状态写进现有运行系统。

```text
HypothesisNode: OPEN --(已知哪些观察可区分)--> READY_TO_TEST
       |                     |                    |
       +--(数据/观测不可得)--> BLOCKED <--(实验限制)--+
       |                     |
       +--(不再继续研究)-----> ARCHIVED
       +<--(新观测能力出现)---- BLOCKED

Run (现有): RUNNING -> PAUSED -> RUNNING -> DONE
Factor (现有): PENDING -> SUBMITTING -> DONE | FAILED
```

研究节点 READY_TO_TEST 后发生的 **一次因子执行失败** 只影响实验记录与候选状态；不能自动标为该节点的科学假设为假。

## 统一的命令 / 工具行为约定（目标，不是已实现 API）

| 目标操作 | 输入 | 输出 | 拒绝条件 |
|---|---|---|---|
| `phenomenon_record` | Phenomenon | 不可变 phenomenon_id | 缺观察来源/观测窗口/数据使用状态 |
| `hypothesis_create` | HypothesisNode | 新 node_id | 与已存 node_id 冲突 |
| `hypothesis_refine` | RefinementEdge + child | edge_id + child_id | 自环、环路、无细化理由、语义上没有新增内容 |
| `experiment_plan` | ExperimentDesign | experiment_id | 无 H0/区分预测、未来数据泄漏、混淆干预与观察 |
| `experiment_compile` | ExperimentDesign + node | Test Contract 或 FactorHandoff | 不可观测、语义对应不成立、无合法时间窗 |
| `evidence_attach` | 运行平台的证据引用 | node/experiment evidence log | Agent 自报结果、数据来源/统计定义未知 |
| `run_resume` | run_id + version | 原运行恢复或明确拒绝 | 未拥有 run 租约、任务已终止、版本冲突 |

这些接口尚不存在；第一期仅通过目录下 JSON Schema 和样例检查数据边界。

## 运行时约定（下一步具体改造）

- **按 run_id 认领工作**，不使用 `ls -1t ~/.quant-runs | head -1` 的全局最新目录推断任务所有权。
- 明确区分 `done`（完成）与 `paused`（等待恢复或人工介入）。暂停不能自动触发全新研究任务。
- 续传中轮询的目标是明确的当前 `run_id`；读取它的 `status`，不要求恢复后生成另一个新 run_id。
- 使用 lease + heartbeat + 单写入者或版本/CAS，替代仅依赖线程锁与猜测工作进程是否存在。
- 关键写操作应有 idempotency key：重试相同 task / experiment 时不得重复提交真实平台任务或重复记账。
- 状态更新应校验允许的迁移；禁止由模型任意覆盖 `status`，或跳过前置产物直接宣称 done。
- 实际实验结果通过服务端程序存盘并给出 evidence ref；禁止让 Agent 总结后的文本覆盖或代替原始证据。
- 不让自动研究进程默认以 `bypassPermissions` 运行无隔离的生产环境；将权限、资源预算和可写路径收敛到独立运行器。
- 因子执行资源预算和假设探索预算分开计费；重复读取已有证据不应被算作一次新实验。
- 将 `run_id`、`node_id`、`experiment_id`、`factor_xname` 四种标识隔离，建立显式关系表或可审计外键。

## 证据治理

- 现象发现阶段可以使用 discovery 数据；筛选阶段记录所有试验候选与比较次数。
- holdout confirmation 由独立的验证步骤授权，禁止将已经用于选择假设的同一批样本当成未使用的确认样本。
- 每项结论应记录来源版本、时间戳、市场/品种、目标时域、结果生成程序和观测 / 因果等级。
- 不要将 `assess` 的高 ICIR / res_IC 判为“机制证实”；保留效应大小、置信区间及失败模式。
- 观察性条件分层不能冒充生物学中的 knockout / rescue 等主动干预。

## 下一期 P0 测试（尚未实现）

- [ ] 新 run 完成，观察到一次 done 且仅一次 round marker。
- [ ] 恢复 **同一** run_id，完成后也只写一次 marker。
- [ ] paused 不归入完成，不开启新 run。
- [ ] 两条车道的状态归属互不串线。
- [ ] 子代理在写因子后退出，恢复不重复提交。
- [ ] 外部重启/多个进程并发写同一 run 时不丢状态。
- [ ] 研究节点的证据状态与执行状态不会相互覆盖。
- [ ] 未使用确认集与已经查询过的确认集有不同审计记录。
