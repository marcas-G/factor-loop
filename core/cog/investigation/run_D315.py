#!/usr/bin/env python3
"""id=315 v1 — 对称化过程相态(STRUCTURE 候选验证)。

靶心:当前表示保留 sym_inst(|sym|-|anti| 瞬时),critic 判丢了"过程相态动态"
A1: M0=f(dir, sym_inst, vol) vs M1=M0+sym_proc(sym窗口均值,STANDARD基线)+coupl_proc(符号耦合率,STRUCTURE候选)
   - sym_proc 有增量、coupl_proc 无 → STANDARD(窗口聚合够,critic 过判)
   - coupl_proc 有独立增量(超 sym_proc)→ STRUCTURE(过程动力学)
A2: matched(dir=+1, sym_inst 窄带, vol 层) — 同瞬时对称化但过程不同,coupl_proc 高低组比 Y
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from core.cog.investigation import xycache

OUT_DIR = ROOT / "logs" / "cog_protocol" / "investigation"
PROBE = "probe_T-D"


def load():
    df = xycache.load_days(PROBE, None)
    cols = [c for c in df.columns if c.startswith("X.") and "SHFE-AG@" in c]
    def p(k):
        cs = [c for c in cols if k in c]
        return cs[0] if cs else None
    d = pd.DataFrame({
        "t": df["receive_time"].values,
        "dir": df[p("dir_coord")].values,
        "sym_inst": df[p("sym_inst")].values,
        "sym_proc": df[p("sym_proc")].values,
        "coupl_proc": df[p("coupl_proc")].values,
        "vol": df[p("vol_coord")].values,
        "y": df["Y.Y_YIndexSeconds<PriceMid>.SHFE-AG@1"].values,
    })
    valid = ~((d["dir"] == 0) & (d["sym_inst"] == 0) & (d["coupl_proc"] == 0))
    d = d[valid].sort_values("t").reset_index(drop=True)
    d["day"] = (d["t"] // (86400 * 10**9)).astype(int)
    return d


def run_a1(d, n_sym_bins=5, n_vol_bins=3, n_folds=5):
    """M0 = 桶均值(dir×sym_inst_bin×vol_bin),M1 = M0 + 桶内 sym_proc + coupl_proc 线性。"""
    d = d.copy()
    d["dir_i"] = np.sign(d["dir"]).astype(int)
    d["si_b"] = pd.qcut(d["sym_inst"].rank(method="first"), n_sym_bins, labels=False).astype(int)
    d["vol_b"] = pd.qcut(d["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)
    days = np.sort(d["day"].unique()); block = len(days) // (n_folds + 1)
    folds = []
    for k in range(1, n_folds + 1):
        tr = d[d["day"].isin(days[: k * block])]; te = d[d["day"].isin(days[k * block:(k + 1) * block])]
        if len(te) < 1000: continue
        tr["bk"] = tr["dir_i"].astype(str) + "_" + tr["si_b"].astype(str) + "_" + tr["vol_b"].astype(str)
        te["bk"] = te["dir_i"].astype(str) + "_" + te["si_b"].astype(str) + "_" + te["vol_b"].astype(str)
        m0 = tr.groupby("bk")["y"].mean()
        pred0 = te["bk"].map(m0).fillna(tr["y"].mean()).values
        mse0 = float(np.mean((te["y"] - pred0) ** 2))
        # M1: 桶内 sym_proc + coupl_proc 二元 OLS
        coef = {}
        for bk, g in tr.groupby("bk"):
            if len(g) < 30: continue
            X = np.column_stack([np.ones(len(g)), g["sym_proc"].values, g["coupl_proc"].values])
            try: beta, *_ = np.linalg.lstsq(X, g["y"].values, rcond=None); coef[bk] = beta
            except Exception: continue
        pred1 = np.full(len(te), tr["y"].mean())
        for bk, beta in coef.items():
            mask = te["bk"] == bk
            X = np.column_stack([np.ones(mask.sum()), te["sym_proc"].values[mask], te["coupl_proc"].values[mask]])
            pred1[mask] = X @ beta
        mse1 = float(np.mean((te["y"] - pred1) ** 2))
        folds.append({"fold": k, "mse0": mse0, "mse1": mse1, "delta_oos": mse0 - mse1, "delta_pct": (mse0 - mse1) / mse0 * 100})
    deltas = [f["delta_oos"] for f in folds]
    return {"test": "A1_process_sufficiency", "model": "M0:f(dir,sym_inst,vol) vs M1:+sym_proc+coupl_proc",
            "folds": folds, "summary": {"delta_median": float(np.median(deltas)), "delta_all_positive": all(x > 0 for x in deltas), "delta_min": float(min(deltas))}}


def run_a2(d, n_vol_bins=3):
    """matched(dir=+1, sym_inst 窄带, vol 层),coupl_proc 中位切高低组比 Y。"""
    rng = np.random.default_rng(42)
    sub = d[(d["dir"] > 0) & (d["sym_inst"].abs() < d["sym_inst"].abs().quantile(0.4))].copy()  # sym_inst 近 0 窄带(|sym|≈|anti|)
    if len(sub) < 5000: return {"n": len(sub), "skipped": "sym_inst 窄带样本不足"}
    sub["vol_b"] = pd.qcut(sub["vol"].rank(method="first"), n_vol_bins, labels=False).astype(int)
    daily = []
    for day, g in sub.groupby("day"):
        eff = 0.0; cnt = 0
        for vb, vg in g.groupby("vol_b"):
            if len(vg) < 30: continue
            med = vg["coupl_proc"].median()
            hi = vg[vg["coupl_proc"] > med]["y"].mean()
            lo = vg[vg["coupl_proc"] <= med]["y"].mean()
            if np.isnan(hi) or np.isnan(lo): continue
            eff += hi - lo; cnt += 1
        if cnt: daily.append(eff / cnt)
    effs = np.array([v for v in daily if not np.isnan(v)])
    if len(effs) < 10: return {"n": len(sub), "skipped": "有效天数不足"}
    day_t = float(effs.mean() / (effs.std() / np.sqrt(len(effs))))
    nb = len(effs) // 10
    bs = [np.concatenate([effs[i * 10:(i + 1) * 10] for i in rng.choice(nb, nb, replace=True)]).mean() for _ in range(1000)] if nb >= 3 else [effs.mean()]
    ci = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    return {"n": int(len(sub)), "n_days": len(effs), "daily_effect_median": float(np.median(effs)),
            "positive_day_ratio": float((effs > 0).mean()), "day_t": round(day_t, 2),
            "block_ci": [round(ci[0], 5), round(ci[1], 5)], "ci_excludes_zero": ci[0] > 0 or ci[1] < 0,
            "note": "coupl_proc 高=同向单边持续,低=对称化持续。同 sym_inst(瞬时对称化同)但过程不同 → 行为差异?"}


def main():
    d = load(); OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {"n_total": len(d), "n_days": int(d["day"].nunique()), "A1": run_a1(d), "A2": run_a2(d)}
    (OUT_DIR / "confirmation_D315.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
