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

因子评价不只看单一预测指标。按**三维度综合 + 一票否决硬关**评,区分因子是"找到不变结构"还是"换种方式过拟合"。所有指标来自平台/本地代码聚合的评估数据(非 LLM 自评)。

### 判定态度

- 单独评估此因子(不跟其他候选对比)
- **不只看 ICIR 阈值**:三维度综合,ICIR 只是第一维其一
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
- `faithful` → 进经验维度(下述三维度综合)。

**双轨本质**:忠实度(因子有没有验证假设)+ 经验(因子有没有效)。忠实度是假设验证的前提——不忠实则因子与假设无关,IC 高也是别的机制的功劳,假设未被验证。

### 第一维 · 预测能力(秩空间,弃 pearson)

因子在"形状/顺序"空间工作,衡量工具也必须是。

| 指标 | 判断标准 | 数据来源 |
|---|---|---|
| **秩 IC 的 ICIR/t 值**(首要) | 看 \|ICIR\|≥1.5 达标——**负 ICIR = 反向信号,反着用即有效,\|ICIR\| 大算强不算失败**(勿因负值判弱);t 值显著 + std 低 | screening(Spearman / ICIR / sign_match_rate) |
| **平稳性 + 差分**(新增) | ADF p<0.05 已平稳 → 无需差分;非平稳且 diff_improvement>0 → 该差分 | stationarity(adf_pvalue / need_differential / orig_ic / diff_ic / diff_improvement) |
| 显著性 | Welch t + p_value | zero |
| 分组单调性 | 5 组收益平滑严格单调 | 待补 |
| 多空盈亏比 | 胜率 40-60% 正常,盈亏比持续 >1(不被极端带飞) | 待补 |

**差分判定细则**:
- `is_stationary=true`(ADF p<0.05):因子日级平稳,不漂移,直接用原始信号 → key_strengths 写"因子平稳(ADF p={x}),无需差分"
- `is_stationary=false` 且 `diff_improvement>0`(差分后 pooled IC 升):非平稳但差分能提升 → key_weaknesses 写"因子非平稳(ADF p={x}),差分后 IC 改善{diff_improvement},建议用差分信号"
- `is_stationary=false` 且 `diff_improvement≤0`:非平稳且差分无效 → 倾向 fail(信号含漂移噪声,差分也救不了)

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
| 正交 | pairwise `\|pearson\|<0.7` **且** 残差 IC 强度不低(`factor_residual_ic_strength` 高=预测力多为新息,低=被库内线性解释=冗余) | IC 冗余 pearson + 残差 IC 强度(见"二、操作流程·查正交") |
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
4. **预测力下限**:主场景 `|screening.icir| < 0.5`(预测力极弱,正负皆然——稳定反向信号 |ICIR| 高不否决,只卡绝对值太低)且无救场 → fail
   - 救场(命中任一则**不否决**,进综合判断):变换族某变换 `|IC| ≥ 0.05`(transform_family.*,某形态有可用水准预测力),或某 horizon 实际 `|IC| ≥ 0.03`(长 horizon 有可用水准预测力)
   - 数据:`screening.icir` + `transform_family` + `factor_ic_daily`(按 horizon 的 IC);某项缺失则对应救场分支不计(不可得 = 不构成救场)
   - 注意:`factor_residual_ic_strength` 是新颖度(预测力不被库内线性解释的比例)**不是预测力绝对值**,不单独作救场——弱信号即使新颖也仍弱,该挂还挂
   - 说明:补这条是因为原 3 条否决没覆盖"预测力本身太弱"——防止 |ICIR| 极低(如 0.12)但忠实度/正交尚可的因子蒙混 pass。阈值 0.5 是"基本无信号"线(evaluated 强信号阈 1.5,1.0 有信号,0.5 以下噪声主导)

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
2. **忠实度审稿 + 初判**:
   - 先忠实度(有 argument_chain 时):派 reviewer-agent 忠实度模式(见第零维)。`unfaithful` → verdict=fail(一票否决),跳过初判。
   - 再初判(`faithful` 或无 argument_chain):按"一、判定核心"(三维度综合 + 否决前置)推理初步 verdict
3. **入库**:`persist_factor {run_id, factor_index, verdict}`(工具内部从 state.json 读 factor/factorFile/checkResult,无需拼装)
4. **查正交(第三维,check_done 必做)**:据冗余 refine verdict
   - 调 `factor_ic_refresh {xname}`:刷新 IC 向量入库(check_done 才有 dailyX 可算),同时产出 @1 因果 IC。**双重用途**:① 冗余检索向量(下步 correlate 用);② **对齐一致性核对**(见"判定态度·数据信任")——对比 feed IC(screening 的 icir)与 @1 因果 IC:符号一致且量级不离谱则对齐可信;符号反或背离(feed ICIR>2 但因果 ICIR<0.3)才诊断为"对齐不一致",`key_weaknesses` 写"feed IC{feed_icir} 与 @1 因果 IC{causal_icir} 对齐不一致"并倾向 fail。**容错**:`ok:false` 则跳过,verdict 照常,`key_weaknesses` 注明"ic 向量刷新失败,冗余/对齐未检"
   - 调 `factor_ic_correlate {target: xname}`:查库内行为冗余因子(按 `|pearson|` 排序)
   - 纳入 verdict:
     - `|pearson| ≥ 0.95`(几乎完全冗余,零增量)→ **verdict=fail 硬否决**(库内已有 IC 行为等价因子,留一个够,ICIR 再高也不放过——这是占名额不产新息)
     - `0.7 ≤ |pearson| < 0.95` → `key_weaknesses` 写"与 {factor} IC 行为冗余 pearson={x}({vs_scene}),增量有限",倾向 fail(需 key_strengths 有明确机制差异佐证才可不 fail,不再是"ICIR 高即可放过")
     - 最高 `|pearson| < 0.5` → `key_strengths` 写"与库内因子 IC 行为正交(最高 |pearson|={x}),增量空间大"
     - `0.5 ≤ |pearson| < 0.7` → 中性,`key_weaknesses` 提一句
   - 调 `factor_residual_ic_strength {target: xname}`(库内有 factor_ic_daily 时,补 pairwise 盲区):相对全库基底的残差比例——某因子 pairwise 都不高(和谁都不像)但合起来仍冗余时,pearson 抓不到,residual 能抓。判据:`factor_residual_ic_strength < 0.1` → **verdict=fail 硬否决**(预测力几乎全被库内线性解释,零新息);`< 0.4` → `key_weaknesses` 写"残差 IC 强度={x},预测力多被库内解释",倾向 fail;`> 0.7` → `key_strengths` 写"残差 IC 强度={x},预测力多为新息"。**容错**:库不足/无 factor_ic_daily → 脚本返回 strength=1.0(无区分力),`key_weaknesses` 注"残差 IC 未评估(库不足)",不据此判。
5. **落盘**:`run_save {run_id, patch: {"factors.<i>.verdict": <verdict>, "factors.<i>.persisted": <persist_factor 返回值>}}`

> IC 冗余比 brainstorm 阶段的 formula 文本语义查重更准——能抓"公式不同但预测行为同涨同跌"的真冗余,对应第三维正交阈值 |pearson|<0.7。

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
