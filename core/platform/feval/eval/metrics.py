"""因子评估统计指标。

纯统计维度的因子分析：
- Session IC: 按 SHFE 交易时段拆分算 IC
- Vol-regime IC: 按波动率区间拆分算 IC
- Linear Edge (beta t-stat + R²): 线性校准诊断
- Quintile analysis: 5 分层单调性
- Zero analysis: X=0 vs X≠0 差异检验
- Train/Test IC: 过拟合检查（轻量级直接计算，不跑完整 screening）
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from feval.analysis.metrics import _date_key_from_ns
from feval.data.loader import LoadedData


def compute_session_ic(
    data: LoadedData,
    screening_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute IC broken down by SHFE trading session (CST).

    Sessions:
      morning:   09:00-10:15
      midday:    10:30-11:30
      afternoon: 13:30-15:00
      night:     21:00-02:30 (cross-midnight)
    """
    rows = []
    ts = data.receive_time
    ts_ns = ts.astype(np.int64)
    # Timestamps are UTC nanoseconds; +8h converts to CST.
    # Confirmed against actual data: first sample 09:05 CST, last 22:51 CST.
    min_of_day = ((ts_ns // 60_000_000_000) + 8 * 60) % (24 * 60)

    for _, row in screening_df.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_vals = data.x_values[x_col].values.astype(np.float64)
        y_vals = data.y_values[y_col].values.astype(np.float64)

        valid = ~(np.isnan(x_vals) | np.isnan(y_vals) | (x_vals == 0))
        if valid.sum() < 50:
            continue

        x_v = x_vals[valid]
        y_v = y_vals[valid]
        m = min_of_day[valid]

        session_ics = {}
        masks = {
            'morning': (m >= 9 * 60) & (m < 10 * 60 + 15),          # 09:00-10:15
            'midday': (m >= 10 * 60 + 30) & (m < 11 * 60 + 30),    # 10:30-11:30
            'afternoon': (m >= 13 * 60 + 30) & (m < 15 * 60),      # 13:30-15:00
            'night': (m >= 21 * 60) | (m < 2 * 60 + 30),           # 21:00-02:30
        }

        for name, mask in masks.items():
            if mask.sum() < 20:
                session_ics[name] = np.nan
            else:
                sr, _ = stats.spearmanr(x_v[mask], y_v[mask])
                session_ics[name] = sr

        ic_values = [v for v in session_ics.values() if not np.isnan(v)]
        ic_std = float(np.std(ic_values)) if len(ic_values) >= 2 else 0.0

        rows.append({
            'x_col': x_col,
            'y_col': y_col,
            'instrument': row['instrument'],
            'horizon': row['horizon'],
            'morning_ic': session_ics.get('morning', np.nan),
            'midday_ic': session_ics.get('midday', np.nan),
            'afternoon_ic': session_ics.get('afternoon', np.nan),
            'night_ic': session_ics.get('night', np.nan),
            'ic_std_across_sessions': ic_std,
        })

    return pd.DataFrame(rows)


def compute_vol_regime_ic(
    data: LoadedData,
    screening_df: pd.DataFrame,
    window: int = 1000,
) -> pd.DataFrame:
    """Compute IC broken down by volatility regime (rolling Y std quintile).

    Low vol = quiet market, high vol = active market.
    A good factor should work across all regimes.
    """
    rows = []

    for _, row in screening_df.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_vals = data.x_values[x_col].values.astype(np.float64)
        y_vals = data.y_values[y_col].values.astype(np.float64)

        valid = ~(np.isnan(x_vals) | np.isnan(y_vals) | (x_vals == 0))
        if valid.sum() < window:
            continue

        x_v = x_vals[valid]
        y_v = y_vals[valid]

        # Rolling volatility of Y as regime proxy
        rolling_std = pd.Series(y_v).rolling(window, min_periods=100).std().values
        not_na = ~np.isnan(rolling_std)
        if not_na.sum() < window:
            rows.append({
                'x_col': x_col, 'y_col': y_col,
                'horizon': row['horizon'],
                'q1_ic': np.nan, 'q2_ic': np.nan, 'q3_ic': np.nan,
                'q4_ic': np.nan, 'q5_ic': np.nan,
            })
            continue

        # Filter to rows with valid vol estimate
        x_f = x_v[not_na]
        y_f = y_v[not_na]
        vol_f = rolling_std[not_na]

        # 5 quintile buckets
        try:
            labels = pd.qcut(vol_f, 5, labels=False, duplicates='drop')
        except ValueError:
            continue

        regime_ics = {}
        for q in range(5):
            qmask = labels == q
            col = f'q{q + 1}_ic'
            if qmask.sum() < 20:
                regime_ics[col] = np.nan
            else:
                sr, _ = stats.spearmanr(x_f[qmask], y_f[qmask])
                regime_ics[col] = sr

        rows.append({
            'x_col': x_col, 'y_col': y_col,
            'instrument': row['instrument'],
            'horizon': row['horizon'],
            **regime_ics,
        })

    return pd.DataFrame(rows)


def compute_linear_edge(
    data: LoadedData,
    screening_df: pd.DataFrame,
) -> pd.DataFrame:
    """Linear calibration diagnostics.

    Fits Y = alpha + beta * X on active samples X != 0.
    Key metrics:
      - beta_tstat: significance of linear relationship
      - linear_r2: fraction of variance explained
      - variance_reduction_bps: R² * 10000
      - pred_std_ratio: std(predicted) / std(Y)
    """
    rows = []

    for _, row in screening_df.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_vals = data.x_values[x_col].values.astype(np.float64)
        y_vals = data.y_values[y_col].values.astype(np.float64)

        valid = ~(np.isnan(x_vals) | np.isnan(y_vals)) & (x_vals != 0)
        if valid.sum() < 50:
            continue

        x = x_vals[valid]
        y = y_vals[valid]
        n = len(x)

        x_mean = np.mean(x)
        y_mean = np.mean(y)
        x_centered = x - x_mean
        y_centered = y - y_mean

        sxx = np.sum(x_centered ** 2)
        y_var = np.var(y)

        if sxx < 1e-15 or y_var < 1e-15:
            continue

        beta = np.sum(x_centered * y_centered) / sxx
        alpha = y_mean - beta * x_mean
        y_hat = alpha + beta * x

        resid = y - y_hat
        y_std = float(np.std(y))

        resid_var = np.var(resid)
        linear_r2 = 1.0 - resid_var / y_var

        # beta standard error
        sigma2 = np.sum(resid ** 2) / max(n - 2, 1)
        beta_se = np.sqrt(sigma2 / sxx) if sxx > 1e-15 else np.nan
        if not np.isnan(beta_se) and beta_se > 1e-15:
            beta_tstat = beta / beta_se
        else:
            beta_tstat = np.nan

        pred_std = float(np.std(y_hat))
        pred_std_ratio = pred_std / y_std if y_std > 1e-15 else np.nan

        rows.append({
            'x_col': x_col,
            'y_col': y_col,
            'instrument': row.get('instrument', ''),
            'horizon': row.get('horizon', -1),

            'alpha': alpha,
            'beta': beta,
            'beta_tstat': beta_tstat,

            'linear_r2': linear_r2,
            'variance_reduction_bps': linear_r2 * 10000,

            'y_std': y_std,
            'pred_std_ratio': pred_std_ratio,

            'n_active': int(valid.sum()),
        })

    return pd.DataFrame(rows)



def compute_quintile(
    data: LoadedData,
    screening_df: pd.DataFrame,
    top_n: int = 5,
) -> Dict[Tuple[str, str], pd.DataFrame]:
    """Daily-internal quintile bucket analysis for top N pairs by |IC|.

    For each (x_col, y_col):
      - Zero bucket (Z): X=0 rows
      - Q1-Q5: X!=0 rows, quintiled within each trading day, then averaged across days.
      - Monotonicity supports both positive (Q1<Q2<...<Q5) and negative direction.
    """
    if "abs_ic_mean" in screening_df.columns:
        top = screening_df.nlargest(top_n, "abs_ic_mean")
    else:
        top = (
            screening_df
            .assign(abs_ic_mean=screening_df["ic_mean"].abs())
            .nlargest(top_n, "abs_ic_mean")
        )

    dates = _date_key_from_ns(data.receive_time)
    result = {}

    for _, row in top.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_vals = data.x_values[x_col].values.astype(np.float64)
        y_vals = data.y_values[y_col].values.astype(np.float64)

        y_valid = ~np.isnan(y_vals)
        zero_mask = y_valid & ((x_vals == 0) | np.isnan(x_vals))
        nz_mask = y_valid & (x_vals != 0)

        if nz_mask.sum() < 50:
            continue

        # Zero bucket
        zero_rows = []
        if zero_mask.sum() >= 20:
            y_zero = y_vals[zero_mask]
            zero_rows.append({
                'bucket': 'Z',
                'X_mean': 0.0,
                'Y_mean': float(np.mean(y_zero)),
                'Y_median': float(np.median(y_zero)),
                'Y_std': float(np.std(y_zero)),
                'count': int(zero_mask.sum()),
                'hit_rate': float((y_zero > 0).mean()),
            })

        # Daily internal quintile for X!=0
        x_nz = x_vals[nz_mask]
        y_nz = y_vals[nz_mask]
        dates_nz = dates[nz_mask]

        daily_bucket_records = []
        for date_val in np.unique(dates_nz):
            dm = dates_nz == date_val
            xd = x_nz[dm]
            yd = y_nz[dm]
            if len(xd) < 10:
                continue
            try:
                labels = pd.qcut(xd, 5, labels=False, duplicates='drop')
            except ValueError:
                continue
            valid_labels = labels[~np.isnan(labels)]
            if len(valid_labels) == 0:
                continue
            for q in np.unique(valid_labels):
                qm = labels == q
                y_q = yd[qm]
                daily_bucket_records.append({
                    'bucket': f'Q{int(q) + 1}',
                    'Y': y_q,
                    'y_mean': float(np.mean(y_q)),
                    'y_positive': float(np.mean(y_q > 0)),
                })

        if not daily_bucket_records:
            continue

        bucket_records = pd.DataFrame(daily_bucket_records)
        agg = (
            bucket_records
            .groupby('bucket', sort=True)
            .agg(
                Y_mean=('y_mean', 'mean'),
                Y_median=('y_mean', 'median'),
                Y_std=('y_mean', 'std'),
                count=('y_mean', 'count'),
                hit_rate=('y_positive', 'mean'),
            )
        )
        agg['X_mean'] = 0.0
        agg = agg[['X_mean', 'Y_mean', 'Y_median', 'Y_std', 'count', 'hit_rate']]

        # Combine zero + nonzero buckets
        all_rows = pd.DataFrame(zero_rows)
        if not all_rows.empty:
            all_rows = all_rows.set_index('bucket')
            combined = pd.concat([all_rows, agg])
        else:
            combined = agg

        # Monotonicity check (only on Q1-Q5)
        q_labels = [f'Q{q}' for q in range(1, 6)]
        q_vals = [combined.loc[q, 'Y_mean'] if q in combined.index else np.nan
                  for q in q_labels]
        q_valid = [(v, i) for i, v in enumerate(q_vals) if not np.isnan(v)]
        eps = 1e-12
        if len(q_valid) >= 2:
            inc = all(q_valid[i][0] <= q_valid[i + 1][0] + eps
                      for i in range(len(q_valid) - 1))
            dec = all(q_valid[i][0] >= q_valid[i + 1][0] - eps
                      for i in range(len(q_valid) - 1))
            if inc:
                direction = "positive"
            elif dec:
                direction = "negative"
            else:
                direction = "non_monotonic"
        else:
            direction = "insufficient_data"

        # t-stat: Q5 vs Q1
        q5_y = bucket_records[bucket_records['bucket'] == 'Q5']['Y']
        q1_y = bucket_records[bucket_records['bucket'] == 'Q1']['Y']
        t_stat = np.nan
        p_val = np.nan
        if len(q5_y) >= 2 and len(q1_y) >= 2:
            try:
                t_stat, p_val = stats.ttest_ind(
                    [np.mean(v) if hasattr(v, '__len__') else v for v in q5_y],
                    [np.mean(v) if hasattr(v, '__len__') else v for v in q1_y],
                    equal_var=False,
                )
            except Exception:
                pass

        combined.attrs['direction'] = direction
        combined.attrs['t_stat'] = t_stat
        combined.attrs['p_value'] = p_val
        result[(x_col, y_col)] = combined

    return result


def compute_zero_analysis(
    data: LoadedData,
    screening_df: pd.DataFrame,
) -> pd.DataFrame:
    """Analyze X=0 vs X!=0: does Y behave differently when factor is inactive?

    X=0 means no trade occurred in C++ system. If Y_mean(X=0) != Y_mean(X!=0),
    the factor carries information beyond just trade presence.
    """
    rows = []

    for _, row in screening_df.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_vals = data.x_values[x_col].values.astype(np.float64)
        y_vals = data.y_values[y_col].values.astype(np.float64)

        y_valid = ~np.isnan(y_vals)
        zero_mask = y_valid & ((x_vals == 0) | np.isnan(x_vals))
        nz_mask = y_valid & (x_vals != 0)

        if zero_mask.sum() < 50 or nz_mask.sum() < 50:
            continue

        y_zero = y_vals[zero_mask]
        y_nz = y_vals[nz_mask]

        t_stat, p_val = stats.ttest_ind(y_nz, y_zero, equal_var=False)

        rows.append({
            'x_col': x_col,
            'y_col': y_col,
            'instrument': row['instrument'],
            'horizon': row['horizon'],
            'zero_ratio': float(zero_mask.sum()) / len(x_vals),
            'y_mean_x0': float(np.mean(y_zero)),
            'y_mean_xnz': float(np.mean(y_nz)),
            'y_std_x0': float(np.std(y_zero)),
            'y_std_xnz': float(np.std(y_nz)),
            't_stat': float(t_stat),
            'p_value': float(p_val),
        })

    return pd.DataFrame(rows)


def _compute_daily_ic_for_pair(
    x: np.ndarray,
    y: np.ndarray,
    receive_time: np.ndarray,
) -> Tuple[float, int]:
    """Compute daily IC (mean of per-day Spearman) for one (X, Y) pair.

    Returns:
        (ic_mean, n_days)
    """
    valid = ~(np.isnan(x) | np.isnan(y))
    x = x[valid]
    y = y[valid]
    receive_time = receive_time[valid]

    if len(x) < 10:
        return 0.0, 0

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

    if not daily_ics:
        return 0.0, 0

    return float(np.nanmean(daily_ics)), len(daily_ics)


def compute_train_test(
    data: LoadedData,
    screening_df: pd.DataFrame,
) -> pd.DataFrame:
    """Train vs Test IC consistency check — lightweight direct computation.

    Instead of running full screening twice, computes daily IC directly
    on train and test splits for each pair found in screening_df.
    """
    rows = []

    for _, row in screening_df.iterrows():
        x_col, y_col = row['x_col'], row['y_col']
        x_all = data.x_values[x_col].values.astype(np.float64)
        y_all = data.y_values[y_col].values.astype(np.float64)

        # Train split
        train_ic, train_days = _compute_daily_ic_for_pair(
            x_all[data.train_mask],
            y_all[data.train_mask],
            data.receive_time[data.train_mask],
        )

        # Test split
        test_ic, test_days = _compute_daily_ic_for_pair(
            x_all[data.test_mask],
            y_all[data.test_mask],
            data.receive_time[data.test_mask],
        )

        ic_decay = test_ic / train_ic if abs(train_ic) > 1e-10 else 0.0
        same_sign = np.sign(train_ic) == np.sign(test_ic)
        abs_decay = abs(test_ic) / abs(train_ic) if abs(train_ic) > 1e-10 else np.nan
        min_abs_ic = min(abs(train_ic), abs(test_ic))

        rows.append({
            'x_col': x_col,
            'y_col': y_col,
            'train_ic': train_ic,
            'train_days': train_days,
            'test_ic': test_ic,
            'test_days': test_days,
            'ic_decay': ic_decay,
            'same_sign': same_sign,
            'abs_decay': abs_decay,
            'min_abs_ic': min_abs_ic,
            'test_abs_ic': abs(test_ic),
        })

    return pd.DataFrame(rows)
