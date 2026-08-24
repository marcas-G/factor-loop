#!/usr/bin/env python3
"""Build multiplicity context for a factor evaluation card."""
from __future__ import annotations

ATTEMPT_STATUSES = ("evaluated", "dead_end", "failed")


def _attempt_status_counts(rows) -> dict[str, int]:
    counts = {status: 0 for status in ATTEMPT_STATUSES}
    for status in rows:
        if status in counts:
            counts[status] += 1
    return counts


def build_multiple_testing_context(
    conn,
    factor: dict,
    idea_id: int | None,
    current_factors: list | None = None,
    factor_index: int | None = None,
) -> dict:
    """Count prior attempts in the same idea lineage and current batch.

    Draft rows are excluded because they have not produced an evaluable result.
    The current run's candidates are added separately: each factor is assessed
    while its sibling candidates are also being tested on the same hypothesis.
    """
    current_factors = current_factors or [factor]
    current_batch_size = max(1, len(current_factors))

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
        "lineage_idea_id": idea_id,
        "lineage_prior_attempt_count": lineage_prior,
        "lineage_attempt_count_including_current_batch": lineage_prior + current_batch_size,
        "lineage_attempt_status_counts": _attempt_status_counts(lineage_status_rows),
        "current_batch_size": current_batch_size,
        "current_factor_index": factor_index,
        "counting_rule": (
            "prior counts persisted evaluated/dead_end/failed factors; "
            "current counts all candidates in this run"
        ),
    }
