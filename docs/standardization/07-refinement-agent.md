# 07 · Hypothesis Refinement Agent（TreEvo P2-b）

状态：**可运行的受控研究原型**，尚未与 factor-runner、现有研究循环或实盘系统连接。它不是遗传算法，也不生成因子公式。

## 目标与模块

核心问题：给定父假设及可选的观察线索，模型能否找出**值得细化的解释缺口**，说明父子逻辑、增加的知识、竞争解释和独有可观察预测？

| 文件 | 职责 |
|---|---|
| core/tre_evo/refinement.py | 生成、分解类型、信息增量检查和第二次模型批评 |
| core/tre_evo/model_client.py | 显式配置的兼容 chat/completions API（默认不联网） |
| core/tre_evo/review_queue.py | SQLite 中持久化 pending/accepted/rejected，人工批准时原子写入 Node+Edge+审核记录 |
| core/tre_evo/cli.py | 创建提案、查看队列、明确批准/拒绝 |
| .agents/skills/tre-evo-refinement/SKILL.md | Agent 侧调用约定 |
| docs/standardization/refinement-review-cases.json | 10 个待人工审核的正反例种子，**不是专家已标注 benchmark** |

**三道独立的审查层次**：JSON Schema/父子引用/版本号确定性校验；第二次模型调用进行批评；最后由研究者明确审核。三者不能互相替代。批评通过并不构成真实经济学机制证明。

## 离线示例，无模型账号

先按照 [06-tree-mvp.md](06-tree-mvp.md) 创建 root 和登记示例 Phenomenon，**不要先添加 child**。

在项目根目录：

~~~bash
python3 -m pip install "jsonschema>=4,<5"
EX=docs/standardization/examples
python3 -m core.tre_evo.cli propose-refinements \
  --tree-id TREE-DEMO-001 --parent-id H-DEMO-ROOT \
  --phenomenon-id P-DEMO-001 \
  --response-file "$EX/refinement-generation.json" \
  --critique-file "$EX/refinement-critique.json"
python3 -m core.tre_evo.cli list-refinement-proposals --tree-id TREE-DEMO-001
python3 -m core.tre_evo.cli show-refinement-proposal --proposal-id "RP-REPLACE-WITH-ACTUAL-ID"
~~~

提案自动入 **pending** 队列；到这里树尚未发生变化。阅读完整提案和批评，确认确实形成有依据的细化以后再明确运行：

~~~bash
python3 -m core.tre_evo.cli accept-refinement \
  --proposal-id "RP-REPLACE-WITH-ACTUAL-ID" --reviewer "your-review-id" \
  --reason "新增了明确机制条件及与竞争解释不同的观测预测"
~~~

若认为逻辑不成立，用同样的 reviewer/reason 参数执行 reject-refinement。不能将模型的自动输出视为人类批准。

## 连接外部模型（会向你配置的服务发送研究文本）

~~~bash
export TREEVO_LLM_BASE_URL="https://your-model-api/v1"
export TREEVO_LLM_MODEL="your-proposer-model"
export TREEVO_LLM_API_KEY="your-api-token"

python3 -m core.tre_evo.cli propose-refinements \
  --tree-id TREE-DEMO-001 --parent-id H-DEMO-ROOT \
  --phenomenon-id P-DEMO-001 --max-candidates 2 \
  --critic-model "your-critic-model"
~~~

默认两次调用：第一次选择解释缺口并提出候选，第二次独立批评。critic-model 可与 proposer 不同（使用相同 endpoint）；若端点要求 JSON mode，可添加 --json-mode。

不提供模型配置时 CLI 不访问任何外部网络，仍可用 response-file/critique-file 完成离线测试。模型密钥只从环境变量读取，不会保存在 TreEvo SQLite 中。请勿未经授权将公司内部因子策略或敏感行情数据发送到外部 API。

生成器需要声明候选的 refinement_type、refinement_warrant、new_information、unique_observable_prediction、alternative_explanation、evidence_limitation。没有实际抓手时必须允许 abstain（空 candidates + 明确原因），不要求每次都强行长出新分支。

Phenomenon 候选仍分两个层次：已登记 Phenomenon 可以作为节点的来源引用；从旧 miner 导入的 unverified 候选不能自动升格为事实。仅显式加 --include-unverified 才会向模型暴露最多五条未审核线索，且这些 ID 不允许成为 evidence_ref。

## 人工审核小样本

[refinement-review-cases.json](refinement-review-cases.json) 包含机制拆解、条件细化、竞争解释、时间过程、可观测化，以及同义改写、问题漂移、无依据归因、不可区分预测和未来信息泄漏等 10 个教学场景。

参考标签是**合成种子**，不是独立专家评估结果；正式验证应在冻结的真实或独立编写任务上盲审父子连贯性、非同义信息增量、假设合理性、竞争解释可区分性及证据纪律。不能把这 10 个例子作为模型研究能力已经提高的实证证据。

## 测试

~~~bash
python3 -m pip install "jsonschema>=4,<5" "numpy>=1.24,<3"
python3 -m unittest discover -s tests -p 'test_tre_evo_*.py' -v
~~~

全部模型响应由固定数据或 mock 提供；没有支付模型调用、没有真实金融数据、没有回测。确定性代码可检查结构、ID、引用及信息增量中的明显同义重复，但不能自动裁定主张的经济学真实性。
