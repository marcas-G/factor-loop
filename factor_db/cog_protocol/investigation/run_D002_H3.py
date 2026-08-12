#!/usr/bin/env python3
"""D002-H3 补测 — 条件自相关(magnitude → 动力学 regime,非均值)。

H3(v0):固定 sign/c/w,按 |s| 量级分弱/强两组:
  - 变化的【不是】条件均值 E[Y|output](两组应接近)
  - 而是 Y 的 lag-1 自相关:弱窗口负(均值回归)/ 强窗口正(趋势)
  即"幅值对条件均值零影响、仅改变转换核(动力学)"

这是 D002 v1 漏测的维度(v1 只测 mag→E[Y] 均值增量 = H1/H2)。
critic 判 STRUCTURE(raw mag available 但 autocorrelation not represented)。
本 probe 验证:H3 是否数据支持。

数据:probe_T-B(已有,117 天,sign/cons/mag/vol/Y@h1)。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "factor_db"))

import numpy as np
import pandas as pd

from cog_protocol.investigation import xycache

OUT_DIR = ROOT / "logs" / "cog_protocol" / "investigation"
PROBE = "probe_T-B"


def load():
    df = xycache.load_days(PROBE, None)
    cols = [c for c in df.columns if c.startswith("X.") and "SHFE-AG@" in c]
    def _pick(kw):
        cs = [c for c in cols if kw in c and "@1@" not in c]
        return cs[0] if cs else None
    d = pd.DataFrame({
        "t": df["receive_time"].values,
        "sign": df[_pick("sign_coord")].values,
        "cons": df[_pick("cons_coord")].values,
        "mag": df[_pick("mag_coord")].values,
        "vol": df[_pick("vol_coord")].values,
        "y": df["Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"].values,
    })
    valid = ~((d["sign"] == 0) & (d["cons"] == 0) & (d["mag"] == 0) & (d["vol"] == 0))
    d = d[valid].sort_values("t").reset_index(drop=True)
    d["day"] = (d["t"] // (86400 * 10**9)).astype(int)
    return d


def _autocorr(y):
    """lag-1 pearson autocorrelation(时间序)。样本<30 返回 nan。"""
    if len(y) < 30:
        return np.nan
    a = y[:-1]; b = y[1:]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _sign_persistence(y):
    """sign(Y_t)==sign(Y_{t-1}) 比率(高=趋势持续,低=均值回归翻转)。"""
    if len(y) < 30:
        return np.nan
    s = np.sign(y)
    return float((s[:-1] == s[1:]).mean())


def run(d, cons_band=(0.60, 0.70), n_vol_bins=3):
    rng = np.random.default_rng(42)
    sub = d[(d["sign"] > 0) & (d["cons"] >= cons_band[0]) & (d["cons"] <= cons_band[1])].copy()
    if len(sub) < 5000:
        return {"n": int(len(sub)), "skipped": "固定子集样本不足"}
    sub["vol_b"] = pd.qcut(sub["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)

    daily = []
    for day, g in sub.groupby("day"):
        ac_diff = 0.0; sp_diff = 0.0; mu_diff = 0.0; cnt = 0
        for vb, vg in g.groupby("vol_b"):
            if len(vg) < 60:
                continue
            vg = vg.sort_values("t")
            med = vg["mag"].median()
            hi = vg[vg["mag"] > med]["y"].values
            lo = vg[vg["mag"] <= med]["y"].values
            ac_hi, ac_lo = _autocorr(hi), _autocorr(lo)
            sp_hi, sp_lo = _sign_persistence(hi), _sign_persistence(lo)
            if np.isnan(ac_hi) or np.isnan(ac_lo):
                continue
            ac_diff += ac_hi - ac_lo
            sp_diff += sp_hi - sp_lo
            mu_diff += hi.mean() - lo.mean()
            cnt += 1
        if cnt:
            daily.append({"day": day, "ac_diff": ac_diff / cnt, "sp_diff": sp_diff / cnt,
                          "mu_diff": mu_diff / cnt})
    if len(daily) < 10:
        return {"n": len(sub), "skipped": "有效天数不足"}

    ac = np.array([x["ac_diff"] for x in daily])
    sp = np.array([x["sp_diff"] for x in daily])
    mu = np.array([x["mu_diff"] for x in daily])

    def _stats(arr):
        n_blocks = len(arr) // 10
        if n_blocks >= 3:
            bs = []
            for _ in range(1000):
                idx = rng.choice(n_blocks, size=n_blocks, replace=True)
                sample = np.concatenate([arr[i * 10 : (i + 1) * 10] for i in idx])
                bs.append(sample.mean())
            ci = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
        else:
            ci = [float(arr.mean()), float(arr.mean())]
        return {
            "median": float(np.median(arr)), "mean": float(arr.mean()),
            "positive_day_ratio": float((arr > 0).mean()),
            "day_t": float(arr.mean() / (arr.std() / np.sqrt(len(arr)))),
            "block_ci": [round(ci[0], 5), round(ci[1], 5)],
            "ci_excludes_zero": ci[0] > 0 or ci[1] < 0,
        }

    return {
        "n_sub": int(len(sub)), "n_days": len(daily), "cons_band": list(cons_band),
        "H3_autocorr_diff_strong_minus_weak": _stats(ac),
        "sign_persistence_diff_strong_minus_weak": _stats(sp),
        "mean_diff_strong_minus_weak_CONTROL": _stats(mu),
        "H3_prediction": "强组 autocorr > 弱组(趋势 vs 均值回归),且均值差≈0(H3 独有:动力学变/均值不变)",
    }


def main():
    d = load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = run(d)
    res["n_total"] = len(d)
    (OUT_DIR / "confirmation_D002_H3.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
