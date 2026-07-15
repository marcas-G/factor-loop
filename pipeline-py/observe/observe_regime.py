"""数据观测工具:regime 条件矛盾(LMSW 式)。

算微观结构量 X 在不同波动率 regime(低/中/高)的预测力,暴露"同量不同状态方向相反"。
反常形态:LMSW 式状态条件——同一量在高波动 regime 正预测、低波动 regime 反向(或反之)。
这种矛盾在 horizon 维度看不到(被全样本平均稀释),只在 regime 切片下显形。

波动率:mid 收益的滚动 std(窗口 VOL_WINDOW 快照),按当天分位分 n_regimes 档。
返回 by_regime IC + 矛盾判定(最低 vs 最高 regime 符号相反且都显著)。
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("/home/lgao/work/quant/factor-evaluate-tmp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
LEVELS = 5
VOL_WINDOW = 200  # 滚动波动率窗口(快照数,500ms×200=100s)


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


def observe(days: int, symbol: str, contract: str, x_type: str, horizon: int, n_regimes: int) -> dict:
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    if not files:
        return {"error": f"无 daily-*.xy 于 {RAW_DIR}"}

    prefix = f"X.{symbol}{contract}@bsi_"
    ycol = f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{horizon}"
    need_cols = ["receive_time", f"{prefix}mid_price", ycol]
    for side in ("bid", "ask"):
        for op in ("add", "cancel"):
            for i in range(LEVELS):
                need_cols.append(f"{prefix}{side}_{op}_{i}")

    regime_ics: dict[int, list[float]] = {r: [] for r in range(n_regimes)}
    for fp in files:
        df = pd.read_csv(fp, usecols=lambda c: c in need_cols)
        if not all(c in df.columns for c in need_cols):
            continue
        mid = df[f"{prefix}mid_price"].astype(np.float64)
        x = compute_x(df, x_type, symbol, contract)
        y = df[ycol].astype(np.float64).values
        vol = mid.diff().rolling(VOL_WINDOW).std()
        vol_arr = vol.values
        finite = np.isfinite(vol_arr)
        if finite.sum() < n_regimes * 100:
            continue
        bounds = np.nanquantile(vol_arr[finite], np.linspace(0, 1, n_regimes + 1))
        for r in range(n_regimes):
            if r < n_regimes - 1:
                m = (vol_arr >= bounds[r]) & (vol_arr < bounds[r + 1])
            else:
                m = (vol_arr >= bounds[r]) & (vol_arr <= bounds[r + 1])
            ic = rank_ic(x[m], y[m])
            if np.isfinite(ic):
                regime_ics[r].append(ic)

    by_regime: dict[int, dict] = {}
    labels = ["极低波动", "低波动", "中波动", "高波动", "极高波动"]
    for r in range(n_regimes):
        arr = np.array(regime_ics[r])
        if len(arr) == 0:
            continue
        std = float(arr.std())
        by_regime[str(r)] = {
            "label": labels[r] if r < len(labels) else f"regime{r}",
            "mean_ic": float(arr.mean()),
            "icir": float(arr.mean() / (std + 1e-12)),
            "n_days": int(len(arr)),
            "pos_ratio": float((arr > 0).mean()),
            "sign": "+" if arr.mean() > 0 else "-",
        }

    low = by_regime.get("0", {})
    high = by_regime.get(str(n_regimes - 1), {})
    low_ic = low.get("mean_ic", 0.0)
    high_ic = high.get("mean_ic", 0.0)
    low_pos = low.get("pos_ratio", 0.5)
    high_pos = high.get("pos_ratio", 0.5)
    low_strong = abs(low_ic) > 0.015 and abs(low_pos - 0.5) > 0.15
    high_strong = abs(high_ic) > 0.015 and abs(high_pos - 0.5) > 0.15
    contradiction = bool(low_ic * high_ic < 0 and low_strong and high_strong)

    return {
        "observation": f"{x_type}_regime_conditional",
        "symbol": f"{symbol}{contract}",
        "x_type": x_type,
        "horizon_s": horizon,
        "n_regimes": n_regimes,
        "n_days": len(files),
        "by_regime": by_regime,
        "contradiction_low_vs_high": contradiction,
        "low_regime_ic": low_ic,
        "high_regime_ic": high_ic,
        "summary": (
            f"{x_type}@{horizon}s 低波动IC={low_ic:+.4f}(正天{low_pos:.0%}) vs "
            f"高波动IC={high_ic:+.4f}(正天{high_pos:.0%}); "
            f"{'regime矛盾(低/高反向)' if contradiction else '无regime矛盾'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="regime 条件矛盾观测")
    p.add_argument("--x-type", default="ofi", choices=["ofi", "cancel_asymmetry", "add_asymmetry"])
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--contract", default="")
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--n-regimes", type=int, default=3)
    a = p.parse_args()
    print(json.dumps(observe(a.days, a.symbol, a.contract, a.x_type, a.horizon, a.n_regimes),
                     ensure_ascii=False, indent=2))
