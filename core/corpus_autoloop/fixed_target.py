"""Preselected X/Y metric extraction from *raw* platform screening.csv.

The standard platform summary selects the highest scoring pair from the
submitted window. That is useful on discovery/screening data but INVALID on
an untouched holdout. This function instead retrieves the frozen X/Y pair
(or frozen Y with exactly one X candidate), rejecting missing/ambiguous rows.
"""
from __future__ import annotations

import math
from pathlib import Path

from .execution_adapter import EvidenceError
from core.metrics import read_csv


def _finite_number(value, label):
    try:
        out=float(value)
    except (ValueError,TypeError) as exc:
        raise EvidenceError(f"invalid raw CSV metric {label}") from exc
    if not math.isfinite(out):
        raise EvidenceError(f"nonfinite raw CSV metric {label}")
    return out


def fixed_target_score(checked: dict, source_file: str | Path, *,
                       target: str, exact_pair: str | None = None) -> dict:
    """Return metrics for predeclared target, never the best heldout pair.

    All parameters are derived from the runner's completed check and existing
    source file; no model-supplied metric is accepted. Only one X/Y row is
    allowed for the target (unless exact_pair explicitly selects one).
    """
    if checked.get("failureLayer") != "check_done":
        raise EvidenceError("holdout check has not completed")
    if not isinstance(target,str) or not target.strip():
        raise EvidenceError("predeclared Y target is mandatory")
    output = checked.get("checkOutput")
    if not output:
        raise EvidenceError("actual platform checkOutput folder is mandatory")
    root=Path(output).expanduser().resolve()
    stem=Path(source_file).stem
    candidate=root/stem/"dailyX"/(stem+"_feval")/"screening.csv"
    if not candidate.is_file():
        raise EvidenceError(f"expected raw holdout screening.csv missing: {candidate}")
    rows=read_csv(candidate)
    if not rows:
        raise EvidenceError("raw holdout screening.csv empty")
    matching=[]
    for row in rows:
        x=(row.get("x_col") or "").strip()
        y=(row.get("y_col") or "").strip()
        if y != target.strip():
            continue
        name=f"{x} vs {y}"
        if exact_pair is None or name==exact_pair.strip():
            matching.append((row,name))
    if len(matching)!=1:
        raise EvidenceError(
            f"expected exactly one predeclared holdout X/Y row, got {len(matching)}")
    row,pair=matching[0]
    zero=_finite_number(row.get("zero_ratio"),"zero_ratio")
    if not 0<=zero<=1:
        raise EvidenceError("zero_ratio outside 0..1")
    if zero>=0.5:
        # Daily ICIR in generic deep_best is selected independently from all
        # pairs. Do not re-use that best result for this frozen target.
        raise EvidenceError(
            "sparse holdout needs per-target daily ICIR; generic deep_best is not valid")
    return {
        "pair":pair,"target":target.strip(),
        "icir":_finite_number(row.get("ic_ir"),"ic_ir"),
        "rank_ic":_finite_number(row.get("spearman_r"),"spearman_r"),
        "zero_ratio":zero,
        "csv_path":str(candidate),
    }
