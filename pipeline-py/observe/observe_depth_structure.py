"""深度结构观测。

5档 size 的结构量:HHI(集中度)/熵/近远档比/盘口斜率。
反常:深度堆积(HHI高,流动性集中)/枯竭/近远档比突变(流动性结构切换)。
观测这些结构量在不同波动 regime 的形态(结构是否随 regime 突变)。
"""
from __future__ import annotations
import argparse
import json
from observe_common import *


def depth_metrics(df, symbol, contract=""):
    """算 5档 bid+ask size 的 HHI/熵/近远比/斜率。"""
    prefix = f"X.{symbol}{contract}@bsi_"
    bid_sizes = np.array([df[f"{prefix}bid_size_{i}"].values for i in range(LEVELS)], dtype=float).T  # (N,5)
    ask_sizes = np.array([df[f"{prefix}ask_size_{i}"].values for i in range(LEVELS)], dtype=float).T
    total = bid_sizes.sum(1) + ask_sizes.sum(1) + 1e-12
    # HHI: 各档占比平方和(集中度,高=堆积)
    shares = np.concatenate([bid_sizes, ask_sizes], axis=1) / total[:, None]
    hhi = (shares ** 2).sum(1)
    # 熵
    entropy = -(shares * np.log(shares + 1e-12)).sum(1)
    # 近远档比: 档0 总量 / 档1-4 总量
    near = bid_sizes[:, 0] + ask_sizes[:, 0]
    far = bid_sizes[:, 1:].sum(1) + ask_sizes[:, 1:].sum(1)
    near_far = near / (far + 1e-12)
    return hhi, entropy, near_far


def observe(days, symbol, horizon):
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    prefix = f"X.{symbol}@bsi_"
    need = ["receive_time", mid_col(symbol)] + [f"{prefix}{s}_size_{i}" for s in ("bid", "ask") for i in range(LEVELS)] + [ycol(symbol, horizon)]
    hhi_ic, entropy_ic, nf_ic = [], [], []
    hhi_means = []
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need)
        if not all(c in df.columns for c in need):
            continue
        hhi, entropy, nf = depth_metrics(df, symbol)
        y = df[ycol(symbol, horizon)].values
        hhi_means.append(float(np.nanmean(hhi)))
        # 结构量 vs Y 的 IC(结构能否预测收益)
        for x, lst in [(hhi, hhi_ic), (entropy, entropy_ic), (nf, nf_ic)]:
            lst.append(rank_ic(x, y))
    hi = agg(hhi_ic)
    ei = agg(entropy_ic)
    ni = agg(nf_ic)
    if not (hi and ei and ni):
        return {"error": "数据不足"}
    hhi_mean = float(np.mean(hhi_means))
    # 反常:HHI 高(>0.3 集中) 或 结构量预测力显著
    hhi_concentrated = hhi_mean > 0.3
    structure_predictive = abs(hi["mean"]) > 0.02 and hi["pos_ratio"] > 0.7 or abs(hi["mean"]) > 0.02 and hi["pos_ratio"] < 0.3
    return {
        "observation": "depth_structure",
        "symbol": symbol, "horizon_s": horizon, "n_days": len(files),
        "hhi_mean": hhi_mean,
        "hhi_ic": hi["mean"], "entropy_ic": ei["mean"], "near_far_ic": ni["mean"],
        "hhi_pos_ratio": hi["pos_ratio"],
        "hhi_concentrated": bool(hhi_concentrated),
        "structure_predictive": bool(structure_predictive),
        "summary": (
            f"深度 HHI均值={hhi_mean:.3f}({'集中★' if hhi_concentrated else '分散'}) "
            f"结构预测力 HHI_IC={hi['mean']:+.4f}(正天{hi['pos_ratio']:.0%}) "
            f"熵_IC={ei['mean']:+.4f} 近远比_IC={ni['mean']:+.4f}; "
            f"{'结构反常(集中或预测)' if (hhi_concentrated or structure_predictive) else '结构正常'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--horizon", type=int, default=1)
    a = p.parse_args()
    print(json.dumps(observe(a.days, a.symbol, a.horizon), ensure_ascii=False, indent=2))
