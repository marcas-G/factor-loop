"""跨量矛盾观测。

两个微观结构量(OFI vs cancel_asymmetry)在某维度的预测力矛盾。
反常:两量本应同向(都捕捉订单流方向)却反向,或一个有效一个无效(信息正交/冗余)。
也算两者 IC 的跨 horizon 符号关系(冗余 vs 正交 vs 矛盾)。
"""
from __future__ import annotations
import argparse
import json
from observe_common import *


def observe(days, symbol, x1_type, x2_type):
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    prefix = f"X.{symbol}@bsi_"
    need = ["receive_time"] + x_dep_cols(x1_type, symbol) + x_dep_cols(x2_type, symbol)
    for h in HORIZONS:
        need.append(ycol(symbol, h))
    ic1_by_h, ic2_by_h = {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}
    x_corr = []  # 两量自身的相关(冗余度)
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need)
        if not all(c in df.columns for c in need):
            continue
        x1 = compute_x(df, x1_type, symbol)
        x2 = compute_x(df, x2_type, symbol)
        m = np.isfinite(x1) & np.isfinite(x2)
        if int(m.sum()) > 200:
            x_corr.append(float(np.corrcoef(x1[m], x2[m])[0, 1]))
        for h in HORIZONS:
            y = df[ycol(symbol, h)].values
            ic1_by_h[h].append(rank_ic(x1, y))
            ic2_by_h[h].append(rank_ic(x2, y))
    xc = agg(x_corr)
    rows = {}
    contradiction = False
    for h in HORIZONS:
        a1, a2 = agg(ic1_by_h[h]), agg(ic2_by_h[h])
        if a1 and a2:
            rows[h] = {"ic1": a1["mean"], "ic2": a2["mean"]}
            # 矛盾:同 horizon 两量符号相反且都显著
            if a1["mean"] * a2["mean"] < 0 and abs(a1["mean"]) > 0.02 and abs(a2["mean"]) > 0.02:
                contradiction = True
    if not xc:
        return {"error": "数据不足"}
    redundancy = abs(xc["mean"]) > 0.5  # 两量高度相关=冗余
    orthogonal = abs(xc["mean"]) < 0.2  # 低相关=正交(独立信息)
    return {
        "observation": "cross_factor",
        "x1": x1_type, "x2": x2_type, "symbol": symbol, "n_days": len(files),
        "x1_x2_corr": xc["mean"],
        "redundant": bool(redundancy),
        "orthogonal": bool(orthogonal),
        "contradiction_some_horizon": bool(contradiction),
        "by_horizon": {str(h): v for h, v in rows.items()},
        "summary": (
            f"{x1_type} vs {x2_type} 自身相关={xc['mean']:+.3f}"
            f"({'冗余' if redundancy else ('正交★独立信息' if orthogonal else '中度相关')}); "
            f"跨 horizon {'矛盾★' if contradiction else '无矛盾'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--x1", default="ofi")
    p.add_argument("--x2", default="cancel_asymmetry")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--out", default=None, help="写 JSON 到文件(默认 print)")
    a = p.parse_args()
    res = observe(a.days, a.symbol, a.x1, a.x2)
    res["axiom_code"] = "info_orthogonality"
    # 违反信息正交性:两量高度相关(冗余,本应正交却重叠)
    res["violation"] = None if not res.get("redundant") else (
        f"redundant({a.x1} vs {a.x2} 相关={res.get('x1_x2_corr', 0):+.3f}>0.5, "
        f"违反信息正交性:两信息源应独立却高度重叠)"
    )
    from observe_common import emit
    emit(res, a.out)
