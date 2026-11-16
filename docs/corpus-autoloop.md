# Corpus-Guided Factor Autoloop v0.1：语料驱动研究闭环

**实现状态：可运行的独立调度器 + 81 章真实语料 + 模型输入输出 + 平台交接 + 离线测试。**

**还未实现/不能冒充：** 此模块不会自动调用量化平台、不会自动生成 C++ 头文件、不会读取或覆盖生产 factors.db、不会替现有 `assess` 作出研究结论。真正的写因子/回测/融合依赖已存在的 quant-mcp 与 Agent，以及其返回的实测结果。本流程由本地持久化状态管理，不默认开启持续后台循环。

## 核心研究策略

`章节（无关金融也照样尝试） → 一个来源锚定的金融假设 → 因子规范 → 真实执行 → 忠实度 + 预测效果 + 独立性 → 独立有效则待确认入库 / 冗余则尝试融合 / 失败则按证据拆分 → 两层后停止 → 下个章节`。

- **强制尝试而非强制成功**：每章必须尝试迁移，但文本不具备可实现的机制时，必须拒绝虚构公式/数据。不会静默跳过章节。
- **失败可审计且不阻塞下一章**：实际尝试后如确实无可测量假设、缺少必要数据或平台不可用，可使用 `fail --object-id ... --stage hypothesis|factor|... --attempt-ref ... --reason ... --expected-revision N` 显式结束，并记录失败踪迹。禁止在尝试前仅凭“与金融无关”直接跳过。
- **研究对象：** 初始是书的完整章节；拆分后是具体子假设，仍持有原章原文、父 ID 与失败证据。
- **一个对象一条假设/一个因子规范；每次拆分两个子对象；最多 depth=2。** 即单章最坏 1 + 2 + 4 = 7 个研究对象；每章会产生的实际执行尝试和成本仍需进一步预算约束。
- **独立性不等于预测有效性**：忠实度、预测能力、冗余/残差 IC 独立判定；并记录所用因子库快照及数据拆分。
- **成功要有实证与持久化凭证**：独立候选必须在 holdout_confirmation 成立后进入 awaiting_admission，并等待真实因子库入库凭证；融合必须在独立确认有增益且已持久化后才算成功。

## 模块

| 模块 | 职责 |
|---|---|
| `corpora/daodejing/parts` | 经文 81 章，逐章编号和来源锚定 |
| `core/corpus_autoloop/corpus.py` | 静态语料读入、版本检查、内容 SHA |
| `core/corpus_autoloop/generator.py` | 从章节强制尝试生成假设；生成一个 FactorSpec；失败证据驱动拆分 |
| `core/corpus_autoloop/contracts.py` | 因子、评估、融合、入库、拆分的输入校验 |
| `core/corpus_autoloop/workflow.py` | SQLite 状态机、独立研究对象队列、幂等 corpus 初始化、版本 CAS |
| `core/corpus_autoloop/cli.py` | 各阶段命令及执行后回填实证结果 |
| `.agents/skills/corpus-autoloop/SKILL.md` | Agent 与现有 quant-mcp/write-factor/assess 的交接协议 |

## 运行第一章

在仓库根目录，使用隔离的新 DB（不涉及现有生产因子库）：

~~~bash
python3 -m pip install "jsonschema>=4,<5"
python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite seed
python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite next
python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite show --object-id RO-DDJ-001
~~~

第一个对象对应《道德经》第一章；书中每章都会被登记，无金融相关性预筛选。

### 模型生成

需显式配置兼容 OpenAI Chat Completions 的 endpoint；**模型会看到所抽取的原文章节**，不要把未授权公司数据送入外部 API。

~~~bash
export TREEVO_LLM_BASE_URL="https://your-provider.example/v1"
export TREEVO_LLM_MODEL="your-model-id"
export TREEVO_LLM_API_KEY="your-api-key"

python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite hypothesis \
  --object-id RO-DDJ-001 --expected-revision 1

python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite show \
  --object-id RO-DDJ-001
~~~

研究假设必须含可在《道德经》第一章逐字定位的 `source_quote`，再说明 `source_principle`、`market_analogy`、`observable_prediction`、`required_data`、`alternative_explanation`、`causal_limit`。这防止模型看完章节后完全脱离文本随便造一个因子。

~~~bash
# 确认当前对象的 revision 后，将平台**实际可用**的原始字段类型列成 JSON 数组
# 如 ["orderbook","trade","price"]；这只是示例，不代表自动检测到实际字段。
python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite factor \
  --object-id RO-DDJ-001 --expected-revision 2 \
  --capabilities-file /path/to/actual-available-fields.json

python3 -m core.corpus_autoloop.cli --db ./corpus-demo.sqlite handoff \
  --object-id RO-DDJ-001
~~~

模型只生成与当前假设精确一致的 FactorSpec，不直接写 .h。输出的 `handoff.factors[0]` 与现有 `persist_candidates` 参数字段兼容；通过已存在的 quant-mcp：

1. 调 `run_init` 拿到新的 `run_id`。
2. 调 `persist_candidates(run_id, idea_text, factors)`，保持 `research_object_id` 作为 Agent 交接与审计的外层元数据。
3. 由真实的 `write-factor / run-factor-agent` 生成、提交、检查、读取完整结果。
4. 调 `assess` 收集真实忠实度、IC/ICIR、Ridge-SVD / ResIC 等证据；不能只根据模型自报“回测成功”。
5. 将平台的 run_id、因子名称、结果路径、样本和因子库快照形成 Evaluation JSON，调用 `evaluation --file /path/to/actual-eval.json --expected-revision <当前版本>`。

**注意：** 这里的 CLI 只检查报告结构和关联标识，**尚不能自行验证外部 evidence_ref 是否真实存在**；此证据适配/审计责任仍属于执行器和 Agent，不能拿 fixture:// 字符串冒充正式试验。

## 第一章离线研究样例（不会执行量化平台）

仓库包含一组**完整原文锚定的教学假设和因子交接**，而不是虚构的回测结论：

- `corpora/daodejing/examples/chapter_001_hypothesis.json`：引用第一章原文“此兩者，同出而異名”，将两个观察视角的关系类比为事前成交失衡与盘口失衡之间的冲突。
- `corpora/daodejing/examples/chapter_001_factor.json`：给出一个非线性冲突信号的**描述性 FactorSpec**；`formula` 并非可直接运行的 C++。
- `corpora/daodejing/examples/illustrative_capabilities.json`：仅为样例字段表；**不是对真实量化平台数据能力的认证**。

~~~bash
DB=./corpus-demo.sqlite3
python3 -m core.corpus_autoloop.cli --db "$DB" seed
python3 -m core.corpus_autoloop.cli --db "$DB" hypothesis \
  --object-id RO-DDJ-001 --expected-revision 1 \
  --response-file corpora/daodejing/examples/chapter_001_hypothesis.json
python3 -m core.corpus_autoloop.cli --db "$DB" factor \
  --object-id RO-DDJ-001 --expected-revision 2 \
  --response-file corpora/daodejing/examples/chapter_001_factor.json \
  --capabilities-file corpora/daodejing/examples/illustrative_capabilities.json
python3 -m core.corpus_autoloop.cli --db "$DB" handoff \
  --object-id RO-DDJ-001
~~~

运行到这里仅有一个候选 `FactorSpec`，状态是 `awaiting_evaluation`，**没有 C++ 生成/提交、没有 IC/ResIC/融合结果，也没有任何因子入库**。后续必须由真实 Agent 和 quant-mcp 负责执行。如果在同一个 DB 已处理过第一章，请改用全新隔离路径，否则版本检查会拒绝重复步骤。

## 决策表

| 实测条件 | 下一步状态 | 含义 |
|---|---|---|
| 忠实度、预测、独立均通过；仅筛选集 | `awaiting_confirmation` | 必须另做保留集确认 |
| 独立确认通过且独立 | `awaiting_admission` | 等待真实因子入库回执 |
| 预测/忠实通过，但与库高度冗余 | `awaiting_fusion` | 尝试与近邻因子融合 |
| 融合有独立确认增益且已入库 | `terminal_fused` | 当前研究对象结束 |
| 融合无增益 | `awaiting_split`（depth<2） | 读取失败证据，进行具体机制拆分 |
| 因子忠实度/预测能力不通过 | `terminal_exhausted` | 不盲目拆分没有发生融合的失败 |
| 融合失败且 depth=2 | `terminal_exhausted` | 此分支结束 |
| 各分支终止 | `next` 指向下一个章节 | 按章节顺序处理 |

当独立性结论为 inconclusive 时，研究对象保持 `awaiting_evaluation`，需要更多真实证据而不是自动入库。

### 实测评估 JSON（仅字段示意，不代表结果）

~~~json
{
  "executor_run_id":"<actual quant-mcp run id>",
  "factor_xname":"<factor name>",
  "execution_ref":"<real execution artifact uri>",
  "library_snapshot_ref":"<factor library revision>",
  "dataset_ref":"<real screening dataset identifier>",
  "data_split":"screening",
  "fidelity":{"passed":true,"evidence_ref":"<real fidelity audit>"},
  "predictive":{"passed":true,"metric_name":"ICIR","metric_value":0.0,
                "evidence_ref":"<real platform screening result>"},
  "independence":{"decision":"redundant","r2_x":0.0,"res_ic":0.0,
                  "nearest_factors":["<existing xname>"],
                  "evidence_ref":"<real Ridge-SVD result>"}
}
~~~

`passed` 和 `decision` 必须由执行端依据实际统计规则填充，不可将上述 0.0 占位值视为有效指标。现有各项指标方向和阈值继续由 `assess` 管理。

## 融合与拆分

- 融合策略（在现有 Agent 执行侧）可先试已有因子加权、条件选择或机制互补；只有独立确认的增量效果 >0 且含实际 `persist_ref` 才被标记为 `terminal_fused`。
- 融合无增益则调用 `fusion --file failure.json --expected-revision N`，进入 `awaiting_split`。
- `split --object-id ... --expected-revision N` 会以**原文 + 当前假设 + 实测失败/融合记录**为输入，生成两个机制、条件或观测不同的子假设，自动建立子对象；不允许纯随机公式变异。
- 子对象无需再从书中重新生成源假设，而是直接进入 `awaiting_factor`；最多两次向下拆分（depth=0→1→2）。父节点保留完整的来源和决策链，不会反复加入队列。
- 成功入库、融合入库后不再拆分；若失败且达到 depth=2，分支终止。

## 限制与下一阶段

- **证据审计增强（v0.1）**：

- Screening 与 holdout 必须使用不同的 `dataset_ref`、`execution_ref` 和预测指标证据引用，无法直接把同一批测试改名为独立验证。
- 独立入库回执中的 `confirmation_ref` 必须精确引用已登记的 holdout `execution_ref`。
- 融合成功须填写 `source_evaluation_ref`（当前候选的实际评价引用）、`confirmed_dataset_ref`（区别于此前评价的独立数据集），及真实 `persist_ref`。
- 默认运行拒绝以 `fixture://`、`mock://`、`synthetic-` 开头的实验回执；合成测试需要显式设置仅供测试的 `allow_fixture_receipts=True`。
- **重要边界**：仅做静态一致性和占位引用防护，仍**无法证明真实链接的文件必然存在、平台结果完整或统计结论可信**。外部执行器必须提供可审计原始产物。不要把通过静态合同误解为自动独立验证。

当前针对**单执行器**，没有多 Agent 分布式 lease。SQLite revision CAS 只保护写状态，不负责跨平台重复提交的幂等令牌。
- 因子库当前不在这个 SQLite 中，真实指标必须由现有服务查阅并形成报告；没有已实现的自动融合搜索器。
- `FactorSpec.formula` 是描述性候选规范，必须经过真实 C++ 生成和未来函数审查，不能视为已可编译的 .h。
- 自动循环可以由项目级 Skill 一轮轮调用本 CLI，但本模块**未启动无人值守后台任务**，也未发起实际 quant-mcp 会话。
- 语料来自非金融典籍，强制迁移可能产生大量无法实现的想法。必须把失败纳入全部尝试统计，并对回测设置预算、保留集和多重检验审计；不得通过反复选择提高结果后宣称独立发现。
- 后续可加入 quant-mcp 执行结果的机器读取 adapter、注册可用字段表、融合优化器、分布式工作租约及独立研究效果评测。

## 测试

~~~bash
python3 -m unittest discover -s tests -p 'test_corpus_autoloop.py' -v
~~~

测试为合成输入，覆盖 81 章、双层分裂、独立入库/融合路径、时间隔离标记、版本冲突、完整 CLI；不访问真实行情、模型服务或量化平台。
