#!/usr/bin/env python3
"""Case C — A1 path sufficiency + A2 matched-summary pair + day/block + KS。

坐标:run_sign / run_len / agg_mag(op3 保留+summary)/ recent_mag(H1) / early_late_ratio(H2) / vol(控制)
靶心:同 summary(run_sign/run_len/agg_mag/vol)但形成过程(early_late_ratio)不同,是否行为不同

A1: M0 = Y~f(run_sign, run_len, agg_mag, vol)(联合桶)
    M1 = M0 + 桶内 (recent_mag + early_late_ratio) 线性
    滚动 OOS,Δ_OOS = MSE0-MSE1 > 0 跨块稳
A2(C 核心): matched-summary pair
    固定 run_sign + run_len(精确) + agg_mag 窄带 + vol 层,early_late_ratio 切 P90/P10
    比 Y 分布(day-level 117 effects + block bootstrap CI + KS 检验)
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
PROBE = "probe_T-C"


def load():
    df = xycache.load_days(PROBE, None)
    cols = [c for c in df.columns if c.startswith("X.") and "SHFE-AG@" in c]
    def _pick(kw):
        cs = [c for c in cols if kw in c and "@1@" not in c]
        return cs[0] if cs else None
    d = pd.DataFrame({
        "t": df["receive_time"].values,
        "sign": df[_pick("run_sign_coord")].values,
        "runlen": df[_pick("run_len_coord")].values,
        "aggmag": df[_pick("agg_mag_coord")].values,
        "recent": df[_pick("recent_mag_coord")].values,
        "elratio": df[_pick("early_late_ratio_coord")].values,
        "vol": df[_pick("vol_coord_c")].values,
        "y": df["Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"].values,
    })
    valid = ~((d["sign"] == 0) & (d["runlen"] == 0) & (d["aggmag"] == 0) & (d["vol"] == 0))
    d = d[valid].sort_values("t").reset_index(drop=True)
    d["day"] = (d["t"] // (86400 * 10**9)).astype(int)
    return d


# ================= A1: path sufficiency(滚动 OOS)=================
def run_a1(d, n_agg_bins=5, n_vol_bins=3, n_folds=5):
    """M0 = 桶均值(sign×runlen_bin×agg_bin×vol_bin),M1 = M0 + 桶内 recent/elratio 线性。"""
    d = d.copy()
    d["sign_i"] = np.sign(d["sign"]).astype(int)
    d["rl_bin"] = pd.qcut(d["runlen"].rank(method="first"), 4, labels=False).astype(int)
    d["agg_b"] = pd.qcut(d["aggmag"].rank(method="first"), n_agg_bins, labels=False).astype(int)
    d["vol_b"] = pd.qcut(d["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)

    days = np.sort(d["day"].unique())
    n_days = len(days)
    block = n_days // (n_folds + 1)
    folds = []
    for k in range(1, n_folds + 1):
        tr = d[d["day"].isin(days[: k * block])]
        te = d[d["day"].isin(days[k * block : (k + 1) * block])]
        if len(te) < 1000:
            continue
        tr["bk"] = tr["sign_i"].astype(str) + "_" + tr["rl_bin"].astype(str) + "_" + tr["agg_b"].astype(str) + "_" + tr["vol_b"].astype(str)
        te["bk"] = te["sign_i"].astype(str) + "_" + te["rl_bin"].astype(str) + "_" + te["agg_b"].astype(str) + "_" + te["vol_b"].astype(str)
        m0 = tr.groupby("bk")["y"].mean()
        pred0 = te["bk"].map(m0).fillna(tr["y"].mean()).values
        mse0 = float(np.mean((te["y"] - pred0) ** 2))
        # M1: 桶内二元 OLS y = a + b*recent + c*elratio
        coef = {}
        for bk, g in tr.groupby("bk"):
            if len(g) < 30:
                continue
            X = np.column_stack([np.ones(len(g)), g["recent"].values, g["elratio"].values])
            try:
                beta, *_ = np.linalg.lstsq(X, g["y"].values, rcond=None)
                coef[bk] = beta
            except Exception:
                continue
        pred1 = np.full(len(te), tr["y"].mean())
        for bk, beta in coef.items():
            mask = te["bk"] == bk
            X = np.column_stack([np.ones(mask.sum()), te["recent"].values[mask], te["elratio"].values[mask]])
            pred1[mask] = X @ beta
        mse1 = float(np.mean((te["y"] - pred1) ** 2))
        folds.append({"fold": k, "train_days": int(len(tr["day"].unique())), "test_days": int(len(te["day"].unique())),
                      "n_test": int(len(te)), "mse0": mse0, "mse1": mse1,
                      "delta_oos": mse0 - mse1, "delta_pct": (mse0 - mse1) / mse0 * 100})
    deltas = [f["delta_oos"] for f in folds]
    return {
        "test": "A1_path_conditional_sufficiency",
        "model": "M0:Y~f(sign,runlen,agg_mag,vol) vs M1:M0+桶内(recent_mag+early_late_ratio)线性",
        "folds": folds,
        "summary": {"n_folds": len(folds), "delta_median": float(np.median(deltas)),
                    "delta_all_positive": all(x > 0 for x in deltas), "delta_min": float(min(deltas)),
                    "verdict_hint": "PATH_INSUFFICIENT_AFTER_SUMMARY" if all(x > 0 for x in deltas) else "INCONCLUSIVE"},
    }


# ================= A2: matched-summary pair(C 核心)=================
def run_a2(d, runlen_range=(4, 8), n_vol_bins=3):
    """固定 run_sign + vol 层 + agg_mag 窄带(run_len 不精确匹配但报告平衡度),
    early_late_ratio P90(early_heavy) vs P10(late_heavy)。"""
    rng = np.random.default_rng(42)
    sub = d[(d["runlen"] >= runlen_range[0]) & (d["runlen"] <= runlen_range[1]) & (d["elratio"] != 1.0)].copy()
    if len(sub) < 5000:
        return {"n": int(len(sub)), "skipped": "run_len≥4 子集样本不足"}
    sub["vol_b"] = pd.qcut(sub["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)
    daily = {}
    all_hi_y, all_lo_y = [], []
    all_hi_rl, all_lo_rl = [], []  # runlen 平衡检查
    for day, g in sub.groupby("day"):
        eff = 0.0; cnt = 0
        for (sgn, vb), gg in g.groupby(["sign", "vol_b"]):
            if len(gg) < 50:
                continue
            lo_q, hi_q = gg["aggmag"].quantile([0.3, 0.7])
            gg_n = gg[(gg["aggmag"] >= lo_q) & (gg["aggmag"] <= hi_q)]
            if len(gg_n) < 30:
                continue
            el_lo, el_hi = gg_n["elratio"].quantile([0.1, 0.9])
            hi_grp = gg_n[gg_n["elratio"] >= el_hi]
            lo_grp = gg_n[gg_n["elratio"] <= el_lo]
            if len(hi_grp) < 5 or len(lo_grp) < 5:
                continue
            eff += hi_grp["y"].mean() - lo_grp["y"].mean(); cnt += 1
            all_hi_y.extend(hi_grp["y"].values); all_lo_y.extend(lo_grp["y"].values)
            all_hi_rl.extend(hi_grp["runlen"].values); all_lo_rl.extend(lo_grp["runlen"].values)
        if cnt:
            daily[day] = eff / cnt
    effs = np.array([v for v in daily.values() if not np.isnan(v)])
    if len(effs) < 10:
        return {"n": len(sub), "skipped": "有效匹配天数不足"}
    day_t = float(effs.mean() / (effs.std() / np.sqrt(len(effs))))
    n_blocks = len(effs) // 10
    if n_blocks >= 3:
        bs = []
        for _ in range(1000):
            idx = rng.choice(n_blocks, size=n_blocks, replace=True)
            sample = np.concatenate([effs[i * 10 : (i + 1) * 10] for i in idx])
            bs.append(sample.mean())
        ci = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    else:
        ci = [float(effs.mean()), float(effs.mean())]
    ks_stat = ks_p = None
    try:
        from scipy.stats import ks_2samp
        ks = ks_2samp(all_hi_y, all_lo_y)
        ks_stat, ks_p = float(ks.statistic), float(ks.pvalue)
    except Exception:
        pass
    # runlen 平衡(confounder 检查)
    rl_hi = np.mean(all_hi_rl) if all_hi_rl else 0
    rl_lo = np.mean(all_lo_rl) if all_lo_rl else 0
    rl_pooled_std = np.std(all_hi_rl + all_lo_rl) if (all_hi_rl or all_lo_rl) else 1.0
    rl_imbalance = abs(rl_hi - rl_lo) / (rl_pooled_std + 1e-9)
    return {
        "runlen_range": list(runlen_range), "n_sub": int(len(sub)), "n_days": int(len(effs)),
        "n_early_heavy": len(all_hi_y), "n_late_heavy": len(all_lo_y),
        "daily_effect_median": float(np.median(effs)),
        "positive_day_ratio": float((effs > 0).mean()),
        "day_t": round(day_t, 2),
        "block_bootstrap_ci": [round(ci[0], 5), round(ci[1], 5)],
        "ci_excludes_zero": ci[0] > 0 or ci[1] < 0,
        "ks_stat": round(ks_stat, 4) if ks_stat is not None else None,
        "ks_pvalue": ks_p,
        "ks_significant": ks_p is not None and ks_p < 0.05,
        "runlen_balance": {"early_heavy_mean": round(float(rl_hi), 3), "late_heavy_mean": round(float(rl_lo), 3),
                           "imbbalance_sigma": round(float(rl_imbalance), 3),
                           "balanced": bool(rl_imbalance < 0.25)},
    }


def main():
    d = load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a1 = run_a1(d)
    a2 = run_a2(d)
    out = {"n_total": len(d), "n_days": int(d["day"].nunique()),
           "runlen_dist": d["runlen"].value_counts().head(8).to_dict(),
           "A1": a1, "A2": a2}
    (OUT_DIR / "confirmation_C12.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
