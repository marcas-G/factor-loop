"""Decision engine: merge all feval outputs into scored KEEP/WATCH/REJECT table.

Scoring dimensions (max 12 points):
  1. Sample quality      (0-1 pt)  — active sample count
  2. IC strength         (0-2 pt)  — |daily IC mean|
  3. IC stability        (0-1 pt)  — ICIR = ic_mean / ic_std
  4. Train/Test          (0-2 pt)  — sign consistency + abs decay
  5. Bucket shape        (0-2 pt)  — monotonicity + spread significance
  6. Session stability   (0-1 pt)  — cross-session IC consistency
  7. Vol-regime          (0-1 pt)  — cross-regime IC consistency
  8. Zero analysis       (0-1 pt)  — X=0 vs X≠0 Y difference
  9. Linear edge         (0-1 pt)  — beta t-stat significance

Decision thresholds:
  KEEP:   score >= 8
  WATCH:  score >= 4
  REJECT: score < 4
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


def _quintile_summary(quintile_df: Dict[Tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Extract key quintile metrics for decision scoring."""
    rows = []

    for (x_col, y_col), qdf in quintile_df.items():
        q_vals = {}
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            if q in qdf.index:
                q_vals[q] = qdf.loc[q, "Y_mean"]
            else:
                q_vals[q] = np.nan

        q1 = q_vals.get("Q1", np.nan)
        q5 = q_vals.get("Q5", np.nan)

        bucket_spread = q5 - q1 if not (np.isnan(q1) or np.isnan(q5)) else np.nan

        direction = getattr(qdf, "attrs", {}).get("direction", "unknown")
        t_stat = getattr(qdf, "attrs", {}).get("t_stat", np.nan)
        p_value = getattr(qdf, "attrs", {}).get("p_value", np.nan)

        rows.append({
            "x_col": x_col,
            "y_col": y_col,
            "bucket_direction": direction,
            "bucket_spread": bucket_spread,
            "bucket_tstat": t_stat,
            "bucket_pvalue": p_value,
            "q1_y": q1,
            "q5_y": q5,
            "zero_y": qdf.loc["Z", "Y_mean"] if "Z" in qdf.index else np.nan,
        })

    return pd.DataFrame(rows)


def compute_decision_summary(result) -> pd.DataFrame:
    """Merge all feval outputs into one decision table with KEEP/WATCH/REJECT."""

    base = result.screening_df.copy()

    # Merge linear edge
    if not result.linear_edge_df.empty:
        base = base.merge(
            result.linear_edge_df,
            on=["x_col", "y_col", "instrument", "horizon"],
            how="left",
            suffixes=("", "_linear"),
        )

    # Merge zero analysis
    if not result.zero_analysis_df.empty:
        zero = result.zero_analysis_df.copy()
        zero["zero_diff"] = zero["y_mean_xnz"] - zero["y_mean_x0"]
        zero = zero.rename(columns={
            "t_stat": "zero_tstat",
            "p_value": "zero_pvalue",
        })
        base = base.merge(
            zero[[
                "x_col", "y_col", "instrument", "horizon",
                "zero_ratio", "y_mean_x0", "y_mean_xnz",
                "zero_diff", "zero_tstat", "zero_pvalue",
            ]],
            on=["x_col", "y_col", "instrument", "horizon"],
            how="left",
            suffixes=("", "_zero"),
        )

    # Merge train/test
    if not result.train_test_df.empty:
        base = base.merge(
            result.train_test_df[[
                "x_col", "y_col",
                "train_ic", "test_ic", "ic_decay",
                "same_sign", "abs_decay", "min_abs_ic", "test_abs_ic",
            ]],
            on=["x_col", "y_col"],
            how="left",
        )

    # Merge quintile summary
    qsum = _quintile_summary(result.quintile_df)
    if not qsum.empty:
        base = base.merge(qsum, on=["x_col", "y_col"], how="left")

    # Merge session consistency
    if not result.session_ic_df.empty:
        sess = result.session_ic_df[[
            "x_col", "y_col", "ic_std_across_sessions",
        ]].copy()
        base = base.merge(sess, on=["x_col", "y_col"], how="left")

    # Merge vol regime consistency
    if not result.vol_regime_ic_df.empty:
        vol = result.vol_regime_ic_df.copy()
        qcols = [c for c in vol.columns if c.startswith("q") and c.endswith("_ic")]
        if qcols:
            vol["vol_min_ic"] = vol[qcols].min(axis=1)
            vol["vol_max_ic"] = vol[qcols].max(axis=1)
            vol["vol_ic_range"] = vol["vol_max_ic"] - vol["vol_min_ic"]
            # Check if IC sign is consistent across all regimes
            vol["vol_ic_sign_consistent"] = vol[qcols].apply(
                lambda row: _check_sign_consistency(row.dropna().values), axis=1
            )
            base = base.merge(
                vol[["x_col", "y_col", "vol_min_ic", "vol_max_ic",
                     "vol_ic_range", "vol_ic_sign_consistent"]],
                on=["x_col", "y_col"],
                how="left",
            )

    # Scoring
    decisions = []
    scores = []
    reasons = []

    for _, row in base.iterrows():
        score = 0
        reason = []

        ic = abs(row.get("ic_mean", 0))
        ic_ir = abs(row.get("ic_ir", 0))
        nonzero_count = row.get("nonzero_count", 0)

        # --- 1. Sample quality (0-1 pt) ---
        if nonzero_count >= 1000:
            score += 1
        elif nonzero_count >= 500:
            score += 0.5
        else:
            reason.append("low_active_count")

        # --- 2. IC strength (0-2 pt) ---
        if ic >= 0.03:
            score += 2
        elif ic >= 0.015:
            score += 1.5
        elif ic >= 0.005:
            score += 1
        elif ic >= 0.002:
            score += 0.5
        else:
            reason.append("weak_ic")

        # --- 3. IC stability via ICIR (0-1 pt) ---
        if ic_ir >= 1.5:
            score += 1
        elif ic_ir >= 0.8:
            score += 0.5
        else:
            reason.append("low_icir")

        # --- 4. Train/Test consistency (0-2 pt) ---
        same_sign = bool(row.get("same_sign", False))
        min_abs_ic = row.get("min_abs_ic", 0)
        abs_decay = row.get("abs_decay", np.nan)

        if same_sign and min_abs_ic >= 0.005:
            if not pd.isna(abs_decay) and abs_decay >= 0.7:
                score += 2  # strong consistency
            elif not pd.isna(abs_decay) and abs_decay >= 0.4:
                score += 1.5  # moderate consistency
            else:
                score += 1  # sign ok but decay heavy
        elif same_sign and min_abs_ic >= 0.002:
            score += 1
        else:
            reason.append("weak_train_test")

        # --- 5. Bucket shape (0-2 pt) ---
        bdir = row.get("bucket_direction", "")
        bucket_spread = row.get("bucket_spread", np.nan)
        bucket_tstat = row.get("bucket_tstat", np.nan)

        if bdir in ("positive", "negative"):
            if not pd.isna(bucket_spread):
                score += 1  # monotonic direction
                # Bonus for significant spread
                if not pd.isna(bucket_tstat) and abs(bucket_tstat) >= 2:
                    score += 1
                elif not pd.isna(bucket_tstat) and abs(bucket_tstat) >= 1.5:
                    score += 0.5
                else:
                    reason.append("insig_bucket_spread")
            else:
                score += 0.5
        else:
            reason.append("bad_bucket_shape")

        # --- 6. Session stability (0-1 pt) ---
        sess_std = row.get("ic_std_across_sessions", np.nan)
        if not pd.isna(sess_std):
            if sess_std <= 0.02:
                score += 1  # very stable across sessions
            elif sess_std <= 0.04:
                score += 0.5  # moderately stable
            else:
                reason.append("session_unstable")

        # --- 7. Vol-regime stability (0-1 pt) ---
        vol_range = row.get("vol_ic_range", np.nan)
        vol_sign_ok = row.get("vol_ic_sign_consistent", np.nan)
        if not pd.isna(vol_range):
            if vol_range <= 0.03 and not pd.isna(vol_sign_ok) and vol_sign_ok:
                score += 1  # stable across vol regimes + same sign
            elif vol_range <= 0.05:
                score += 0.5
            else:
                reason.append("vol_regime_unstable")

        # --- 8. Zero analysis (0-1 pt) ---
        zp = row.get("zero_pvalue", np.nan)
        if not pd.isna(zp) and zp < 0.05:
            score += 1
        elif not pd.isna(zp):
            reason.append("no_zero_diff")

        # --- 9. Linear edge (0-1 pt) ---
        beta_t = row.get("beta_tstat", np.nan)
        if not pd.isna(beta_t) and abs(beta_t) >= 3:
            score += 1
        elif not pd.isna(beta_t) and abs(beta_t) >= 2:
            score += 0.5
        elif not pd.isna(beta_t):
            reason.append("weak_beta")

        # --- Decision ---
        if score >= 8:
            decision = "KEEP"
        elif score >= 4:
            decision = "WATCH"
        else:
            decision = "REJECT"

        scores.append(round(score, 1))
        decisions.append(decision)
        reasons.append(",".join(reason) if reason else "ok")

    base["score"] = scores
    base["decision"] = decisions
    base["reason"] = reasons

    # Sort by decision and score
    decision_rank = {"KEEP": 0, "WATCH": 1, "REJECT": 2}
    base["_decision_rank"] = base["decision"].map(decision_rank)
    base = base.sort_values(
        ["_decision_rank", "score", "abs_ic_mean"],
        ascending=[True, False, False],
    ).drop(columns=["_decision_rank"])

    return base


def _check_sign_consistency(ic_values: np.ndarray) -> bool:
    """Check if all IC values have the same sign (ignoring NaN)."""
    if len(ic_values) < 2:
        return True
    signs = np.sign(ic_values)
    signs = signs[signs != 0]  # ignore zeros
    if len(signs) == 0:
        return True
    return bool(np.all(signs > 0) or np.all(signs < 0))
