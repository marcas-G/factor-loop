#!/usr/bin/env python3
"""Case B — A1 continuous sufficiency + A2 narrow matched + day/block。

坐标:sign_coord(±1)/cons_coord(一致率)/mag_coord(被压幅值)/vol_coord(活跃度 regime)
靶心:Y ⟂ M | R,C ?(符号表示 R + 一致率 C 固定后,幅值 M 是否仍携带行为信息)

A1: M0 = Y~f(sign, cons, vol)(允许非线性:联合桶均值)
    M1 = M0 + 桶内 mag 线性
    滚动时间块 OOS(断点 train 内定),Δ_OOS = MSE0-MSE1 > 0 且跨块稳
    → vol 进 M0 基线 = 防「幅值只是 volatility regime proxy」(Case B 硬性要求)
A2: 固定子集 sign=+1 ∧ cons 窄带(≈全一致),vol 层内,mag 中位切高低组
    比较 Y 分布;day-level 117 天 daily effects + block bootstrap CI
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
    ycol = "Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"
    d = pd.DataFrame({
        "t": df["receive_time"].values,
        "sign": df[[c for c in cols if "sign_coord" in c][0]].values,
        "cons": df[[c for c in cols if "cons_coord" in c][0]].values,
        "mag": df[[c for c in cols if "mag_coord" in c][0]].values,
        "vol": df[[c for c in cols if "vol_coord" in c][0]].values,
        "y": df[ycol].values,
    })
    valid = ~((d["sign"] == 0) & (d["cons"] == 0) & (d["mag"] == 0) & (d["vol"] == 0))
    d = d[valid].sort_values("t").reset_index(drop=True)
    d["day"] = (d["t"] // (86400 * 10**9)).astype(int)
    return d


# ================= A1: continuous sufficiency(滚动 OOS)=================
def run_a1(d, n_cons_bins=5, n_vol_bins=3, n_folds=5):
    """M0 = 桶均值(sign×cons 分位×vol 分位),M1 = M0 + 桶内 mag 线性。"""
    days = np.sort(d["day"].unique())
    n_days = len(days)
    block = n_days // (n_folds + 1)
    folds = []
    # sign 分 3 类,cons/vol 分位
    d = d.copy()
    d["cons_b"] = pd.qcut(d["cons"].rank(method="first"), n_cons_bins, labels=False).astype(int)
    d["vol_b"] = pd.qcut(d["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)
    d["sign_i"] = np.sign(d["sign"]).astype(int)

    for k in range(1, n_folds + 1):
        tr = d[d["day"].isin(days[: k * block])]
        te = d[d["day"].isin(days[k * block : (k + 1) * block])]
        if len(te) < 1000:
            continue
        # 桶键
        tr["bk"] = tr["sign_i"].astype(str) + "_" + tr["cons_b"].astype(str) + "_" + tr["vol_b"].astype(str)
        te["bk"] = te["sign_i"].astype(str) + "_" + te["cons_b"].astype(str) + "_" + te["vol_b"].astype(str)
        # M0: 桶均值
        m0 = tr.groupby("bk")["y"].mean()
        pred0 = te["bk"].map(m0).fillna(tr["y"].mean()).values
        mse0 = float(np.mean((te["y"] - pred0) ** 2))
        # M1: 桶内 mag 线性 y = a + b*mag
        coef = {}
        for bk, g in tr.groupby("bk"):
            if len(g) < 30:
                continue
            mm = g["mag"].values; yy = g["y"].values
            var = ((mm - mm.mean()) ** 2).sum()
            if var < 1e-12:
                continue
            b = ((mm - mm.mean()) * (yy - yy.mean())).sum() / var
            a = yy.mean() - b * mm.mean()
            coef[bk] = (a, b)
        pred1 = np.full(len(te), tr["y"].mean())
        for bk, (a, b) in coef.items():
            mask = te["bk"] == bk
            pred1[mask] = a + b * te["mag"].values[mask]
        mse1 = float(np.mean((te["y"] - pred1) ** 2))
        folds.append({
            "fold": k, "train_days": int(len(tr["day"].unique())), "test_days": int(len(te["day"].unique())),
            "n_test": int(len(te)), "mse0": mse0, "mse1": mse1,
            "delta_oos": mse0 - mse1, "delta_pct": (mse0 - mse1) / mse0 * 100,
        })
    deltas = [f["delta_oos"] for f in folds]
    return {
        "test": "A1_magnitude_conditional_sufficiency",
        "model": "M0:Y~f(sign,cons,vol)(联合桶均值,vol 进基线防 proxy) vs M1:M0+桶内mag线性",
        "folds": folds,
        "summary": {
            "n_folds": len(folds), "delta_median": float(np.median(deltas)),
            "delta_all_positive": all(x > 0 for x in deltas),
            "delta_min": float(min(deltas)),
            "verdict_hint": "MAGNITUDE_INSIGNIFICANT_AFTER_RC" if all(x > 0 for x in deltas) else "INCONCLUSIVE",
        },
    }


# ================= A2: narrow matched(day-level + block bootstrap)=================
def run_a2(d, cons_band=(0.60, 0.70), n_vol_bins=3):
    """固定 sign=+1 ∧ cons 窄带(≈全一致),vol 层内 mag 中位切高低组。"""
    rng = np.random.default_rng(42)
    sub = d[(d["sign"] > 0) & (d["cons"] >= cons_band[0]) & (d["cons"] <= cons_band[1])]
    if len(sub) < 5000:
        return {"band": cons_band, "n": int(len(sub)), "skipped": "固定子集样本不足"}
    sub = sub.copy()
    sub["vol_b"] = pd.qcut(sub["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)
    daily = {}
    for day, g in sub.groupby("day"):
        eff = 0.0; cnt = 0
        for vb, vg in g.groupby("vol_b"):
            med = vg["mag"].median()
            hi = vg[vg["mag"] > med]["y"].mean()
            lo = vg[vg["mag"] <= med]["y"].mean()
            if np.isnan(hi) or np.isnan(lo):
                continue  # 该层空组,跳过
            eff += hi - lo; cnt += 1
        if cnt:
            daily[day] = eff / cnt
    effs = np.array([v for v in daily.values() if not np.isnan(v)])
    if len(effs) < 2:
        return {"n": len(sub), "skipped": "有效天数不足"}
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
    return {
        "cons_band": cons_band, "n": int(len(sub)), "n_days": int(len(effs)),
        "daily_effect_median": float(np.median(effs)),
        "positive_day_ratio": float((effs > 0).mean()),
        "day_t": round(day_t, 2),
        "block_bootstrap_ci": [round(ci[0], 5), round(ci[1], 5)],
        "ci_excludes_zero": ci[0] > 0 or ci[1] < 0,
    }


def main():
    d = load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a1 = run_a1(d)
    a2 = run_a2(d)
    out = {"n_total": len(d), "n_days": int(d["day"].nunique()), "A1": a1, "A2": a2}
    (OUT_DIR / "confirmation_B12.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
