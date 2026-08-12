#!/usr/bin/env python3
"""Case A 最终确认: A1 连续 sufficiency + A2 窄带匹配 + day/block robustness。

用户审结的三大离线确认(全用现有 417 万探针样本,不重提平台):

A1 — Continuous conditional sufficiency(滚动 OOS):
  M0: Y = f(P)     (P 的 20 分位桶哑变量,允许非线性)
  M1: Y = f(P, S)  (桶哑变量 + 桶内 S 线性)
  滚动时间块 OOS(训练=块1..k,测试=块k+1),断点在 train 上定(防泄漏)
  Δ_OOS = MSE0 - MSE1 > 0 且跨块稳定 → Y 不⟂ S|P → product-only 不充分

A2 — Narrow-caliper matched distributional counterexample:
  绝对窄带(如 P∈[0.15,0.25],宽~0.01)内按 S 中位切高/低两组,
  同 P 下 S 高⟺G 低 = decomposition 不同;
  比较两组 Y 的行为分布(E[Y] 差 + hit 差);
  day-level:逐天窄带内 S 高低 Y 差 → 117 daily effects
    → median / positive-day ratio / day t / block bootstrap(10 天块)CI

判定: A1 Δ_OOS>0 跨块稳 + A2 效应方向一致 day t>2 + CI 不含 0
      → 晋升 REPRESENTATION_FAILURE_SUPPORTED_ONCE / SUPPORTED_DISTINCTION
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


def load():
    df = xycache.load_days("probe_T-A", None)
    sig = df["X.SHFE-AG@sig_coord"].values
    gate = df["X.SHFE-AG@gate_coord"].values
    prod = df["X.SHFE-AG@prod_coord"].values
    y = df["Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"].values
    t = df["receive_time"].values
    valid = ~((sig == 0) & (gate == 0) & (prod == 0))
    d = pd.DataFrame({
        "S": sig[valid], "G": gate[valid], "P": prod[valid], "y": y[valid], "t": t[valid],
    }).sort_values("t").reset_index(drop=True)
    d["day"] = (d["t"] // (86400 * 10**9)).astype(int)
    return d


# ================= A1: continuous sufficiency(滚动 OOS)=================
def run_a1(d, n_bins=20, n_folds=5):
    """滚动时间块:M0(Y~f(P)) vs M1(Y~f(P,S)),断点 train 内定。"""
    days = np.sort(d["day"].unique())
    n_days = len(days)
    block = n_days // (n_folds + 1)  # 每块天数
    folds = []
    for k in range(1, n_folds + 1):
        train_days = days[: k * block]
        test_days = days[k * block : (k + 1) * block]
        tr = d[d["day"].isin(train_days)]
        te = d[d["day"].isin(test_days)]
        if len(te) < 1000:
            continue
        # 断点在 train 上定
        edges = np.quantile(tr["P"], np.linspace(0, 1, n_bins + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        tr_bin = np.clip(np.searchsorted(edges, tr["P"]) - 1, 0, n_bins - 1)
        te_bin = np.clip(np.searchsorted(edges, te["P"]) - 1, 0, n_bins - 1)
        # M0: 每桶均值(非参数 f(P))
        bin_mean = np.zeros(n_bins)
        for b in range(n_bins):
            m = tr_bin == b
            bin_mean[b] = tr["y"][m].mean() if m.sum() else 0.0
        pred0 = bin_mean[te_bin]
        mse0 = float(np.mean((te["y"] - pred0) ** 2))
        # M1: 桶内 S 线性 y = a_b + b_b * S(每个桶独立 OLS)
        a = np.zeros(n_bins); bcoef = np.zeros(n_bins)
        for bb in range(n_bins):
            m = tr_bin == bb
            ss = tr["S"][m].values; yy = tr["y"][m].values
            if len(ss) < 50:
                continue
            s_mean = ss.mean(); s_var = ((ss - s_mean) ** 2).sum()
            if s_var < 1e-12:
                continue
            bcoef[bb] = ((ss - s_mean) * (yy - yy.mean())).sum() / s_var
            a[bb] = yy.mean() - bcoef[bb] * s_mean
        pred1 = a[te_bin] + bcoef[te_bin] * te["S"].values
        mse1 = float(np.mean((te["y"] - pred1) ** 2))
        folds.append({
            "fold": k, "train_days": int(len(train_days)), "test_days": int(len(test_days)),
            "n_test": int(len(te)),
            "mse0": mse0, "mse1": mse1, "delta_oos": mse0 - mse1,
            "delta_pct": (mse0 - mse1) / mse0 * 100,
        })
    deltas = [f["delta_oos"] for f in folds]
    return {
        "test": "A1_continuous_sufficiency",
        "model": "M0:Y~f(P)(20桶) vs M1:Y~f(P)+桶内S线性;滚动块OOS,断点train内定",
        "folds": folds,
        "summary": {
            "n_folds": len(folds),
            "delta_median": float(np.median(deltas)),
            "delta_all_positive": all(x > 0 for x in deltas),
            "delta_min": float(min(deltas)),
            "verdict_hint": "PRODUCT_INSUFFICIENT" if all(x > 0 for x in deltas) else "INCONCLUSIVE",
        },
    }


# ================= A2: narrow-caliper matched(day-level + block bootstrap)=================
def run_a2(d, bands=((-0.25, -0.15), (0.15, 0.25), (0.35, 0.45))):
    """绝对窄带内 S 中位切高低组,比较 Y 分布;day-level + block bootstrap。"""
    rng = np.random.default_rng(42)
    results = []
    for lo, hi in bands:
        sub = d[(d["P"] > lo) & (d["P"] < hi)]
        if len(sub) < 5000:
            results.append({"band": (lo, hi), "n": int(len(sub)), "skipped": "样本不足"})
            continue
        # 带内残余 P 混杂控制:再按 P 中位 split 后合并(双平衡)
        sub["p_half"] = sub["P"] > sub["P"].median()
        # 每 P 半区内按 S 中位切高低
        daily = {}
        for day, g in sub.groupby("day"):
            eff = 0.0; cnt = 0
            for ph, phg in g.groupby("p_half"):
                med_s = phg["S"].median()
                s_hi = phg[phg["S"] > med_s]["y"].mean()
                s_lo = phg[phg["S"] <= med_s]["y"].mean()
                eff += (s_hi - s_lo); cnt += 1
            if cnt:
                daily[day] = eff / cnt
        effs = np.array(list(daily.values()))
        day_t = float(effs.mean() / (effs.std() / np.sqrt(len(effs)))) if len(effs) > 1 else 0.0
        # block bootstrap(10 天块,1000 次)
        n_blocks = len(effs) // 10
        if n_blocks >= 3:
            bs = []
            for _ in range(1000):
                idx = rng.choice(n_blocks, size=n_blocks, replace=True)
                sample = np.concatenate([effs[i * 10 : (i + 1) * 10] for i in idx])
                bs.append(sample.mean())
            ci_lo, ci_hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        else:
            ci_lo = ci_hi = float(effs.mean())
        results.append({
            "band": (lo, hi),
            "n": int(len(sub)),
            "n_days": int(len(effs)),
            "daily_effect_median": float(np.median(effs)),
            "positive_day_ratio": float((effs > 0).mean()),
            "day_t": round(day_t, 2),
            "block_bootstrap_ci": [round(ci_lo, 5), round(ci_hi, 5)],
            "ci_excludes_zero": ci_lo > 0 or ci_hi < 0,
        })
    return {"test": "A2_narrow_caliper_matched", "bands": results}


def main():
    d = load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a1 = run_a1(d)
    a2 = run_a2(d)
    out = {"n_total": len(d), "n_days": int(d["day"].nunique()), "A1": a1, "A2": a2}
    (OUT_DIR / "confirmation_A12.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
