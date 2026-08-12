"""单对 (X, Y) 统计指标计算。

评估一个特征对某个前瞻收益的预测能力，包括：
- Pearson / Spearman 相关系数
- Daily IC: 按自然日计算 Spearman IC，取均值/标准差/IR
- 符号一致性 (sign match rate)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class AnalysisResult:
    """Result of analyzing one (X, Y) pair."""

    x_col: str
    y_col: str
    n_samples: int

    # Correlations
    pearson_r: float
    pearson_p: float
    spearman_r: float
    spearman_p: float

    # Daily Information Coefficient
    ic_mean: float
    ic_std: float
    ic_ir: float  # information ratio = ic_mean / ic_std
    n_days: int   # number of trading days with valid IC

    # Prediction quality
    sign_match_rate: float

    # Weighted variants
    weighted_pearson: Optional[float] = None


def _date_key_from_ns(receive_time_ns: np.ndarray) -> np.ndarray:
    """Convert nanosecond timestamps (UTC) to CST date strings (YYYY-MM-DD)."""
    ts = pd.to_datetime(receive_time_ns, unit="ns", utc=True).tz_convert("Asia/Shanghai")
    return np.array(ts.date, dtype=object)


def analyze_pair(
    x: np.ndarray,
    y: np.ndarray,
    weight: Optional[np.ndarray] = None,
    receive_time: Optional[np.ndarray] = None,
) -> AnalysisResult:
    """Compute all analysis metrics for a single (X, Y) pair.

    Args:
        x: Feature values (1-D array).
        y: Target values (1-D array, same length as x).
        weight: Optional sample weights.
        receive_time: Optional int64 nanosecond timestamps for Daily IC.
                      If None, falls back to overall Spearman as ic_mean.

    Returns:
        AnalysisResult with all metrics.
    """
    # Drop NaN pairs
    valid = ~(np.isnan(x) | np.isnan(y))
    x = x[valid]
    y = y[valid]
    if weight is not None:
        weight = weight[valid]
    if receive_time is not None:
        receive_time = receive_time[valid]

    n = len(x)
    if n < 10:
        return _empty_result(x_col="", y_col="")

    # Pearson
    if n >= 3:
        pr, pp = stats.pearsonr(x, y)
    else:
        pr, pp = 0.0, 1.0

    # Spearman
    if n >= 3:
        sr, sp = stats.spearmanr(x, y)
    else:
        sr, sp = 0.0, 1.0

    # Daily IC: per-calendar-day Spearman, then aggregate
    if receive_time is not None:
        dates = _date_key_from_ns(receive_time)
        unique_dates = np.unique(dates)
        daily_ics = []
        for d in unique_dates:
            dm = dates == d
            xd = x[dm]
            yd = y[dm]
            if len(xd) < 10:
                continue
            if np.std(xd) < 1e-15 or np.std(yd) < 1e-15:
                daily_ics.append(0.0)
                continue
            r, _ = stats.spearmanr(xd, yd)
            daily_ics.append(r)

        if len(daily_ics) >= 2:
            ic_mean = float(np.nanmean(daily_ics))
            ic_std = float(np.nanstd(daily_ics))
            ic_ir = ic_mean / ic_std if ic_std > 1e-10 else 0.0
            n_days = len(daily_ics)
        elif len(daily_ics) == 1:
            ic_mean = daily_ics[0]
            ic_std = 0.0
            ic_ir = 0.0
            n_days = 1
        else:
            ic_mean = sr
            ic_std = 0.0
            ic_ir = 0.0
            n_days = 0
    else:
        # No timestamps: fall back to overall Spearman
        ic_mean = sr
        ic_std = 0.0
        ic_ir = 0.0
        n_days = 0

    # Sign match (exclude zeros in either)
    nonzero = (x != 0) & (y != 0)
    sign_match = float(np.mean(np.sign(x[nonzero]) == np.sign(y[nonzero]))) if np.any(nonzero) else 0.0

    # Weighted Pearson
    w_pearson = None
    if weight is not None and n >= 3:
        w_pearson = _weighted_correlation(x, y, weight)

    return AnalysisResult(
        x_col="",
        y_col="",
        n_samples=n,
        pearson_r=pr,
        pearson_p=pp,
        spearman_r=sr,
        spearman_p=sp,
        ic_mean=ic_mean,
        ic_std=ic_std,
        ic_ir=ic_ir,
        n_days=n_days,
        sign_match_rate=sign_match,
        weighted_pearson=w_pearson,
    )


def _weighted_correlation(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Compute weighted Pearson correlation."""
    w = np.asarray(w, dtype=float)
    w = np.where(np.isfinite(w), w, 0.0)
    if w.sum() <= 1e-15:
        return 0.0

    w = w / w.sum()
    mx = np.sum(w * x)
    my = np.sum(w * y)

    cov = np.sum(w * (x - mx) * (y - my))
    vx = np.sum(w * (x - mx) ** 2)
    vy = np.sum(w * (y - my) ** 2)

    denom = np.sqrt(vx * vy)
    if denom < 1e-15:
        return 0.0
    return float(cov / denom)


def _empty_result(x_col: str, y_col: str) -> AnalysisResult:
    return AnalysisResult(
        x_col=x_col, y_col=y_col, n_samples=0,
        pearson_r=0.0, pearson_p=1.0,
        spearman_r=0.0, spearman_p=1.0,
        ic_mean=0.0, ic_std=0.0, ic_ir=0.0,
        n_days=0,
        sign_match_rate=0.0,
    )
