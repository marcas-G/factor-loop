---
name: evaluate
description: 量化因子结果评估。触发 `/evaluate <run_id> <factor_index>` 或被 research-loop 嵌套调用。基于 7 维评估数据出 verdict（pass/fail）并写库。
---

# Evaluate — 量化因子结果评估

基于代码从平台产物聚合的 7 维评估数据（**不是 LLM 自评**），对单个因子做结果评估，调 MCP 持久化 verdict。

## 输入

- `run_id`：研究 run id
- `factor_index`：state.factors 数组下标
- 或直接给 factor 对象

需要从 state 读：
- `state.idea` — 本次研究 idea
- `state.factors[i].name` — 因子类名
- `state.factors[i].hypothesis` — 因子设计假设（brainstorm 阶段由 `intuition + diff_check + coord_usage` 拼接而成）
- `state.factors[i].evidence.seven_dim_summary` — 7 维评估数据 JSON
- `state.factors[i].factor_file` — .h 文件绝对路径
- `state.factors[i].last_rewrite` — retry 信息（可能为 null）
- `state.idea_id` — 关联的 idea id

## 7 维评估维度参考

- **factor_level**：平台对 N 个 X-Y 对的 decision 分布（KEEP/WATCH/REJECT）+ 最佳 score
- **seven_dim_best**：每个维度的最佳 X-Y 对指标
  - screening: IC / ICIR / Spearman / sign_match_rate
  - session_ic: 各交易时段 IC + std（std 越小越稳）
  - vol_regime: 波动率 5 分位 IC + sign_consistent
  - zero: Welch t 检验 + p_value
  - train_test: 训练/测试 IC 衰减
- **deep_best**：deep 分析最佳值（conditional_sharpe / cum_ret_pct / monthly_icir / daily_ic_tstat / daily_rank_ic / daily_icir / signal_instability_pct）。**daily rank ic 与 daily ic 均已做 per-horizon 尾盘截断防未来信息泄漏**（按 X 信号日分桶,丢弃距当日收盘不足 horizon 秒的尾盘 tick）;旧字段 rank_ic_max 为 pooled 全样本、仅旧 run 兼容
- **top_pairs**：按 score 排序的前 3 个 X-Y 对
- **failure_reasons**：平台失败原因统计（low_icir / weak_beta / vol_regime_unstable / no_zero_diff / bad_bucket_shape / weak_train_test / weak_ic）

## 评估原则

1. 单独评估此因子（不跟其他候选对比）
2. 综合多维度判断，不要只看 ICIR 阈值
3. 强假设：因子是否回应了 idea 的核心假设（看 hypothesis 是否在数据上验证）
4. 强证据：所有结论必须引用 7 维数据的具体数字
5. `verdict=pass`：因子值得入库（算子可借鉴，下次能迭代）
6. `verdict=fail`：方向已被否决（避免下次重写），但 `suggested_iteration` 留作未来参考
7. **IC 行为冗余**：check_done 因子必须查与库内因子的 IC 行为冗余（见下），`|pearson|≥0.7` 视为冗余、倾向 fail

## IC 行为冗余检查（check_done 因子必做，容错）

因子 check_done 后已有 IC 数据，查它和库内已有因子的**行为冗余**（IC 序列 Pearson）——对应 PRINCIPLES "与已有因子相关性 < 0.7"。比 brainstorm 阶段的 formula 文本语义查重更准（能抓"公式不同但预测行为同涨同跌"的真冗余）。

**执行顺序**：先基于 7 维推理初步 verdict → `persist_factor` 入库（`factor_ic_refresh` 需因子已在 factors 表）→ 本节 refresh+correlate → 据冗余 refine verdict → `run_save` 最终 verdict。

1. 调 `factor_ic_refresh {xname}`：刷新该因子 IC 向量入库（check_done 因子才有 dailyX 可算）。**容错**：返回 `ok:false`（下载/计算失败）则跳过冗余检查，verdict 照常出，`key_weaknesses` 注明"ic 向量刷新失败，冗余未检"。
2. 调 `factor_ic_correlate {target: xname}`：查库内行为冗余因子（按 `|pearson|` 排序）。
3. 结果纳入 verdict：
   - `|pearson| ≥ 0.7` → `key_weaknesses` 写"与 {factor} IC 行为冗余 pearson={x}（{vs_scene}），增量有限"，verdict 倾向 fail（除非其它维度极强）
   - 最高 `|pearson| < 0.5` → `key_strengths` 写"与库内因子 IC 行为正交（最高 |pearson|={x}），增量空间大"
   - `0.5 ≤ |pearson| < 0.7` → 中性，`key_weaknesses` 提一句即可

## 持久化（推理出 verdict 后必须做）

1. 调 `persist_factor`（工具内部从 state.json 读 factor/factorFile/checkResult，无需你拼装）：
   ```
   persist_factor {
     run_id,
     factor_index: i,
     verdict: <verdict>
   }
   ```
2. 调 `run_save`：
   ```
   run_save {
     run_id,
     patch: {
       "factors.<i>.verdict": <verdict>,
       "factors.<i>.persisted": <persist_factor 返回值>
     }
   }
   ```

## 输出格式

严格 JSON，无其他文字：

```json
{
  "xname": "<FACTOR_NAME>",
  "verdict": "pass 或 fail",
  "key_strengths": ["强项 1（含具体数字）", "强项 2"],
  "key_weaknesses": ["弱项 1（含具体数字）", "弱项 2"],
  "suggested_iteration": "如果下次重做这个方向，应该尝试什么调整（换 Y horizon / 换品种 / 调窗口）"
}
```

## 错误处理

- 7 维数据缺失 → `verdict=fail`，`key_weaknesses` 写"seven_dim 缺失"，继续
- `persist_factor` 返回 `{ok: false, error}` → 原样写入 `persisted` 字段（不要自己编 error 文案，工具会给出真实原因）；verdict 仍写 run_save
- MCP 连续失败 3 次 → `run_save {status: "paused"}` 然后停止
