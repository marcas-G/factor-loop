"""跨品种 lead-lag 观测。

AG 收益 vs CU 收益的 lag 互相关(谁领先谁)。
反常:非对称传导(一边强领先另一边)或反向传导。
不依赖 Y 标签(只有 AG 有 Y),纯用两品种 mid 收益的互相关。
"""
from __future__ import annotations
import argparse
import json
from observe_common import *


def observe(days, lookback_lags):
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    need = ["receive_time", mid_col("SHFE-AG"), mid_col("SHFE-CU")]
    lag_corrs = {lag: [] for lag in lookback_lags}
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need)
        if not all(c in df.columns for c in need):
            continue
        r_ag = df[mid_col("SHFE-AG")].astype(np.float64).diff().values
        r_cu = df[mid_col("SHFE-CU")].astype(np.float64).diff().values
        n = min(len(r_ag), len(r_cu))
        for lag in lookback_lags:
            # corr(r_AG[t], r_CU[t-lag]): lag>0 → AG 领先 CU(lag 前 AG 预测 CU)
            #                            lag<0 → CU 领先 AG
            if lag >= 0:
                a, b = r_ag[:n - lag], r_cu[lag:n]
            else:
                a, b = r_ag[-lag:n], r_cu[:n + lag]
            m = np.isfinite(a) & np.isfinite(b)
            if int(m.sum()) > 200:
                lag_corrs[lag].append(float(np.corrcoef(a[m], b[m])[0, 1]))
    by_lag = {}
    for lag in lookback_lags:
        a = agg(lag_corrs[lag])
        if a:
            by_lag[lag] = a["mean"]
    if not by_lag:
        return {"error": "数据不足(CU 缺?)"}
    # lag0 = 同步相关; lag>0 = AG领先; lag<0 = CU领先
    lag0 = by_lag.get(0, 0)
    ag_lead = by_lag.get(2, 0)  # AG 领先 2 快照(1s)
    cu_lead = by_lag.get(-2, 0)
    # 反常:非对称(一边领先显著,另一边不)
    se = 1.96 / np.sqrt(35000)
    ag_strong = abs(ag_lead) > se and abs(ag_lead) > abs(cu_lead) * 1.5
    cu_strong = abs(cu_lead) > se and abs(cu_lead) > abs(ag_lead) * 1.5
    asym_lead = ag_strong or cu_strong
    return {
        "observation": "cross_symbol_lead_lag",
        "n_days": len(files),
        "sync_corr_lag0": lag0,
        "ag_lead_2step": ag_lead,
        "cu_lead_2step": cu_lead,
        "by_lag": {str(k): v for k, v in by_lag.items()},
        "asymmetric_lead": bool(asym_lead),
        "leader": "AG" if ag_strong else ("CU" if cu_strong else "对称/无"),
        "summary": (
            f"AG↔CU 同步={lag0:+.3f} AG领先2步={ag_lead:+.3f} CU领先2步={cu_lead:+.3f}; "
            f"{'非对称传导(' + ('AG领先★' if ag_strong else 'CU领先★') + ')' if asym_lead else '对称传导'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--lags", default="-5,-2,-1,0,1,2,5")
    a = p.parse_args()
    lags = [int(x) for x in a.lags.split(",")]
    print(json.dumps(observe(a.days, lags), ensure_ascii=False, indent=2))
