"""数据观测工具:微观结构量跨 horizon 矛盾(泛化版)。

从 BookSnapshotInfo_raw 算指定微观结构量 X,看它在 5 个 horizon 的预测是否矛盾。
支持多种 X(--x-type):
  ofi                加撤净流 OFI = Σ档 w·[(bid_add−bid_cancel)−(ask_add−ask_cancel)]
  cancel_asymmetry   撤单方向偏度 = Σ档 w·(bid_cancel−ask_cancel)   撤买−撤卖
  add_asymmetry      加单方向偏度 = Σ档 w·(bid_add−ask_add)          加买−加卖
  cancel_intensity   撤单强度 = Σ档 w·(bid_cancel+ask_cancel)        撤单总量(非方向)

反常形态:同一量在不同 horizon 方向相反(LMSW 式)。
撤单偏度理论上可能短强长反(意图消散)——高潜力矛盾源。

返回 observation + significance(ICIR/正天比) + robustness(跨天std) + 矛盾判定。
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("/home/lgao/work/quant/factor-evaluate-tmp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
HORIZONS = [1, 5, 10, 60, 300]
LEVELS = 5

# 每个 x_type 需要的原始列后缀
_X_DEPS = {
    "ofi": [("bid", "add"), ("bid", "cancel"), ("ask", "add"), ("ask", "cancel")],
    "cancel_asymmetry": [("bid", "cancel"), ("ask", "cancel")],
    "add_asymmetry": [("bid", "add"), ("ask", "add")],
    "cancel_intensity": [("bid", "cancel"), ("ask", "cancel")],
}


def compute_x(df: pd.DataFrame, x_type: str, symbol: str, contract: str) -> np.ndarray:
    prefix = f"X.{symbol}{contract}@bsi_"
    x = np.zeros(len(df), dtype=np.float64)
    for i in range(LEVELS):
        w = 1.0 / (i + 1)
        if x_type == "ofi":
            bid_net = df[f"{prefix}bid_add_{i}"].values - df[f"{prefix}bid_cancel_{i}"].values
            ask_net = df[f"{prefix}ask_add_{i}"].values - df[f"{prefix}ask_cancel_{i}"].values
            x += w * (bid_net - ask_net)
        elif x_type == "cancel_asymmetry":
            x += w * (df[f"{prefix}bid_cancel_{i}"].values - df[f"{prefix}ask_cancel_{i}"].values)
        elif x_type == "add_asymmetry":
            x += w * (df[f"{prefix}bid_add_{i}"].values - df[f"{prefix}ask_add_{i}"].values)
        elif x_type == "cancel_intensity":
            x += w * (df[f"{prefix}bid_cancel_{i}"].values + df[f"{prefix}ask_cancel_{i}"].values)
        else:
            raise ValueError(f"未知 x_type: {x_type}")
    return x


def rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 30:
        return float("nan")
    xr = pd.Series(x[mask]).rank().values
    yr = pd.Series(y[mask]).rank().values
    return float(np.corrcoef(xr, yr)[0, 1])


def observe(days: int, symbol: str, contract: str, x_type: str) -> dict:
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    if not files:
        return {"error": f"无 daily-*.xy 于 {RAW_DIR}"}

    prefix = f"X.{symbol}{contract}@bsi_"
    deps = _X_DEPS[x_type]
    need_cols = ["receive_time"]
    for side, op in deps:
        for i in range(LEVELS):
            need_cols.append(f"{prefix}{side}_{op}_{i}")
    for h in HORIZONS:
        need_cols.append(f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{h}")

    ics_by_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need_cols)
        if not all(c in df.columns for c in need_cols):
            continue
        x = compute_x(df, x_type, symbol, contract)
        for h in HORIZONS:
            ycol = f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{h}"
            ic = rank_ic(x, df[ycol].values)
            if np.isfinite(ic):
                ics_by_h[h].append(ic)

    by_horizon: dict[int, dict] = {}
    for h in HORIZONS:
        arr = np.array(ics_by_h[h])
        if len(arr) == 0:
            continue
        std = float(arr.std())
        by_horizon[str(h)] = {
            "mean_ic": float(arr.mean()),
            "icir": float(arr.mean() / (std + 1e-12)),
            "std": std,
            "n_days": int(len(arr)),
            "pos_ratio": float((arr > 0).mean()),
            "sign": "+" if arr.mean() > 0 else "-",
        }

    short_ic = by_horizon.get("1", {}).get("mean_ic", 0.0)
    long_ic = by_horizon.get("300", {}).get("mean_ic", 0.0)
    short_pos = by_horizon.get("1", {}).get("pos_ratio", 0.5)
    long_pos = by_horizon.get("300", {}).get("pos_ratio", 0.5)
    short_strong = abs(short_ic) > 0.02 and abs(short_pos - 0.5) > 0.15
    long_strong = abs(long_ic) > 0.02 and abs(long_pos - 0.5) > 0.15
    contradiction = bool(short_ic * long_ic < 0 and short_strong and long_strong)

    # 衰减形态:短→长 IC 是否单调衰减(信息扩散) vs 非单调(机制切换)
    ics_seq = [by_horizon.get(str(h), {}).get("mean_ic") for h in HORIZONS]
    ics_seq = [v for v in ics_seq if v is not None]
    monotonic = all(ics_seq[i] >= ics_seq[i + 1] for i in range(len(ics_seq) - 1)) or \
                all(ics_seq[i] <= ics_seq[i + 1] for i in range(len(ics_seq) - 1))

    return {
        "observation": f"{x_type}_cross_horizon",
        "symbol": f"{symbol}{contract}",
        "x_type": x_type,
        "n_days": len(files),
        "by_horizon": by_horizon,
        "contradiction_short_vs_long": contradiction,
        "monotonic_decay": bool(monotonic),
        "short_1s_ic": short_ic,
        "long_300s_ic": long_ic,
        "summary": (
            f"{x_type} @1s IC={short_ic:+.4f}(正天{short_pos:.0%}) vs "
            f"@300s IC={long_ic:+.4f}(正天{long_pos:.0%}); "
            f"{'跨horizon矛盾' if contradiction else ('单调衰减' if monotonic else '非单调')}"
        ),
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from observe_common import emit

    p = argparse.ArgumentParser(description="微观结构量跨 horizon 观测")
    p.add_argument("--x-type", default="ofi", choices=list(_X_DEPS.keys()))
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--contract", default="")
    p.add_argument("--out", default=None, help="写 JSON 到文件(默认 print)")
    a = p.parse_args()
    res = observe(a.days, a.symbol, a.contract, a.x_type)
    res["axiom_code"] = "info_diffusion_monotone"
    # 违反扩散单调性:IC 跨 horizon 非单调(信息该单调衰减却不衰减/反弹/反向)
    res["violation"] = None if res.get("monotonic_decay") else (
        f"nonmonotonic_diffusion({a.x_type} IC跨horizon非单调: 该单调衰减却不单调, "
        f"短={res.get('short_1s_ic', 0):+.4f} 长={res.get('long_300s_ic', 0):+.4f})"
    )
    emit(res, a.out)
