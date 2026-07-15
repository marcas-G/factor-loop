"""方向不对称观测(杠杆效应)。

X 在上涨状态(过去 lookback 收益>0) vs 下跌状态(<0)的预测力差异。
反常:单向有效(某量只在一个方向有效)或状态反向(两状态 IC 符号相反)。
杠杆效应经典:下跌冲击的预测力强于上涨(或反之)。
"""
from __future__ import annotations
import argparse
import json
from observe_common import *


def observe(days, symbol, x_type, horizon, lookback):
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    prefix = f"X.{symbol}@bsi_"
    need = ["receive_time", mid_col(symbol)] + x_dep_cols(x_type, symbol) + [ycol(symbol, horizon)]
    up_ics, down_ics = [], []
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need)
        if not all(c in df.columns for c in need):
            continue
        x = compute_x(df, x_type, symbol)
        y = df[ycol(symbol, horizon)].values
        mid = df[mid_col(symbol)].astype(np.float64)
        past = mid.diff(lookback).values  # 过去 lookback 快照收益(状态判定)
        up = past > 0
        down = past < 0
        iu = rank_ic(x[up], y[up])
        id_ = rank_ic(x[down], y[down])
        up_ics.append(iu)
        down_ics.append(id_)
    u = agg(up_ics)
    d = agg(down_ics)
    if not u or not d:
        return {"error": "数据不足"}
    sign_flip = (u["mean"] * d["mean"] < 0) and abs(u["mean"]) > 0.02 and abs(d["mean"]) > 0.02
    one_sided = (u["mean"] * d["mean"] > 0) and abs(u["mean"] - d["mean"]) > 0.04
    return {
        "observation": f"{x_type}_asymmetry",
        "symbol": symbol, "horizon_s": horizon, "lookback": lookback, "n_days": len(files),
        "up_state_ic": u["mean"], "down_state_ic": d["mean"],
        "up_pos_ratio": u["pos_ratio"], "down_pos_ratio": d["pos_ratio"],
        "sign_flip_up_vs_down": bool(sign_flip),
        "one_sided_dominance": bool(one_sided),
        "summary": (
            f"{x_type}@{horizon}s 上涨态IC={u['mean']:+.4f}(正天{u['pos_ratio']:.0%}) vs "
            f"下跌态IC={d['mean']:+.4f}(正天{d['pos_ratio']:.0%}); "
            f"{'符号反转(强反常)' if sign_flip else ('单向主导' if one_sided else '对称')}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--x-type", default="ofi")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--lookback", type=int, default=20, help="状态判定回看快照数")
    a = p.parse_args()
    print(json.dumps(observe(a.days, a.symbol, a.x_type, a.horizon, a.lookback), ensure_ascii=False, indent=2))
