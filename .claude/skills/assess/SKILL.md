---
name: assess
description: 量化因子结果评估。触发 `/assess <run_id> <factor_index>` 或被 research-loop 嵌套调用。忠实度(实现忠于假设)+三维度+一票否决 双轨出 verdict(pass/fail)并写库。
---

# Assess — 量化因子结果评估

基于代码从平台产物聚合的评估数据(**不是 LLM 自评**),按三维度+一票否决框架对单个因子做结果评估,调 MCP 持久化 verdict。

## 输入

- `run_id`:研究 run id
- `factor_index`:state.factors 数组下标
- 或直接给 factor 对象

需要从 state 读:
- `state.idea` — 本次研究 idea
- `state.factors[i].name` — 因子类名
- `state.factors[i].hypothesis` — 因子设计假设(brainstorm 阶段由 intuition + diff_check + coord_usage 拼接而成)
- `state.factors[i].evidence.eval_metrics` — 评估数据 JSON(字段名历史命名,风是三维度各指标的数据载体)
- `state.factors[i].factor_file` — .h 文件绝对路径
- `state.factors[i].last_rewrite` — retry 信息(可能为 null)
- `state.idea_id` — 关联的 idea id

---

## 一、判定核心(评价标准)

因子评价 = **过关闸门(二元)→ 冗余度首要(价值排序)** 双轨。先过闸门(忠实度 + 信噪比 ICIR≥0.3 + 效应量 |rank_ic|≥0.01 + 可交易 + 无符号/推进反转);过闸门的因子再按**冗余度**(对组合的边际信息贡献)定去留——真正交 pass、冗余 fail。**ICIR 强弱只作过关闸门、不作排序依据**:组合价值=信息维度多样性,不是单 ICIR 高。所有指标来自平台/本地代码聚合的评估数据(非 LLM 自评)。

### 判定态度

- 单独评估此因子(不跟其他候选对比)
- **ICIR 是过关闸门非排序键**:可信 ICIR≥0.3 过关(见否决④),过闸门后强弱不再管,交给冗余度首要
- **强假设**:因子是否回应了 idea 的核心假设(hypothesis 在数据上验证)
- **强证据**:所有结论引用具体数字
- **一票否决前置**:否决任一命中直接 `fail`,不进综合;三维度数据不全时 verdict 谨慎
- **数据信任 / 无罪推定**:factor_check 流程未报错则数据可信,IC 与 cum_ret 照单全收。**cum_ret 大、conditional_sharpe 与 cum_ret 量级不匹配、数字"太好"等单独都不是怀疑理由**——IC 跨长样本全正一致 + 高频复利,累积出天文数字是正常数学结果,不是 bug。唯一可下调 IC 可信度的依据:**feed IC(screening)与 @1 因果 IC 符号相反或量级背离**(如 feed ICIR>2 但因果 ICIR<0.3),此时诊断为"对齐不一致"并倾向 fail;无此证据则 verdict/key_weaknesses 不得写任何"结果可疑/数据不可信"类的预设判断,也不据此降级。历史 lesson 里的此类旧表述不得搬用

### 第零维 · 忠实度(假设验证的前提,有 argument_chain 时必审)

因子是否真验证了它声称的假设?IC 高 ≠ 验证假设——可能来自别的机制(冒充)。

**前提**:假设有结构化 argument_chain(hypothesize 产,在 ideas.argument_chain,用 `hypothesis_get` 读)。散文 hypothesis(旧 brainstorm 无论证链)→ 跳过本维(无法对照),仅经验维度评估。

**审稿**:派 reviewer-agent 忠实度模式(模式二):
```
Task({
  subagent_type: "reviewer-agent",
  prompt: "忠实度审稿:假设论证链 idea_id=<state.idea_id>(用 hypothesis_get 读),因子实现 .h 路径=<state.factors[i].factor_file>(用 Read)。审实现是否忠于论证链核心机制"
})
```

**判据**:reviewer 返回 faithful/unfaithful。
- `unfaithful` → **一票否决**,verdict=fail(因子未验证假设,即使 IC 高)。key_weaknesses 写"实现偏离假设核心机制: <偏离点>"。
- `faithful` → 进经验维度(下述双轨判定:过关闸门 + 冗余度首要)。

**双轨本质**:忠实度(因子有没有验证假设)+ 经验(因子有没有效)。忠实度是假设验证的前提——不忠实则因子与假设无关,IC 高也是别的机制的功劳,假设未被验证。

> **🎯 冗余度首要(全局原则)**:因子价值 = 对组合的边际信息贡献,**由冗余度决定,不由 ICIR 强弱决定**。ICIR 仅作过关闸门(可信口径≥0.3,见否决④);过闸门后**冗余度是首要排序键**。⚠️ 信噪比<0.3 不过闸门——低信噪比 IC 是噪声,和谁都低相关→假"正交",冗余度判定不可信。

> **🔬 冗余主判据 = 平台 dLOOCV_pct(平台优先)**:过闸门后,用平台 Ridge-SVD 的 **dLOOCV_pct**(加入因子后 LOOCV 误差下降%,对线性模型的净增益)作主判据,替代旧的 R4 pearson+残差 IC(那是在 IC 空间做正交化,维度低信息损失大;平台在 X 空间对别人 72 因子大库做正交化,更强)。R4 降为 fallback(restest 无数据时)+ 补充检查(X 独立但 IC 行为冗余)。

### 第一维 · 预测能力(秩空间,弃 pearson)

因子在"形状/顺序"空间工作,衡量工具也必须是。

| 指标 | 判断标准 | 数据来源 |
|---|---|---|
| **秩 IC 的 ICIR**(过关闸门,非排序键) | 可信 ICIR≥0.3 过关(稀疏 zero_rate≥0.5 用 daily,稠密用 screening pooled,见"第一维补");<0.3 信噪比不足→fail。≥0.3 后 ICIR 强弱不再区分(只过闸门),不作通过依据,交给冗余度首要。负 ICIR=反向信号反着用,看绝对值 | screening / daily |
| **秩 IC 效应量**(过关闸门) | 可信 `\|rank_ic\|≥0.01` 过关。<0.01 效应极小(扣成本净亏)。和 ICIR 独立,都过才过关 | screening.ic_mean / daily mean_ic |
| **平稳性 + 差分**(新增) | ADF p<0.05 已平稳 → 无需差分;非平稳且 diff_improvement>0 → 该差分 | stationarity(adf_pvalue / need_differential / orig_ic / diff_ic / diff_improvement) |
| 显著性 | Welch t + p_value | zero |
| 分组单调性 | 5 组收益平滑严格单调 | 待补 |
| 多空盈亏比 | 胜率 40-60% 正常,盈亏比持续 >1(不被极端带飞) | 待补 |

**差分判定细则**:
- `is_stationary=true`(ADF p<0.05):因子日级平稳,不漂移,直接用原始信号 → key_strengths 写"因子平稳(ADF p={x}),无需差分"
- `is_stationary=false` 且 `diff_improvement>0`(差分后 pooled IC 升):非平稳但差分能提升 → key_weaknesses 写"因子非平稳(ADF p={x}),差分后 IC 改善{diff_improvement},建议用差分信号"
- `is_stationary=false` 且 `diff_improvement≤0`:非平稳且差分无效 → 倾向 fail(信号含漂移噪声,差分也救不了)

### 第一维补 · 稀疏因子口径(关键,防 pooled ICIR 虚高)

`screening.icir` / `csv_ic.horizons[].rank_icir` 是 **pooled rank IC**(全样本拼一起算一个秩相关)。对稀疏因子(zero_rate 高、active_rate 低)pooled ICIR **系统性虚高且可能反号**——被少数触发日主导、hit_rate 虚高到 1.0。实测:zero_rate=0.94 的因子 pooled ICIR=5.50,真实逐日 ICIR=-0.89(pooled 把 6% 触发日的秩相关放大)。

- **判定稀疏**:`screening.zero_rate ≥ 0.5` 或 `active_rate ≤ 0.5` → 视为稀疏因子
- **稀疏时口径切换**:否决④ 双闸门(ICIR + rank_ic)判据**一律改用 daily 口径**(ICIR=逐日 rank IC 的 mean/std,rank_ic=mean_ic),pooled 仅作记录、**不作判据**。负值按"反向信号"对待,关键看绝对值与逐日稳定性
- **key_weaknesses 必注明**:"zero_rate=X, pooled ICIR Y 不可信(稀疏虚高),以 daily ICIR Z 为准"
- **稠密因子(zero_rate<0.5)**:pooled 与 daily 通常一致,pooled ICIR 可用;但仍对照 daily,**符号相反即口径异常** → key_weaknesses 注明并以 daily 为准
- **🔥 预测力双闸门(统一,见否决④)**:无论稀疏/稠密,可信 ICIR<0.3 或 |rank_ic|<0.01 → fail。稀疏因子 daily IC 近噪声时尤须卡——其"低冗余"是噪声随机性非真新颖。|daily ICIR|∈[0.3,1.5) 的过关因子 ICIR 中等不丢分,继续走冗余度首要
- daily ICIR 取法见步骤4(路径B 第5步)

### 第二维 · 稳健性

验证预测能力是否可信、持久。

| 指标 | 判断标准 | 数据来源 |
|---|---|---|
| **IC 标准差**(核心) | 跨时段/regime 远低于原始,表现平稳 | session_ic(std) + vol_regime(波动 5 分位 sign_consistent) |
| 训练-测试衰减 | 衰减小(过拟合检查) | train_test |
| 最大回撤 + 修复期 | <5%、修复短;比原始大=丢信息 | deep_best(cum_ret_pct / max_dd) |
| 月度稳定 | monthly_icir 一致 | deep_best(monthly_icir) |
| 参数平坦度 | 参数-夏普曲线**高原非针峰**(针峰=过拟合) | 待补 |
| 极端日敏感性 | 最差 1% 日不巨亏 | 待补 |

> 注:第一维 screening ICIR 本身就是按天分桶 rank IC 序列(每天一个 Spearman,117 点)的 mean/std,已覆盖"逐日 rank IC 稳定性",此处不重复。

### 第三维 · 可交易性(高频必过)

避免纸上谈兵。tick 因子(500ms 高频)这是生死线。

| 指标 | 判断标准 | 数据来源 |
|---|---|---|
| **换手率** | 日均换手低;高换手=追微波动 | `tradability.avg_turnover_per_day` |
| **成本后 Sharpe(8bps)** | 毛 Sharpe vs 成本后(8bps 严格);转负=毛强净亏 | `tradability.sharpe_net_8bps` |
| 容量 | 日换手>100 → 容量受限(固定代理) | `tradability.capacity_risk` |
| 正交 | **平台 dLOOCV_pct ≥ 1%**(对线性模型显著增量,不冗余); dLOOCV<1% 且 R2_X>0.8 = 冗余; dLOOCV<0 = 过拟合 | 平台 restest ridge_svd(见"二、操作流程·查正交"); 无 restest 时 fallback 到 R4 pearson+残差 |
| **变换族预测力**(新增) | 最强变换 |IC| 显著优于原始(>20%) → 建议改用该变换；ridge_residual 最强=预测力来自新息 | transform_family(orig_ic / delta_ic / impulse_ic / asym_impulse_pos_ic / asym_impulse_neg_ic / ridge_residual_ic) |

**变换族判定细则**(对原始因子 X 做 delta/impulse/asym_impulse/ridge_residual 四种变换,各算 pooled IC 对比;assess 自己从 6 个 |IC| 判最强变换):
- 取 6 个字段 `|IC|` 最大者为 best_transform(比较 delta/impulse/asym_pos/asym_neg/ridge_residual 与 orig)
- `ridge_residual_ic` 最大且 `>> orig_ic`(差>0.02):预测力来自新息(去自相关后的 surprise),原始因子含冗余趋势 → key_strengths 写"预测力核心是新息(ridge残差IC={ridge} vs 原始{orig}),建议改用残差信号"
- `impulse_ic` 最大且 `≈ orig_ic`:预测力来自方向而非幅度,因子可二值化简化 → key_strengths
- `|asym_impulse_neg_ic| >> |asym_impulse_pos_ic|`(差>0.03):下跌冲击预测力远强于上涨(杠杆效应),因子对下行更敏感 → key_weaknesses 注一句(单向有效,多头端弱)
- `delta_ic << orig_ic` 且 `|delta_ic|≈0`:差分后预测力消失,信号在水平不在变化 → 因子是"水平型"非"动量型"(中性信息)
- 最强变换 |IC| 比 orig 高 >20% → suggested_iteration 建议"改用{最强变换}变换重做"

### 一票否决(任一命中 → verdict=fail,不进综合)

1. **样本外秩 IC 符号反转**:与样本内完全相反(zero / sign_match 可查)
2. **推进式回测失败**:滚动训练-预测,连续多月亏或后期断崖(train_test 可近似)
3. **成本翻倍夏普转负**(16bps):`tradability.veto3_cost_double`(成本翻倍 Sharpe 转负 → fail)
4. **预测力双闸门**(信噪比 + 效应量,任一不过 → fail):
   - **信噪比**:可信 ICIR ≥ 0.3(<0.3 IC 序列近噪声,冗余度判定不可信)
   - **效应量**:可信 `|rank_ic| ≥ 0.01`(<0.01 效应极小,"稳定地空转",扣 8bps 成本净亏)
   - **可信口径取法**(两者同源):稀疏(zero_rate≥0.5)用 daily(ICIR=mean/std、rank_ic=mean_ic),稠密用 screening(pooled);⚠️ 稀疏因子用 pooled 会被虚高绕过(如 ICIR5.50/rank_ic0.10 实则 daily -0.89/极小),必须用 daily
   - 救场(命中任一则不否决):变换族某形态 `|IC|≥0.3`(其他形态有可信水准信号)
   - 说明:ICIR 保证测得稳、rank_ic 保证测出来的值钱,两者独立都要过;稳定反向信号看绝对值;数据见 `screening`+`factor_ic_vec_meta`+`transform_family`

### 综合参考

- **factor_level**:平台对 N 个 X-Y 对的 KEEP/WATCH/REJECT 分布 + 最佳 score
- **failure_reasons**:平台标的失败原因(low_icir / weak_beta / vol_regime_unstable / no_zero_diff / bad_bucket_shape / weak_train_test / weak_ic)
- **top_pairs**:按 score 排序前 3 个 X-Y 对
- **deep_best 其他**:conditional_sharpe / daily_ic_tstat / daily_rank_ic / daily_icir / signal_instability_pct(daily IC 已 per-horizon 尾盘截断防未来函数;旧字段 rank_ic_max 仅旧 run 兼容)
- **新增两指标**(来自 factor_check 深度分析 `[6/7][7/7]`,经 metrics.mjs 聚合进 `evidence.eval_metrics`):
  - **平稳性+差分**:`evidence.eval_metrics.stationarity`({adf_pvalue, need_differential_rate, orig_ic, diff_ic, diff_improvement})
  - **变换族预测力**:`evidence.eval_metrics.transform_family`({orig_ic, delta_ic, impulse_ic, asym_impulse_pos_ic, asym_impulse_neg_ic, ridge_residual_ic})

### 当前缺口(待 factor_check 补)

第三维(换手/成本后/容量)+ 否决③ 已由 factor_check 算(固定严格约束:8/16bps 成本 + 换手代理容量),进 `tradability`。剩余缺口:第一维(分组单调已有 inc,盈亏比笔级缺)、第二维(参数平坦要跑参数网格,极端日可从 daily_ls 算)。**缺口指标缺失时,key_weaknesses 注明"X 未评估",verdict 谨慎**。

### verdict 含义

- `pass`:因子值得入库(算子可借鉴,下次能迭代)
- `fail`:方向已否决(避免下次重写),`suggested_iteration` 留作未来参考

---

## 二、操作流程(执行判定)

1. **取数据**:从 state 读 evidence + hypothesis + factor_file + idea_id(见"输入")
2. **忠实度审稿**(有 argument_chain 时):派 reviewer-agent 忠实度模式(见第零维)。`unfaithful` → 直接定 verdict=fail(一票否决),跳到步骤 5 commit(跳过 3/4)。无 argument_chain 跳过本步。
3. **入表占位(prepare)**:`persist_factor {run_id, factor_index, mode: "prepare"}` —— 入 factors 表(status=draft),**不写 eval/lesson、不定 verdict**。目的是让因子进表,解锁步骤 4 路径 B 的 ingest(全新因子入库前 ingest 撞外键)。
4. **查正交(第三维,check_done 必做)**:因子已入表(步骤 3),可查库间冗余。结果作为步骤 5 定 verdict 的正交维度输入。

   - **主判据 = 平台 restest ridge_svd(平台优先)**: run-factor-agent 在 check_done 后已自动跑 restest, 结果在 `state.factors[i].evidence.ridge_svd`(metrics 数组)。读它:
        ```
        # metrics = [{x_col, horizon, R2_X, res_IC, n, dLOOCV_pct}, ...]
        ```
        聚合: 取主力(非 @1)x_col 中 dLOOCV_pct 最大的那条作主判据。
        - **dLOOCV_pct < 0** → 过拟合否决(加因子 LOOCV 反升), key_weaknesses 写"restest dLOOCV={x}<0 过拟合"
        - **dLOOCV_pct < 1% 且 R2_X > 0.8** → 冗余否决(因子值被大库解释 80%+ 且无增量), key_weaknesses 写"restest R2_X={x} dLOOCV={y}% X空间冗余且无增量"
        - **dLOOCV_pct ≥ 1%** → 显著增量, 正交通过(真正交 pass 的高价值因子)
        - **无 ridge_svd(restest 没跑/失败)** → fallback 到下方 R4

   - **fallback = R4(restest 无数据时)**:抓"公式不同但日级 IC 同涨同跌"的真冗余。
     1. 导 daily_ts(一步 CLI,自动处理 P6 外存 JSON 或 check_output CSV):
        ```
        Bash: /home/lgao/quant-venv/bin/python core/tools/ingest_evidence_ts.py \
              --evidence-file <state.factors[i].evidence_file> --xname <xname>
        ```
     2. Bash `/home/lgao/quant-venv/bin/python3 core/tools/vec_refresh_from_daily.py <xname>` 算 factor_ic_vec(需sqlite_vec)
     3. **R4 检索**: 调 R4 Contract `search_behavior_neighbors`:
        ```
        Bash: /home/lgao/quant-venv/bin/python core/retrieval/r4_search_behavior_neighbors.py \
              --xname <xname> --symbol <sym> --horizon <hz>
        ```
        读 R4 返回:
        - `collision_verdict`: COLLIDES(|pearson|>0.7) | WEAK_CORRELATION(>0.4) | INDEPENDENT
        - `strongest_neighbor` + `strongest_pearson`
        - `residual_after_orthogonalization`: <0.5=冗余零新息
     - **硬否决**: R4 `COLLIDES` → 冗余; `residual_after_orthogonalization < 0.5` → 零新息

   - **补充检查(restest 通过但 R4 撞族)**: restest 说 X 空间独立, 但 R4 说 IC 行为 pearson>0.7 → 更隐蔽的"预测行为冗余"(X 独立但预测同涨同跌), key_weaknesses 注明, 倾向 fail。

   5. 【口径切换原料】查 `factor_ic_vec_meta` 主场景的 icir/mean_ic/std_ic(用 CLI,不要手写 SQL):
        ```
        Bash: /home/lgao/quant-venv/bin/python core/tools/factor_ic_vec_query.py meta --xname <xname>
        ```
        返回 JSON 数组,取主场景(symbol=SHFE-AG)的 icir/mean_ic。
   - **路径 A(辅,因子内部一致性,非库间冗余)**:`csv_ic_xcorr.md` 是**该因子自身**的 X↔X 矩阵(5品种×2horizon 互相关),**查不出与库内因子的冗余**——`find_redundant` 只会匹配到自身的不同场景(如 AG main↔AG@1)。仅作泛化/对齐敏感性参考,**不作库间冗余硬否决**。
     - Bash `python3 core/tools/csv_ic_adapter.py find_redundant <xcorr_file> <当前xname> --threshold 0.6`,结果只写入 `key_weaknesses`/`key_strengths` 描述内部一致性(如"AG main↔@1 反号=对齐敏感"),不触发否决。
   - **回退(无 csv_ic_ts — 真旧平台)**:`factor_ic_refresh {xname}` 走 dailyX,**dailyX 现已无数据,常 ok:false,直接跳过**;verdict 照常,`key_weaknesses` 注"库间 IC 冗余未检(无 daily_ts/dailyX)"
5. **定 verdict + 入库(commit)**:按"判定核心"双轨(过关闸门:忠实+预测力双闸门+可交易+无反转;过闸门后冗余度首要)定**最终 verdict**(pass/fail),调 `persist_factor {run_id, factor_index, mode: "commit", verdict: <最终verdict>}` —— 写 eval/lesson/定 status(draft→evaluated/dead_end)、假设 `support_score` 全量重算。**一次定,无初判/改判**。
6. **落盘**:`run_save {run_id, patch: {"factors.<i>.verdict": <最终verdict>, "factors.<i>.persisted": <persist_factor 返回值>}}`

> IC 冗余比 brainstorm 阶段的 formula 文本语义查重更准——能抓"公式不同但预测行为同涨同跌"的真冗余,对应第三维正交阈值 |pearson|<0.6。

### 输出格式

严格 JSON,无其他文字:

```json
{
  "xname": "<FACTOR_NAME>",
  "verdict": "pass 或 fail",
  "key_strengths": ["强项 1(含具体数字)", "强项 2"],
  "key_weaknesses": ["弱项 1(含具体数字)", "弱项 2"],
  "suggested_iteration": "如果下次重做这个方向,应该尝试什么调整(换 Y horizon / 换品种 / 调窗口)",
  "iterable": "true/false — 本因子的 suggested_iteration 是否值得接续(pass=true;dead_end 有换维度重试价值=true;dead_end 方向无救=false,走 dead_end lesson 避雷)"
}
```

---

## 迭代管道（精进 + 避雷）

verdict 定后、**persist_factor 之后**执行（open/realize 都要求因子已入 factors 表，外键约束）。分两种情况：

### A. 当前因子是"接续来的"（`state.factors[i].suggestion_id` 非空）→ realize 归档

接续候选 B 跑完、persist_factor 成功（B 已入库）后，归档当初那条 suggestion：

1. 取源因子 A 的 ICIR：`factor_detail {xname: state.factors[i].iterates_from}` → `.factor.latest_icir`
2. 当前因子 B 的 ICIR：`factor_detail {xname: <B.name>}` → `.factor.latest_icir`（B 刚入库，复查最稳）
3. `icir_delta = B.latest_icir - A.latest_icir`
4. 调：
   ```
   iteration_realize {
     suggestion_id: state.factors[i].suggestion_id,
     to_xname: <当前因子 B 的 xname>,
     icir_delta: <B.icir - A.icir>
   }
   ```
   outcome（improved/declined/neutral）由 icir_delta 自动推导。演进链 A→B 就此落定。

### B. 为当前因子的 suggested_iteration 开新建议（open）

判 `iterable`（决定开不开 suggestion）：

| verdict | suggested_iteration 性质 | iterable | 动作 |
|---|---|---|---|
| pass | "换 horizon/窗口可能更强"类精进 | true | `iteration_open` 开建议 |
| fail/dead_end | "换品种/换维度重试"且 `\|latest_icir\|≥0.05` | true | `iteration_open` 开建议（显式重试，避免下次换皮盲撞）|
| fail/dead_end | 方向本身无救（`\|latest_icir\|<0.05` 或机制判定无效） | **false** | **不开 suggestion**；persist_factor 已自动写 dead_end lesson，brainstorm 的 `factor_recent_lessons` 会检索到 → 避雷 |

iterable=true 时调：
```
iteration_open {
  from_xname: <当前因子>,
  change_note: <suggested_iteration 核心,如 "换 60s horizon">,
  reason: <基于 7 维数据的依据,一句话>,
  iterable: true,
  idea_id: state.idea_id
}
```
同 (from, change) 已 open → 幂等返回已有 id，不重开。

### 容错

- realize/open 任何一步失败 → 记 retry_trace，**不阻塞 verdict 落库**（verdict 优先，迭代是增益）
- persist_factor 返回 `ok:false`（因子没入库）→ 跳过整个迭代段（A/B 都做不了，外键不满足）

---

## 三、容错

- 评估数据缺失 → `verdict=fail`,`key_weaknesses` 写"评估数据缺失",继续
- `persist_factor` 返回 `{ok: false, error}` → 原样写入 `persisted` 字段(不要自己编 error 文案,工具会给出真实原因);verdict 仍写 run_save
- MCP 连续失败 3 次 → `run_save {status: "paused"}` 然后停止
