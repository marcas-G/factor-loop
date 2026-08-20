#!/usr/bin/env python3
"""Build multiplicity context for a factor evaluation card."""
from __future__ import annotations

from core.db.db import infer_angle_code


ATTEMPT_STATUSES = ("evaluated", "dead_end", "failed")


def _attempt_status_counts(rows) -> dict[str, int]:
    counts = {status: 0 for status in ATTEMPT_STATUSES}
    for status in rows:
        if status in counts:
            counts[status] += 1
    return counts


def _infer_factor_angle(factor: dict) -> str | None:
    tags = factor.get("tags") or []
    if not isinstance(tags, (list, tuple)):
        tags = [tags]
    return infer_angle_code(factor.get("formula"), tags, factor.get("name"))


def build_multiple_testing_context(
    conn,
    factor: dict,
    idea_id: int | None,
    current_factors: list | None = None,
    factor_index: int | None = None,
) -> dict:
    """Count prior attempts in the same angle and idea lineage.

    Draft rows are excluded because they have not produced an evaluable result.
    The current run's candidates are added separately: each factor is assessed
    while its sibling candidates are also being tested on the same hypothesis.
    """
    current_factors = current_factors or [factor]
    current_batch_size = max(1, len(current_factors))

    angle = None
    angle_source = "inferred"
    if idea_id is not None:
        row = conn.execute(
            "SELECT angle_code FROM ideas WHERE id=?", (idea_id,)
        ).fetchone()
        if row and row[0]:
            angle = row[0]
            angle_source = "idea"
    if not angle:
        angle = _infer_factor_angle(factor)

    angle_prior = 0
    angle_status_rows = []
    if angle:
        placeholders = ",".join("?" for _ in ATTEMPT_STATUSES)
        angle_status_rows = [
            r[0]
            for r in conn.execute(
                f"""SELECT f.status
                    FROM factors f
                    WHERE f.angle_code=? AND f.deprecated_at IS NULL
                      AND f.status IN ({placeholders})""",
                (angle, *ATTEMPT_STATUSES),
            ).fetchall()
        ]
        angle_prior = len(angle_status_rows)

    if angle and angle_source == "idea":
        current_angle_attempts = current_batch_size
    elif angle:
        current_angle_attempts = sum(
            1 for candidate in current_factors
            if _infer_factor_angle(candidate or {}) == angle
        ) or 1
    else:
        current_angle_attempts = 1

    lineage_prior = 0
    lineage_status_rows = []
    if idea_id is not None:
        placeholders = ",".join("?" for _ in ATTEMPT_STATUSES)
        lineage_status_rows = [
            r[0]
            for r in conn.execute(
                f"""SELECT f.status
                    FROM idea_factor_links ifl
                    JOIN factors f ON f.xname=ifl.factor_xname
                    WHERE ifl.idea_id=? AND f.deprecated_at IS NULL
                      AND f.status IN ({placeholders})""",
                (idea_id, *ATTEMPT_STATUSES),
            ).fetchall()
        ]
        lineage_prior = len(lineage_status_rows)

    return {
        "available": True,
        "angle_code": angle,
        "angle_source": angle_source if angle else "unmatched",
        "angle_prior_attempt_count": angle_prior,
        "angle_attempt_count_including_current": angle_prior + current_angle_attempts,
        "angle_attempt_status_counts": _attempt_status_counts(angle_status_rows),
        "lineage_idea_id": idea_id,
        "lineage_prior_attempt_count": lineage_prior,
        "lineage_attempt_count_including_current_batch": lineage_prior + current_batch_size,
        "lineage_attempt_status_counts": _attempt_status_counts(lineage_status_rows),
        "current_batch_size": current_batch_size,
        "current_batch_angle_attempt_count": current_angle_attempts,
        "current_factor_index": factor_index,
        "counting_rule": (
            "prior counts persisted evaluated/dead_end/failed factors; "
            "current counts all candidates in this run"
        ),
    }
