# Corpus Autoloop · 真实执行适配器（v0.2）

状态：**生产工具对接代码已实现，线上平台尚未实际运行验证**。该模块会在显式授权后写入真实 \`quant-mcp\` 研究状态/ideas 表、运行 OpenCode 因子代理、向真实平台提交任务。当前 GitHub CI 完全由受控 FakeBackend 测试驱动，不含真实行情、模型或平台凭据。

## 组件

| 组件 | 使用的真实能力 | 边界 |
|---|---|---|
| \`execution_adapter.py\` | \`mcp.tools.state.run_init/run_load/run_save\`、\`mcp.tools.persist.persist_candidates\` | 保证研究对象与原有 run_id 绑定，按所有权 token 恢复；只创建研究 idea，不直接提交平台任务 |
| \`agent_runner.py\` | 显式配置的 \`opencode run\`，读原项目的 \`run-factor-agent.md\`、\`write-factor/SKILL.md\` | 依赖本机工具/quant-mcp；串行执行；不信任 Agent 文本冒充真实结果 |
| \`execution_adapter.collect\` | 已落盘的 \`state.factors[0].evidence.eval_metrics\` 和 \`ridge_svd_agg\` | 自动取 GPU R2_X/res_IC、screening ICIR、稀疏日级 ICIR；源代码 fidelity 审核必须绑定 .h SHA-256 |
| \`holdout_adapter.py\` | 已有 CPU 提交表单+日期字段、真实 \`check_factor_programmatic\` | CPU 独立日期确认；**GPU 2025H1 固定窗口不被冒充为 holdout** |
| \`admission_adapter.py\` | 原 \`mcp.tools.persist.persist_factor(mode=commit)\` | **先独立确认 + 完整交易/稳定性复核，后写生产 factors 表** |
| \`fusion_adapter.py\` | 一次机制融合提案、独立 quant-mcp run、GPU screening | 冗余因子只允许一次融合 trial；未通过可凭真实证据进入拆分 |
| \`fusion_confirmation.py\` | 原候选、库中近邻、融合候选三个 CPU 保留期回测 | 事前固定 Y 目标与同一期间；核对已有因子源文件；成功后才提交真实融合因子 |

## 真实运行环境检查

必须在原 Factor Autoloop 运行机器上，有可访问的 Factor DB、\`featuretool_creds.json\`、经授权的真实行情平台、配置好的 \`quant-mcp\` 和运行所需 Python 依赖。Opencode 必须具备原项目 mcp 配置、模型和写 factor .h 权限。

所有可能写生产工具或向平台提交的命令**必须显式带** \`--enable-platform-writes\`。这不是一键演示；在无密钥、无环境、无确认数据时应失败而不是产生“成功”指标。

使用项目级虚拟环境执行 \`python -m core.corpus_autoloop.cli ...\`。

## Step 1 · 准备《道德经》第一章 ResearchObject

~~~bash
DB=~/.quant-corpus-autoloop/research.sqlite3
python -m core.corpus_autoloop.cli --db "$DB" seed
python -m core.corpus_autoloop.cli --db "$DB" next
python -m core.corpus_autoloop.cli --db "$DB" hypothesis \
  --object-id RO-DDJ-001 --expected-revision 1 \
  --response-file corpora/daodejing/examples/chapter_001_hypothesis.json
python -m core.corpus_autoloop.cli --db "$DB" factor \
  --object-id RO-DDJ-001 --expected-revision 2 \
  --response-file corpora/daodejing/examples/chapter_001_factor.json \
  --capabilities-file /path/to/VERIFIED-platform-fields.json
~~~

示例因子规范尚**不是** C++ 代码；模型会在执行阶段依照项目 Skill 生成真实 .h。新 ResearchObject 的实际版本用 \`show\` 检查，不能硬编码延续已有数据库的 revision。

## Step 2 · 初始化真实 quant-mcp Run

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" execution-start \
  --object-id RO-DDJ-001 --expected-revision 3 \
  --dataset-ref "platform/default_test/2025-01-01_to_2025-06-30" \
  --library-snapshot-ref "/path/to/frozen-factor-library-snapshot" \
  --enable-platform-writes
~~~

此步真实调用 \`run_init\` + \`persist_candidates\`，建立 \`run_id\` 和 idea 库记录。可从 \`execution-status\` 查看绑定。不会直接提交 GPU 或 CPU 任务。相同对象重复调用会读取原 run，不能重复创建候选；过程中进程崩溃可按 \`parent_session\` 唯一 token 恢复。

这里的平台筛选窗口采用原 \`submit_csv_and_gpu_ridge\` 默认的 **2025-01-01—2025-06-30**。\`dataset-ref\` 是用户提供的核查标识，程序无法从该字符串独立确认平台确实使用了相同时间范围；必须与真实任务提交记录对应。

## Step 3 · 真正写因子并提交

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" execution-run \
  --object-id RO-DDJ-001 \
  --executor-binary "opencode" \
  --executor-model "your-available-model" \
  --timeout-sec 1800 \
  --enable-platform-writes

python -m core.corpus_autoloop.cli --db "$DB" execution-status \
  --object-id RO-DDJ-001
~~~

执行器通过 \`opencode run --model ... --dir ...\` 在项目内运行，指示模型完成原 \`write → submit → check → restest\`。默认要能在 Opencode 会话内访问既有 \`mcp__quant-mcp__*\` 工具。日志在 \`.tmp/corpus_executor/<run_id>.log\`。

**与原 \`/research-loop\` 的重要区别**：这一阶段禁止 \`assess\` Skill 提前 \`persist_factor(commit)\`，因为我们必须先在未使用过的保留期确认才能正式入库。量化统计的筛选门槛来自原 \`assess\` 规则，但额外的交易/稳定性审查要在最终 commit 时提供。

原执行器只认项目的固定 \`.tmp/agent_task.json\`。新适配器使用排他性文件创建、串行执行、仅删除自己创建且未被改动的任务文件；同一工作区不能同时启动多个旧 Agent 任务。

## Step 4 · 从真实 run state 回收数值

真实 .h 文件写好后，按照它的实际 SHA-256 和独立 reviewer 生成本地审核 JSON：

~~~json
{
  "passed": true,
  "reviewer": "your-source-reviewer",
  "evidence_ref": "file:///path/to/actual-source-review.json",
  "sha256": "<actual generated .h SHA256>"
}
~~~

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" execution-collect \
  --object-id RO-DDJ-001 --expected-revision 3 \
  --fidelity-file /path/to/actual-source-fidelity.json \
  --nearest-file /path/to/verified-nearest-factor-names.json \
  --enable-platform-writes
~~~

\`nearest-file\` 的内容是现有因子库中**已经核实存在**的候选名称数组。如果 GPU restest 显示高度冗余但缺少合法近邻，则只能得到 \`inconclusive\`，而不是凭空构造相似因子。

从 \`eval_metrics.core_metrics.screening\` 取 \`icir/spearman/zero_ratio/pair\`；zero_ratio≥0.5 时要求日级 \`deep_best.daily_icir/daily_rank_ic\`，不能用 pooled 指标绕过；从 \`ridge_svd_agg\` 取真实 GPU \`R2_X/res_IC\`。这只覆盖预测双闸门和冗余判断，不等于完整策略评估。无法确定字段或缺指标时拒绝回填。若平台自动换名，默认拒绝直接归属为原因子，必须核查真实别名后另做绑定修复。

## Step 5A · 独立候选的保留期确认 + 入库

仅当对象状态是 \`awaiting_confirmation\` 才可执行：

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" execution-confirm \
  --object-id RO-DDJ-001 --expected-revision 4 \
  --fidelity-file /path/to/actual-source-fidelity.json \
  --start-date 2025-07-01 --end-date 2025-12-31 \
  --enable-platform-writes
~~~

此步真正向现有 CPU CSV IC 平台提交日期明确的**新任务**，不重新运行原 GPU restest。仅在前期已验实的 R2_X/res_IC 与独立时段的预测指标同时满足时，才进入 \`awaiting_admission\`。筛选/保留期的 dataset、execution、metric evidence 都不同。失败的 CPU task 可以在**已记录提交回执**时重查，不会再重复 POST；若 POST 后进程崩溃且没有保存任务 ID，必须人工在平台对账。

最终还需要一份对交易成本、稳定性和统计试验过程的审核：

~~~json
{
  "verdict": "pass",
  "reviewer": "research-reviewer",
  "assess_ref": "file:///path/to/actual-assess-audit.json",
  "tradability_ref": "file:///path/to/actual-cost-audit.json",
  "stability_ref": "file:///path/to/actual-stability-audit.json",
  "tradability_passed": true,
  "stability_passed": true,
  "key_strengths": ["<actual observed strength>"],
  "key_weaknesses": ["<actual observed weakness>"]
}
~~~

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" execution-admit \
  --object-id RO-DDJ-001 --expected-revision 5 \
  --assessment-file /path/to/actual-full-assessment.json \
  --enable-platform-writes
~~~

只有这一步才调用原 \`persist_factor(mode=commit)\` 写入生产 factors 表，取得真实 \`persisted\` 回执，并把 \`confirmation_ref\` 绑定到已存储的 holdout execution_ref。**指标/审查文件里的非空 URI 并不天然证明其真实性，执行机器上仍需完整产物审计。**

## Step 5B · 冗余候选的融合 + 失败驱动拆分

当状态为 \`awaiting_fusion\`：

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" fusion-plan \
  --object-id RO-DDJ-001 --expected-revision 4 \
  --capabilities-file /path/to/VERIFIED-platform-fields.json \
  --model "your-model" --base-url "https://your-provider/v1"

python -m core.corpus_autoloop.cli --db "$DB" fusion-start \
  --object-id RO-DDJ-001 --expected-revision 4 --enable-platform-writes

python -m core.corpus_autoloop.cli --db "$DB" fusion-run \
  --object-id RO-DDJ-001 --executor-model "your-model" --enable-platform-writes

python -m core.corpus_autoloop.cli --db "$DB" fusion-collect \
  --object-id RO-DDJ-001 --expected-revision 4 \
  --fidelity-file /path/to/actual-fused-source-review.json --enable-platform-writes
~~~

单对象最多一个融合提案，且必须来自 \`independence.nearest_factors\` 所指的真实因子；\`fusion-plan\` 会调用现有 factor DB 获取近邻的元数据。筛选不通过，自动记录真实失败，进入 \`awaiting_split\`（当 depth<2）。

融合筛选通过仍不能称成功，必须使用**相同的独立 Y 目标**、同一 CPU H2 窗口分别评估原候选、近邻与融合因子。融合成功的最低操作性判据是：

\[
\Delta = |ICIR_{\rm fused,H2}| -
 \max(|ICIR_{\rm original,H2}|,\ |ICIR_{\rm nearest,H2}|) > \delta
\]

默认预设 \`delta=0.05\`，并要求 \`|rank_ic|\ge 0.01\`。**这不是经过严格推导的因果增量或多重检验修正统计量**；必须再附人工审查、统计协议和交易性审核。非零差异也不自动证明长期有效。

示例 \`fusion-review.json\` 结构：

~~~json
{
  "reviewer": "independent-researcher",
  "evaluation_ref": "file:///path/to/frozen-comparison-protocol.json",
  "statistical_protocol_ref": "file:///path/to/multiple-testing-audit.json",
  "target": "Y.<exact-predeclared-target-and-horizon>",
  "tradability_passed": true,
  "stability_passed": true,
  "multiplicity_controlled": true,
  "tradability_ref": "file:///path/to/fusion-costs.json",
  "stability_ref": "file:///path/to/fusion-stability.json",
  "allow_single_holdout_comparison": true
}
~~~

~~~bash
python -m core.corpus_autoloop.cli --db "$DB" fusion-confirm \
  --object-id RO-DDJ-001 --expected-revision 4 \
  --nearest-source-file /actual/path/from-factor_detail/<similar-factor>.h \
  --review-file /path/to/frozen-fusion-review.json \
  --start-date 2025-07-01 --end-date 2025-12-31 \
  --enable-platform-writes
~~~

必须从正式库中找到 \`nearest_source_file\`，且实际路径与 \`factor_detail\` 一致。正向结果会在当前 heldout/quality门禁后真正调用 \`persist_factor(commit)\`，终态 \`terminal_fused\`；未通过则 \`awaiting_split\`，再用原已有 \`split\` 创建两子假设（最多 depth=2）。

## 限制与审计（必须读）

- GitHub CI 只能证明控制流/错误处理在模拟平台响应下成立。**没有在你的生产平台跑任何真实 C++、GPU 或 CPU 回测；不代表找到有效因子**。
- CPU holdout 使用平台的独立日期；GPU ridge 固定 2025H1，因此它仍然只属于 screening 证据。
- \`screening\` 与 \`holdout\` 无法仅靠 \`dataset_ref\` 文本验证数据语义；日期由实际 CPU 提交参数控制，但平台内部 DAG/数据落地仍要审计。
- 原系统 \`assess\` 原本会提早 commit：新适配器有意切断这一步，用内部数值门槛与显式审核文件完成确认后再调用原 persist 工具。
- 因子融合的 \`Δ|ICIR|\` 是便于工程比较的保守代理，但不是统计显著性的充分判据；必须审查同目标/同样本、依赖性与选择偏差，不能无限重复使用 H2。
- 同一个工作区仅单执行器，未做多用户/多进程锁租约；任务停止或失联要审查真实平台任务后再恢复。
- 同步 Opencode 运行不会自动创建后台监控任务。通过 \`next\` 手动或外部受控调度继续 81 章。
- 对象拆分后保留原始章节、失败原因与两层上限，独立失败在这版仍直接结束，**只有真实融合失败才会分裂**。
- 如果现有 GPU/CPU 平台修改提交日期、输出结构或回测配置，本适配器必须随之更新，不能伪造字段填补。
