# 数据补全任务

> 数据库全面审查(2026-07-16)后发现的数据缺口。每项独立,可分别执行。
> 补全后 quality_score / 知识图血缘全准。

## 总览

| # | 缺口 | 影响 | 工作量 | 优先级 |
|---|---|---|---|---|
| 1 | 33 个 factor_ic_daily | independence=0 保守,quality 独立性维不准 | 中(refresh) | ⭐⭐ |
| 2 | 29 个无 factor_evals | quality_score=NULL,不参与排序 | 大(重评)/可选 | ⭐(可选) |
| 3 | 5 个缺 core_metrics.train_test | quality 样本维用默认(不准) | 小(重评5个) | ⭐ |

---

## 1. 补 33 个 factor_ic_daily(independence 补全)⭐⭐

### 背景

`quality_score` 的独立性维度 `independence = residual_ic_strength`,依赖 `factor_ic_daily`(日级 IC 序列做岭回归残差)。33 个 evaluated 没 refresh 过 ic 向量 → residual 算不了 → independence=0(保守低估)。

### 33 个名单

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

### 前置确认(关键)

`refresh` 算 ic_daily 要 **dailyX 数据**(平台评估产物)。先确认在不在:

```bash
# 重新确认当前缺的(跑前可能变)
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
ev=set(r[0] for r in c.execute(\"SELECT xname FROM factors WHERE status='evaluated' AND quality_score IS NOT NULL\"))
has=set(r[0] for r in c.execute('SELECT DISTINCT factor_xname FROM factor_ic_daily'))
print('缺', len(ev-has), ':', sorted(ev-has))
"
# dailyX 在不在
ls -d /home/lgao/work/quant/factor-evaluate-tmp/ 2>/dev/null && echo "在" || echo "⚠ 不在"
```

- **dailyX 在** → 可补,执行步骤
- **dailyX 不在** → 补不了(要重跑 factor_check 平台评估)

### 步骤

```bash
cd /home/lgao/work/factor-autoloop
PY=/home/lgao/quant-venv/bin/python

# 逐个 refresh(脚本 --xname)
$PY -c "
import sqlite3
c=sqlite3.connect('factors.db')
ev=set(r[0] for r in c.execute(\"SELECT xname FROM factors WHERE status='evaluated' AND quality_score IS NOT NULL\"))
has=set(r[0] for r in c.execute('SELECT DISTINCT factor_xname FROM factor_ic_daily'))
print('\n'.join(sorted(ev-has)))
" | while read x; do
  [ -z "$x" ] && continue
  echo "=== refresh $x ==="
  $PY core/tools/refresh_factor_ic_vectors.py --xname "$x" 2>&1 | tail -2
done

# 重 re-rank
$PY core/tools/recompute_quality_scores.py
```

或 MCP(重启会话后): `mcp__quant-mcp__factor_ic_refresh {xname: "<name>"}` 逐个。

### 验证

```bash
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
n=c.execute('''SELECT COUNT(*) FROM factors WHERE status='evaluated' AND quality_score IS NOT NULL
               AND xname NOT IN (SELECT DISTINCT factor_xname FROM factor_ic_daily)''').fetchone()[0]
print('缺 ic_daily 的有效 quality 因子:', n, '(目标0)')
for r in c.execute(\"SELECT quality_grade,COUNT(*) FROM factors WHERE status='evaluated' AND quality_score IS NOT NULL GROUP BY quality_grade\"):
    print(f'  {r[0]}: {r[1]}')
"
```

期望:缺 ic_daily=0;有效 quality 因子 independence 都非 0。

---

## 2. 补 29 个无 factor_evals(quality 补全)⭐ 可选

### 背景

29 个 evaluated 因子**无 factor_evals 记录**(评估详情丢,但 latest_icir 有 -11~7,说明评估过)。这些因子 quality_score 已置 NULL(不参与排序,避免空数据误导)。

### 影响

这 29 个 quality_score=NULL,不进 A/B/C 排序。要参与需补 factor_evals。

### 名单(查当前)

```bash
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
for r in c.execute('''SELECT xname,round(latest_icir,2) FROM factors WHERE status='evaluated' 
                      AND xname NOT IN (SELECT DISTINCT factor_xname FROM factor_evals) ORDER BY latest_icir DESC'''):
    print(f'  {r[0]:32s} icir={r[1]}')
"
```

### 步骤(大工作量)

补 factor_evals 要**重跑 factor_check**(平台评估)。这 29 个是 2026-06-24 老因子。

```bash
# 重跑这 29 个的 factor_check(平台),补 eval 记录
# 具体: 对每个因子调 platform_check_factor → 产出 eval_metrics → 写 factor_evals
# (平台评估流程,参考 run-factor-agent)
```

### 验证

```bash
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
n=c.execute('''SELECT COUNT(*) FROM factors WHERE status='evaluated' 
               AND xname NOT IN (SELECT DISTINCT factor_xname FROM factor_evals)''').fetchone()[0]
print('无 eval 的 evaluated:', n, '(目标0)')
"
```

**⚠ 评估**:这是大工作量(29 个 × 平台评估)。如果这 29 个不重要(老因子/icir 差),**可接受 NULL**(不补),它们不影响新研究。建议**优先级低**。

---

## 3. 补 5 个缺 core_metrics.train_test(小)⭐

### 背景

5 个 factor_evals 缺 `core_metrics.train_test`(factor_check 没产)。quality 的样本维(防过拟合)用默认 0.3,不准。

### 名单

```
QuoteTiltAsymAccum, QuoteTiltDepthGradient, TurnoverTailSoftGateReversal,
TurnoverSurpriseTailReversal_s2000p2000r600k2000rr1e-3tt2g15dg50d999, TurnoverDepthRatioTailReversal
```

### 步骤

```bash
# 重跑这 5 个的 factor_check(平台) → 补 eval_metrics(含 train_test)
# 然后 re-rank
/home/lgao/quant-venv/bin/python core/tools/recompute_quality_scores.py
```

或**接受**(5 个样本维用默认,影响小)。

### 验证

```bash
/home/lgao/quant-venv/bin/python -c "
import sqlite3
c=sqlite3.connect('factors.db')
n=c.execute(\"SELECT COUNT(*) FROM factor_evals WHERE json_extract(eval_metrics,'$.core_metrics.train_test') IS NULL\").fetchone()[0]
print('缺 train_test:', n)
"
```

---

---

## 相关

- **quality_score 公式**: `core/db/db.py` `quality_score_from_parts`
- **re-rank 脚本**: `core/tools/recompute_quality_scores.py`
- **refresh 脚本**: `core/tools/refresh_factor_ic_vectors.py`(`--xname`)
- **审查**: 全面数据库审查 2026-07-16(schema v6 / 孤儿0 / 知识图血缘 / quality 一致性全过)
- **提交**: 7d93b09(quality 理想公式) / 7150857(本补全文档前身)
