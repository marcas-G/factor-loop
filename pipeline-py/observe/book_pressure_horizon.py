"""数据观测工具:OFI 跨 horizon 矛盾。

从 BookSnapshotInfo_raw 原始盘口算 OFI(订单流不平衡,5档加撤净流加权),
算 OFI 对 5 个 horizon(1/5/10/60/300s)收益的 rank IC,暴露跨 horizon 预测矛盾。

反常形态:同一微观结构量在不同 horizon 方向相反(LMSW 式状态条件矛盾)。
  - 若 OFI 在短 horizon 强正预测、长 horizon 反转(或反之) → 跨 horizon 矛盾反常
  - 单 horizon 的 IC 只是经验有效;跨 horizon 矛盾才暴露"机制随尺度切换"

返回 observation + significance(t值/ICIR) + robustness(跨天 std/正负比)。
防数据挖掘:矛盾需两端都显著(|IC|>阈值)且跨天稳健(正负比)才算。
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


def compute_ofi(df: pd.DataFrame, symbol: str = "SHFE-AG", contract: str = "") -> np.ndarray:
    """OFI = Σ档 w_i · [(bid_add_i − bid_cancel_i) − (ask_add_i − ask_cancel_i)], w_i = 1/(i+1)。

    contract="" 主力, "@1" 次月。加撤净流的方向性聚合(买压 − 卖压)。
    """
    prefix = f"X.{symbol}{contract}@bsi_"
    ofi = np.zeros(len(df), dtype=np.float64)
    for i in range(LEVELS):
        w = 1.0 / (i + 1)
        bid_net = df[f"{prefix}bid_add_{i}"].values - df[f"{prefix}bid_cancel_{i}"].values
        ask_net = df[f"{prefix}ask_add_{i}"].values - df[f"{prefix}ask_cancel_{i}"].values
        ofi += w * (bid_net - ask_net)
    return ofi


def rank_ic(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Spearman rank IC + t-stat。返回 (ic, t)。"""
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < 30:
        return float("nan"), float("nan")
    xr = pd.Series(x[mask]).rank().values
    yr = pd.Series(y[mask]).rank().values
    ic = float(np.corrcoef(xr, yr)[0, 1])
    t = float(ic * np.sqrt((n - 2) / (1 - ic ** 2 + 1e-12)))
    return ic, t


def observe(days: int = 5, symbol: str = "SHFE-AG", contract: str = "") -> dict:
    files = sorted(RAW_DIR.glob("daily-*.xy"))[:days]
    if not files:
        return {"error": f"无 daily-*.xy 于 {RAW_DIR}"}

    # 只读需要的列(主力 OFI 40列 + Y 5列 + time/weight),省 IO
    prefix = f"X.{symbol}{contract}@bsi_"
    need_cols = ["receive_time"]
    for side in ("bid", "ask"):
        for op in ("add", "cancel"):
            for i in range(LEVELS):
                need_cols.append(f"{prefix}{side}_{op}_{i}")
    for h in HORIZONS:
        need_cols.append(f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{h}")

    ics_by_h: dict[int, list[float]] = {h: [] for h in HORIZONS}
    for fp in files:
        try:
            df = pd.read_csv(fp, usecols=lambda c: c in need_cols)
        except Exception:
            df = pd.read_csv(fp)
        present = [c for c in need_cols if c in df.columns]
        if len(present) < len(need_cols):
            continue
        ofi = compute_ofi(df, symbol, contract)
        for h in HORIZONS:
            ycol = f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{h}"
            if ycol not in df.columns:
                continue
            ic, _ = rank_ic(ofi, df[ycol].values)
            if np.isfinite(ic):
                ics_by_h[h].append(ic)

    by_horizon: dict[int, dict] = {}
    for h in HORIZONS:
        arr = np.array(ics_by_h[h])
        if len(arr) == 0:
            continue
        std = float(arr.std())
        by_horizon[h] = {
            "mean_ic": float(arr.mean()),
            "icir": float(arr.mean() / (std + 1e-12)),
            "std": std,
            "n_days": int(len(arr)),
            "pos_ratio": float((arr > 0).mean()),  # 跨天正 IC 比例(稳健性)
            "sign": "+" if arr.mean() > 0 else "-",
        }

    # 跨 horizon 矛盾判定:短(1s) vs 长(300s) 符号相反 + 两端都显著 + 跨天稳健
    short_ic = by_horizon.get(1, {}).get("mean_ic", 0.0)
    long_ic = by_horizon.get(300, {}).get("mean_ic", 0.0)
    short_pos = by_horizon.get(1, {}).get("pos_ratio", 0.5)
    long_pos = by_horizon.get(300, {}).get("pos_ratio", 0.5)
    short_strong = abs(short_ic) > 0.02 and abs(short_pos - 0.5) > 0.15
    long_strong = abs(long_ic) > 0.02 and abs(long_pos - 0.5) > 0.15
    contradiction = bool(
        short_ic * long_ic < 0 and short_strong and long_strong
    )

    return {
        "observation": "ofi_cross_horizon",
        "symbol": f"{symbol}{contract}",
        "n_days": len(files),
        "by_horizon": by_horizon,
        "contradiction_short_vs_long": contradiction,
        "short_1s_ic": short_ic,
        "long_300s_ic": long_ic,
        "summary": (
            f"OFI @1s IC={short_ic:+.4f}(正天{short_pos:.0%}) vs "
            f"@300s IC={long_ic:+.4f}(正天{long_pos:.0%}); "
            f"{'跨horizon矛盾(短/长反向)' if contradiction else '无短长矛盾'}"
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="OFI 跨 horizon 矛盾观测")
    p.add_argument("--days", type=int, default=5, help="读多少天的 daily-*.xy")
    p.add_argument("--symbol", default="SHFE-AG")
    p.add_argument("--contract", default="", help="空=主力, @1=次月")
    a = p.parse_args()
    result = observe(a.days, a.symbol, a.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
