# 任务:补 33 个 evaluated 的 factor_ic_daily(让 quality_score 全准)

> **状态:待办**(空闲时执行)
> **来源**:quality_score 理想公式落地(7d93b09)的遗留——33 个 evaluated 缺 ic_daily → independence=0 保守低估

---

## 背景

`quality_score`(多指标聚合分)的独立性维度:
```
independence = residual_ic_strength   ← 依赖 factor_ic_daily(日级 IC 序列做岭回归残差)
```

当前 73 个 evaluated 里 **33 个没有 factor_ic_daily**(没 refresh 过 ic 向量)→ residual 算不了 → independence=0(保守)。

**影响**:这 33 个的 quality_score 偏低(独立性维=0 拉低),grade 可能虚降。它们未必冗余,只是没数据算 independence。

补全后,73 个 independence 都准,quality_score 完全可信。

## 33 个待补名单

```
BHHI, BPDiff, BPDiffSkew, BPSecDiff, BSE, BT, BTDiff, BTDiffSkew,
BreachImbalanceAutocor_w60, BreachPressureDivergence_w30, CascadeVelocityRegime,
DirectionalBreachImbalance_w60, KeyPushActiveAddNetFlow, MF_cv_w600,
MoneyFlow2PriceAlpha_w21, MoneyFlowDivergenceFactor, PVCor_Raw_w120,
RetailAddCancelStormDir, RetailOIChaseMom, SpreadDeltaFactor, SpreadSecDeltaFactor,
TCI_Trans, ThinBookCancelFastDecay_l5_d0.8_s100, ThinBookCancelPressure_l5_d0.9_s100,
ThinBookCancelScale50_l5_d0.9_s50, ThinBookCancelSquare_l5_d0.9_s100,
TimeSeriesVolWeakPointDetector_l5, TimeSeriesWeakPointDetector_l5, TradeRunVolAccel2,
VolBurstFleeAsymSoftGate, WeakPointDetector_l5, bookEntropyDiffRateImbalance, bookEntropyDiffRateSkew
```

---

## 前置确认(关键,决定能否补)

`factor_ic_refresh` 算 ic_daily 要 **dailyX 数据**(平台评估产物)。先确认在不在:

```bash
# 1. 重新确认当前缺的(可能有变化)
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
ev=set(r[0] for r in c.execute(\"SELECT xname FROM factors WHERE status='evaluated' AND deprecated_at IS NULL\"))
has=set(r[0] for r in c.execute('SELECT DISTINCT factor_xname FROM factor_ic_daily'))
print('缺', len(ev-has), ':', sorted(ev-has))
"

# 2. 确认 dailyX 数据在(refresh 的输入)
ls -d /home/lgao/work/quant/factor-evaluate-tmp/ 2>/dev/null && echo "在" || echo "⚠ 不在(补不了)"
```

- **dailyX 在** → 可补,执行下面步骤
- **dailyX 不在** → 补不了(要重跑 factor_check 平台评估,大工作量,放弃这 33 个或重评估)

---

## 步骤

### 1. refresh 33 个的 factor_ic_daily

脚本(逐个,参数 `--xname`):

```bash
cd /home/lgao/work/factor-autoloop
PY=/home/lgao/quant-venv/bin/python

# 拿当前缺的名单
MISS=$($PY -c "
import sqlite3
c=sqlite3.connect('factors.db')
ev=set(r[0] for r in c.execute(\"SELECT xname FROM factors WHERE status='evaluated' AND deprecated_at IS NULL\"))
has=set(r[0] for r in c.execute('SELECT DISTINCT factor_xname FROM factor_ic_daily'))
print('\n'.join(sorted(ev-has)))
")

# 逐个 refresh
echo "$MISS" | while read x; do
  [ -z "$x" ] && continue
  echo "=== refresh $x ==="
  $PY factor_db/refresh_factor_ic_vectors.py --xname "$x" 2>&1 | tail -2
done
```

或用 MCP(重启会话后,新 server): `mcp__quant-mcp__factor_ic_refresh {xname: "<name>"}` 逐个调。

### 2. 重 re-rank(用理想公式重算 quality_score)

```bash
/home/lgao/quant-venv/bin/python factor_db/recompute_quality_scores.py
```

### 3. 验证

```bash
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
n_noic=c.execute('''SELECT COUNT(*) FROM factors WHERE status='evaluated' AND deprecated_at IS NULL
                    AND xname NOT IN (SELECT DISTINCT factor_xname FROM factor_ic_daily)''').fetchone()[0]
print(f'缺 ic_daily 的 evaluated: {n_noic}  (目标 0)')
for r in c.execute(\"SELECT quality_grade, COUNT(*) FROM factors WHERE status='evaluated' GROUP BY quality_grade\"):
    print(f'  {r[0]}: {r[1]}')
"
```

**期望**:缺 ic_daily=0;73 个 independence 都非 0;grade 分布可能变(33 个补准后,真实独立/冗余的升降)。

---

## 可能问题

| 问题 | 处理 |
|---|---|
| **dailyX 不在**(评估产物清理了) | 补不了,放弃这 33 个或重跑 factor_check(平台,大工作量) |
| **refresh 失败**(某因子评估数据异常) | 跳过该因子,记日志,继续下一个 |
| **residual 仍 None**(ic_daily 有但 residual 算不出,基底问题) | ind=0 保留,quality_score 用保守值 |

---

## 相关

- **quality_score 公式**: `factor_db/db.py` `quality_score_from_parts`(独立性 + 样本train_test + 时间 + regime)
- **re-rank 脚本**: `factor_db/recompute_quality_scores.py`
- **refresh 脚本**: `factor_db/refresh_factor_ic_vectors.py`(`--xname`)
- **落地提交**: `7d93b09`(quality_score 理想公式 + v6 字段)
