#!/usr/bin/env python3
"""7 维评估数据抓取(吸收 runtime/lib/metrics.mjs)。

从 checkOutput 读 feval/deep/csv_ic 产物,组装成结构化 JSON(喂给 assess 做因子级评估)。
输出结构与 metrics.mjs extractMetricsFromCheckOutput 1:1 对齐。

用法:
    from core.metrics import extract_metrics_from_check_output
    eval_metrics = extract_metrics_from_check_output(check_output, xname)
"""
from __future__ import annotations

import csv
import re
from pathlib import Path


def _num(v):
    if v is None or v == "":
        return None
    try:
        n = float(v)
        return n if n == n else None  # 排除 NaN
    except (ValueError, TypeError):
        return None


def _bool(v):
    if v is None or v == "":
        return None
    return v in ("True", "true", "1")


def read_csv(file_path: str | Path) -> list[dict] | None:
    """读 CSV → list[dict](原生处理引号/BOM/空行)。缺失/空 → None。"""
    p = Path(file_path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8-sig", errors="replace").strip()  # utf-8-sig 剥 BOM
    if not text:
        return None
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader if any(v.strip() for v in row.values())]


def _find_first(base: str | Path, candidates: list[str]) -> str | None:
    """在 base 下找第一个存在的路径。"""
    for c in candidates:
        p = Path(base) / c
        if p.exists():
            return str(p)
    return None


def _pair_label(r: dict) -> str:
    return f"{r.get('x_col', '')} vs {r.get('y_col', '')}"


def _pick_best_abs(rows: list[dict], value_key: str):
    """按 |value| 最大选 row。返回 (value, row) 或 None。"""
    best = None
    best_value = None
    for r in rows:
        v = _num(r.get(value_key))
        if v is None:
            continue
        if best_value is None or abs(v) > abs(best_value):
            best = r
            best_value = v
    return (best_value, best) if best is not None else None


def extract_metrics_from_check_output(check_output: str | Path, xname: str) -> dict:
    result = {
        "factor_level": {"n_pairs": 0, "keep": 0, "watch": 0, "reject": 0, "best_score": None, "best_pair": None},
        "core_metrics": {},
        "deep_best": {},
        "top_pairs": [],
        "failure_reasons": {},
        "stationarity": {},
        "transform_family": {},
    }

    # ---- 1. decision_summary.csv:因子级 decision 分布 + best score ----
    decision_csv = _find_first(check_output, [
        "all_factors_decision_summary.csv",
        f"{xname}/dailyX/{xname}_feval/decision_summary.csv",
    ])
    decision_rows = read_csv(decision_csv) if decision_csv else None
    if decision_rows:
        result["factor_level"]["n_pairs"] = len(decision_rows)
        for r in decision_rows:
            d = (r.get("decision") or "").upper()
            if d == "KEEP":
                result["factor_level"]["keep"] += 1
            elif d == "WATCH":
                result["factor_level"]["watch"] += 1
            elif d == "REJECT":
                result["factor_level"]["reject"] += 1
            for reason in (r.get("reason") or "").split(","):
                reason = reason.strip()
                if reason:
                    result["failure_reasons"][reason] = result["failure_reasons"].get(reason, 0) + 1
        best = sorted(
            ({"score": _num(r.get("score")), "pair": _pair_label(r),
              "decision": r.get("decision"), "reason": r.get("reason") or ""}
             for r in decision_rows),
            key=lambda x: -(x["score"] if x["score"] is not None else float("-inf")),
        )
        best = [x for x in best if x["score"] is not None]
        if best:
            result["factor_level"]["best_score"] = best[0]["score"]
            result["factor_level"]["best_pair"] = best[0]["pair"]
            result["top_pairs"] = best[:3]

    # ---- 2. feval 子目录里的 7 维 CSV ----
    feval_dir = _find_first(check_output, [f"{xname}/dailyX/{xname}_feval"])
    if feval_dir:
        # Screening: screening.csv — |ic_mean| 最大的 pair
        screening = read_csv(Path(feval_dir) / "screening.csv")
        if screening:
            v, r = _pick_best_abs(screening, "ic_mean") or (None, None)
            if v is not None:
                result["core_metrics"]["screening"] = {
                    "ic_mean": v,
                    "icir": _num(r.get("ic_ir")),
                    "spearman": _num(r.get("spearman_r")),
                    "sign_match_rate": _num(r.get("sign_match_rate")),
                    "zero_ratio": _num(r.get("zero_ratio")),
                    "pair": _pair_label(r),
                }
        # Session IC: session_ic.csv — std 最小
        session = read_csv(Path(feval_dir) / "session_ic.csv")
        if session:
            sorted_s = sorted(
                (r for r in session if _num(r.get("ic_std_across_sessions")) is not None),
                key=lambda r: _num(r.get("ic_std_across_sessions")),
            )
            if sorted_s:
                b = sorted_s[0]
                result["core_metrics"]["session_ic"] = {
                    "morning": _num(b.get("morning_ic")), "midday": _num(b.get("midday_ic")),
                    "afternoon": _num(b.get("afternoon_ic")), "night": _num(b.get("night_ic")),
                    "std": _num(b.get("ic_std_across_sessions")), "pair": _pair_label(b),
                }
        # Vol regime: vol_regime_ic.csv — sign 最一致
        vol = read_csv(Path(feval_dir) / "vol_regime_ic.csv")
        if vol:
            def annotate(r):
                qs = [x for x in [_num(r.get("q1_ic")), _num(r.get("q2_ic")), _num(r.get("q3_ic")),
                                  _num(r.get("q4_ic")), _num(r.get("q5_ic"))] if x is not None]
                all_same = len(qs) == 5 and all(
                    (x > 0) == (qs[0] > 0) for x in qs[1:]
                )
                min_abs = min((abs(x) for x in qs), default=0)
                return (all_same, min_abs, r)
            annotated = [annotate(r) for r in vol]
            annotated.sort(key=lambda x: (not x[0], -x[1]))
            if annotated:
                b = annotated[0][2]
                result["core_metrics"]["vol_regime"] = {
                    "q1": _num(b.get("q1_ic")), "q2": _num(b.get("q2_ic")), "q3": _num(b.get("q3_ic")),
                    "q4": _num(b.get("q4_ic")), "q5": _num(b.get("q5_ic")),
                    "sign_consistent": annotated[0][0], "pair": _pair_label(b),
                }
        # Zero: zero_analysis.csv — |t_stat| 最大
        zero = read_csv(Path(feval_dir) / "zero_analysis.csv")
        if zero:
            v, r = _pick_best_abs(zero, "t_stat") or (None, None)
            if v is not None:
                result["core_metrics"]["zero"] = {
                    "t_stat": v, "p_value": _num(r.get("p_value")),
                    "y_mean_x0": _num(r.get("y_mean_x0")), "y_mean_xnz": _num(r.get("y_mean_xnz")),
                    "pair": _pair_label(r),
                }
        # Train/Test: train_test.csv — same_sign + |test_ic| 最大
        tt = read_csv(Path(feval_dir) / "train_test.csv")
        if tt:
            same_sign = [r for r in tt if _bool(r.get("same_sign")) is True]
            candidates = same_sign or tt
            v, r = _pick_best_abs(candidates, "test_ic") or (None, None)
            if v is not None:
                result["core_metrics"]["train_test"] = {
                    "train_ic": _num(r.get("train_ic")), "test_ic": v,
                    "decay": _num(r.get("ic_decay")), "same_sign": _bool(r.get("same_sign")),
                    "pair": _pair_label(r),
                }

    # ---- 2b. bucket_analysis_summary.csv:可交易性 ----
    bucket_csv = _find_first(check_output, [
        "bucket_analysis_summary.csv", f"{xname}/dailyX/bucket_analysis_summary.csv",
    ])
    bucket_rows = read_csv(bucket_csv) if bucket_csv else None
    if bucket_rows:
        best = sorted(
            (r for r in bucket_rows if _num(r.get("sharpe_net_8bps")) is not None),
            key=lambda r: -abs(_num(r.get("sharpe_net_8bps"))),
        )
        if best:
            b = best[0]
            result["core_metrics"]["tradability"] = {
                "avg_turnover_per_day": _num(b.get("avg_turnover_per_day")),
                "sharpe_net_8bps": _num(b.get("sharpe_net_8bps")),
                "sharpe_net_16bps": _num(b.get("sharpe_net_16bps")),
                "veto3_cost_double": _bool(b.get("veto3_cost_double")),
                "capacity_risk": _bool(b.get("capacity_risk")),
                "pair": _pair_label(b),
            }

    # ---- 3. deep_summary.csv:因子级摘要(analysis + metric 映射)----
    deep_csv = _find_first(check_output, ["all_factors_deep_summary.csv"])
    deep_rows = read_csv(deep_csv) if deep_csv else None
    if deep_rows:
        for r in deep_rows:
            analysis = r.get("analysis")
            metric = r.get("metric")
            value = _num(r.get("value"))
            if value is None:
                continue
            if analysis == "Daily IC":
                result["deep_best"]["daily_ic_tstat"] = value
            elif analysis == "Rank IC":
                result["deep_best"]["rank_ic_max"] = value
            elif analysis == "Conditional Return" and metric == "best_annualized_sharpe":
                result["deep_best"]["conditional_sharpe"] = value
            elif analysis == "Conditional Return" and metric == "best_cum_ret_%":
                result["deep_best"]["cum_ret_pct"] = value
            elif analysis == "Signal Stability":
                result["deep_best"]["signal_instability_pct"] = value
            elif analysis == "Monthly IC" and metric == "best_icir":
                result["deep_best"]["monthly_icir"] = value
            elif analysis == "Monthly IC" and metric == "best_ic_mean":
                result["deep_best"]["monthly_ic_mean"] = value
            elif analysis == "Stationarity":
                result["stationarity"][metric] = value
            elif analysis == "Transform Family":
                result["transform_family"][metric] = value

    # ---- 4. csv_ic 分支(feval/deep 全缺时从平台 csv_ic 抽 IC 类)----
    if not result["core_metrics"].get("screening"):
        csv_summary = _find_first(check_output, [f"{xname}/csv_ic/csv_ic_summary.csv"])
        csv_rows = read_csv(csv_summary) if csv_summary else None
        if csv_rows:
            best = sorted(
                (r for r in csv_rows if _num(r.get("rank_icir")) is not None),
                key=lambda r: -abs(_num(r.get("rank_icir"))),
            )
            if best:
                b = best[0]
                result["core_metrics"]["screening"] = {
                    "ic_mean": _num(b.get("rank_ic_mean")), "icir": _num(b.get("rank_icir")),
                    "hit_rate": _num(b.get("hit_rate")), "n_days": _num(b.get("n_days")),
                    "horizon": _num(b.get("horizon")), "pearson_pooled": _num(b.get("pearson_pooled")),
                    "pair": f"{b.get('x_col', '')}@{b.get('horizon', '')}s",
                    "zero_rate": _num(b.get("zero_rate")), "active_rate": _num(b.get("active_rate")),
                    "pearson_nonzero": _num(b.get("pearson_nonzero")),
                }
                result["deep_best"]["daily_rank_ic"] = _num(b.get("rank_ic_mean"))
                result["deep_best"]["daily_icir"] = _num(b.get("rank_icir"))
            result["csv_ic"] = {
                "horizons": [{
                    "horizon": _num(r.get("horizon")), "rank_ic_mean": _num(r.get("rank_ic_mean")),
                    "rank_icir": _num(r.get("rank_icir")), "hit_rate": _num(r.get("hit_rate")),
                    "n_days": _num(r.get("n_days")), "zero_rate": _num(r.get("zero_rate")),
                    "active_rate": _num(r.get("active_rate")), "pearson_nonzero": _num(r.get("pearson_nonzero")),
                } for r in csv_rows],
                "source": "default_test/csv_ic",
            }
            # 逐日 IC 时序(csv_ic_ts.csv)
            csv_ts = _find_first(check_output, [f"{xname}/csv_ic/csv_ic_ts.csv"])
            if csv_ts:
                ts_rows = read_csv(csv_ts)
                if ts_rows:
                    result["csv_ic"]["daily_ts"] = ts_rows
            # 因子间相关性矩阵(csv_ic_xcorr.md 文本)
            csv_xcorr = _find_first(check_output, [f"{xname}/csv_ic/csv_ic_xcorr.md"])
            if csv_xcorr:
                try:
                    result["csv_ic"]["xcorr_md"] = Path(csv_xcorr).read_text(encoding="utf-8")
                except Exception:
                    pass

    return result


def extract_metrics_from_daily_ic(daily_ic_preview: str | None) -> dict:
    """从 daily_ic_results.txt 文本抽 4 数值(向后兼容,persist 用)。"""
    if not daily_ic_preview:
        return {}

    def find(regex: str):
        m = re.search(regex, str(daily_ic_preview), re.IGNORECASE)
        return float(m.group(1)) if m else None

    return {
        "ic_mean": find(r"IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "icir": find(r"ICIR[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "sharpe": find(r"Sharpe[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
        "rank_ic": find(r"Rank\s*IC[^a-zA-Z0-9]+(-?\d+\.?\d*(?:e[-+]?\d+)?)"),
    }


def max_zero_ratio_from_screening(check_output: str | Path, feature_key: str) -> float | None:
    """读 feval/screening.csv 的 zero_ratio max(0-1)。缺失/无数据 → None。"""
    screening_path = Path(check_output) / feature_key / "dailyX" / f"{feature_key}_feval" / "screening.csv"
    rows = read_csv(screening_path)
    if not rows:
        return None
    max_zero = 0.0
    for r in rows:
        z = _num(r.get("zero_ratio"))
        if z is not None and z > max_zero:
            max_zero = z
    return max_zero


def is_all_zero_from_screening(check_output: str | Path, feature_key: str) -> bool:
    """check_output_missing 时检测因子值是否全零(max_zero>=0.999 = DAG 缓存陷阱特征)。"""
    z = max_zero_ratio_from_screening(check_output, feature_key)
    return z is not None and z >= 0.999
