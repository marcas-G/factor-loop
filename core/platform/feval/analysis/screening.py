"""全量特征筛选。

遍历所有 (X, Y) 组合，对每对调用 analyze_pair() 计算统计指标，
最终返回按 |IC| 降序排列的 DataFrame，用于快速定位最有预测力的 feature-horizon 组合。
支持多进程加速。
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from feval.analysis.metrics import analyze_pair
from feval.config import Config
from feval.data.loader import LoadedData
from feval.data.columns import parse_y_column, parse_x_column


def _analyze_single_pair(args: Tuple) -> dict:
    """Worker function for parallel screening."""
    x_arr, y_arr, w_arr, x_col, y_col, receive_time = args
    result = analyze_pair(x_arr, y_arr, w_arr, receive_time=receive_time)

    parsed_x = parse_x_column(x_col)
    parsed_y = parse_y_column(y_col)
    instrument = parsed_x.instrument if parsed_x else ""
    horizon = parsed_y.horizon_seconds if parsed_y else -1

    nonzero_mask = x_arr != 0
    x_nz = x_arr[nonzero_mask]

    # zero_ratio based on valid samples only (exclude NaN)
    valid_mask = ~(np.isnan(x_arr) | np.isnan(y_arr))
    x_valid = x_arr[valid_mask]
    zero_ratio_val = float(np.mean(x_valid == 0)) if len(x_valid) > 0 else np.nan

    return {
        "x_col": x_col,
        "y_col": y_col,
        "instrument": instrument,
        "horizon": horizon,
        "n_samples": result.n_samples,
        "pearson_r": result.pearson_r,
        "pearson_p": result.pearson_p,
        "spearman_r": result.spearman_r,
        "spearman_p": result.spearman_p,
        "ic_mean": result.ic_mean,
        "ic_std": result.ic_std,
        "ic_ir": result.ic_ir,
        "n_days": result.n_days,
        "sign_match_rate": result.sign_match_rate,
        "zero_ratio": round(zero_ratio_val, 4),
        "nonzero_count": int(nonzero_mask.sum()),
        "x_std": round(float(np.std(x_nz)) if len(x_nz) > 0 else 0.0, 6),
        "y_std": round(float(np.std(y_arr)), 6),
        "x_skew": round(float(stats.skew(x_nz)) if len(x_nz) > 2 else 0.0, 4),
        "x_kurt": round(float(stats.kurtosis(x_nz)) if len(x_nz) > 3 else 0.0, 4),
    }


def run_screening(
    data: LoadedData,
    config: Optional[Config] = None,
    y_columns: Optional[List[str]] = None,
    x_columns: Optional[List[str]] = None,
    period: str = "train",
    parallel: bool = True,
) -> pd.DataFrame:
    """Screen all (X, Y) feature pairs by predictive quality.

    Args:
        data: LoadedData instance.
        config: Configuration. If None, uses defaults.
        y_columns: Subset of Y columns. If None, all Y columns.
        x_columns: Subset of X columns. If None, all X columns.
        period: "train", "test", or "all".
        parallel: Use multiprocessing.

    Returns:
        DataFrame sorted by |ic_mean| descending.
    """
    if config is None:
        config = Config()

    y_cols = y_columns or data.y_columns
    x_cols = x_columns or data.x_columns

    # Select data based on period
    if period == "train":
        mask = data.train_mask
    elif period == "test":
        mask = data.test_mask
    else:
        mask = np.ones(len(data.receive_time), dtype=bool)

    x_df = data.x_values[mask]
    y_df = data.y_values[mask]
    w = data.weight[mask]
    rt = data.receive_time[mask]

    # Build work items
    work_items = []
    for xc in x_cols:
        if xc not in x_df.columns:
            continue
        x_arr = x_df[xc].values.astype(np.float64)
        for yc in y_cols:
            if yc not in y_df.columns:
                continue
            y_arr = y_df[yc].values.astype(np.float64)
            work_items.append((x_arr, y_arr, w, xc, yc, rt))

    if not work_items:
        return pd.DataFrame()

    # Execute
    if parallel and len(work_items) > 10:
        with ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_analyze_single_pair, work_items))
    else:
        results = [_analyze_single_pair(item) for item in work_items]

    df = pd.DataFrame(results)
    df["abs_ic_mean"] = df["ic_mean"].abs()
    df = df.sort_values("abs_ic_mean", ascending=False).reset_index(drop=True)

    return df
