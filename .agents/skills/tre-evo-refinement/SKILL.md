---
name: tre-evo-refinement
description: TreEvo 自顶向下的假设分析与逐层细化。识别父假设中的解释缺口，提出有机制细节、竞争解释、可观测预测及明确细化理由的子假设，并经批评及人工审核后才入树；不写因子或运行回测。
---

# Hypothesis Refinement Agent

此能力属于 Factor Autoloop 的**研究前端原型**，不直接执行因子代码、量化平台实验或自动批准科学主张。

1. 获取父假设和已有树节点，明确 open questions、unknowns、已有子节点；可以参考登记好的现象记录。原始矿工的 unverified candidate 仅能作为未证实线索。
2. 找出最值得展开的一处解释缺口。没有抓手时应当选择 abstain，不要机械展开分类树。
3. 使用五种操作之一：mechanism_decomposition、condition_specification、competing_explanation、process_elaboration、operationalization。输出明确的父子关系、细化理由、新信息、替代解释、独有可观测预测及未识别边界。
4. 独立批评模型或独立上下文复核提案，不能直接自我认可。不得捏造已执行实验、因果结论、IC 指标或证据来源。
5. 通过 core/tre_evo/cli.py 的 propose-refinements 提交 pending queue；查看 show-refinement-proposal 及 critique。
6. **只有用户明确批准**才能调用 accept-refinement，并提供真实 reviewer/reason。拒绝后持久保存 reject reason。不可为了实现“自动循环”而假装用户已批准。
7. 完整运行命令和数据边界见 docs/standardization/07-refinement-agent.md。

TreEvo 在此阶段不是遗传算法、AST 表达式搜索或因子回测流程，而是科学解释的逐层细化。任何审查通过仅表示结构进入研究树，**不意味着科学假设得到证实**。
