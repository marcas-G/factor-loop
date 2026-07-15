"""观测工具共享模块:raw 加载 + 微观结构量计算 + rank IC + 跨天聚合。"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

RAW_DIR = Path("/home/lgao/work/quant/factor-evaluate-tlp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
RAW_DIR = Path("/home/lgao/work/quant/factor-evaluate-tmp/BookSnapshotInfo_raw/BookSnapshotInfo/dailyX")
HORIZONS = [1, 5, 10, 60, 300]
LEVELS = 5


def compute_x(df, x_type, symbol, contract=""):
    """微观结构量:ofi/cancel_asymmetry/add_asymmetry。5档 1/(i+1) 加权。"""
    prefix = f"X.{symbol}{contract}@bsi_"
    x = np.zeros(len(df), dtype=np.float64)
    for i in range(LEVELS):
        w = 1.0 / (i + 1)
        if x_type == "ofi":
            bn = df[f"{prefix}bid_add_{i}"].values - df[f"{prefix}bid_cancel_{i}"].values
            an = df[f"{prefix}ask_add_{i}"].values - df[f"{prefix}ask_cancel_{i}"].values
            x += w * (bn - an)
        elif x_type == "cancel_asymmetry":
            x += w * (df[f"{prefix}bid_cancel_{i}"].values - df[f"{prefix}ask_cancel_{i}"].values)
        elif x_type == "add_asymmetry":
            x += w * (df[f"{prefix}bid_add_{i}"].values - df[f"{prefix}ask_add_{i}"].values)
    return x


def rank_ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 30:
        return float("nan")
    xr = pd.Series(x[m]).rank().values
    yr = pd.Series(y[m]).rank().values
    return float(np.corrcoef(xr, yr)[0, 1])


def agg(arrs):
    """跨天聚合:mean/std/icir/pos_ratio。"""
    arr = np.array([a for a in arrs if np.isfinite(a)])
    if len(arr) == 0:
        return None
    s = float(arr.std())
    return {
        "mean": float(arr.mean()),
        "std": s,
        "icir": float(arr.mean() / (s + 1e-12)),
        "n": int(len(arr)),
        "pos_ratio": float((arr > 0).mean()),
    }


def ycol(symbol, horizon):
    return f"Y.Y_YIndexSeconds<PriceMid>.{symbol}@{horizon}"


def mid_col(symbol, contract=""):
    return f"X.{symbol}{contract}@bsi_mid_price"


def x_dep_cols(x_type, symbol, contract=""):
    """X 计算需要的原始列。"""
    prefix = f"X.{symbol}{contract}@bsi_"
    ops = {"ofi": ["add", "cancel"], "cancel_asymmetry": ["cancel"], "add_asymmetry": ["add"]}
    cols = []
    for side in ("bid", "ask"):
        for op in ops.get(x_type, []):
            for i in range(LEVELS):
                cols.append(f"{prefix}{side}_{op}_{i}")
    return cols


def emit(result: dict, out: str | None = None) -> None:
    """observe 结果输出:--out 写文件,否则 print stdout。
    result 应含 axiom_code 和 violation(违反理论预期时填描述,符合预期时 None)。"""
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text)
        print(f"written: {out}")
    else:
        print(text)
