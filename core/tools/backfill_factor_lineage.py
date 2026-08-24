#!/usr/bin/env python3
"""Backfill factor lineage from explicit run state and exact idea-text references."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DB_PATH
from core.db import db


def _iter_run_states(runs_root: Path):
    for path in sorted(runs_root.glob("*/state.json")):
        try:
            with path.open(encoding="utf-8") as f:
                yield path.parent.name, json.load(f)
        except (OSError, json.JSONDecodeError):
            continue


def _exact_factor_refs(text: str, identifiers: list[str]) -> set[str]:
    refs = set()
    for identifier in identifiers:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(identifier)}(?![A-Za-z0-9_])"
        if re.search(pattern, text or ""):
            refs.add(identifier)
    return refs


def backfill(
    conn: sqlite3.Connection,
    runs_root: Path,
    *,
    dry_run: bool = False,
) -> dict:
    factor_rows = conn.execute(
        "SELECT xname, class_name, created_ts FROM factors ORDER BY xname"
    ).fetchall()
    factors = {r["xname"]: r["created_ts"] for r in factor_rows}
    class_names = {r["class_name"] for r in factor_rows if r["class_name"]}
    class_to_factors: dict[str, list[str]] = {}
    for row in factor_rows:
        if row["class_name"]:
            class_to_factors.setdefault(row["class_name"], []).append(row["xname"])
    explicit = 0
    textual = 0
    operator_marker = 0
    skipped = []

    # Highest-confidence source: run state explicitly says which existing factor this
    # candidate iterates from.
    for run_id, state in _iter_run_states(runs_root):
        for factor in state.get("factors") or []:
            source = factor.get("iterates_from")
            target = factor.get("name")
            if not source or not target or source == target:
                continue
            if source not in factors or target not in factors:
                continue
            if dry_run:
                explicit += 1
                continue
            db.add_lineage_edge(
                conn,
                source,
                target,
                relation_type="iteration",
                origin="manual_backfill",
                idea_id=state.get("idea_id"),
                evidence={"method": "run_state_iterates_from"},
                confidence="declared",
            )
            explicit += 1

    # Cog research ideas often encode their Research Object in the idea text. Only exact,
    # currently-persisted factor identifiers are accepted; outputs linked to that idea are
    # excluded from source candidates.
    idea_rows = conn.execute("""
        SELECT i.id AS idea_id, i.text AS text,
               GROUP_CONCAT(l.factor_xname) AS outputs
        FROM ideas i
        LEFT JOIN idea_factor_links l ON l.idea_id=i.id
        GROUP BY i.id, i.text
    """).fetchall()
    for row in idea_rows:
        outputs = set((row["outputs"] or "").split(","))
        output_identifiers = outputs | {
            class_name for xname in outputs if (class_name := next(
                (r["class_name"] for r in factor_rows if r["xname"] == xname), None
            ))
        }
        refs = _exact_factor_refs(
            row["text"] or "",
            sorted(set(factors) | class_names, key=len, reverse=True),
        ) - output_identifiers
        resolved_refs = set()
        for ref in refs:
            if ref in factors:
                resolved_refs.add(ref)
            elif len(class_to_factors.get(ref, [])) == 1:
                # A unique class name is a stable alias when the research object was
                # referenced without its parameterized xname.
                resolved_refs.add(class_to_factors[ref][0])
        refs = resolved_refs
        for target in outputs:
            if target not in factors:
                continue
            for source in refs:
                if source == target:
                    continue
                # A source normally predates its derivation. Skip clear time-order
                # violations instead of forcing a wrong edge.
                # Some legacy rows contain date-only values while others contain full
                # timestamps; lexical comparison falsely treats date-only as earlier.
                source_ts, target_ts = factors[source], factors[target]
                same_day = bool(source_ts and target_ts and source_ts[:10] == target_ts[:10])
                if (
                    not same_day
                    and source_ts and target_ts
                    and len(source_ts) > 10 and len(target_ts) > 10
                    and source_ts > target_ts
                ):
                    skipped.append({"source": source, "target": target, "reason": "time_order"})
                    continue
                if dry_run:
                    textual += 1
                    continue
                db.add_lineage_edge(
                    conn,
                    source,
                    target,
                    relation_type="repair",
                    origin="cog_repair",
                    idea_id=row["idea_id"],
                    evidence={
                        "method": "idea_text_exact_factor_reference",
                        "idea_id": row["idea_id"],
                    },
                    confidence="inferred",
                )
                textual += 1

        # Operator contracts can carry a canonical research_object in source_ref. This
        # recovers later batches whose idea text references only the operator shorthand.
        for op in conn.execute(
            "SELECT op_id, name, source_ref FROM operators ORDER BY op_id"
        ).fetchall():
            marker = f"{op['name']}(op{op['op_id']})"
            if marker not in (row["text"] or ""):
                continue
            match = re.search(r"research_object:([A-Za-z0-9_]+)", op["source_ref"] or "")
            if not match or match.group(1) not in factors:
                continue
            source = match.group(1)
            for target in outputs:
                if target not in factors or target == source:
                    continue
                if conn.execute(
                    """SELECT 1 FROM factor_lineage_edges
                       WHERE parent_xname=? AND child_xname=? LIMIT 1""",
                    (source, target),
                ).fetchone():
                    conn.execute(
                        """UPDATE factor_lineage_edges
                           SET confidence='declared', op_id=?
                           WHERE parent_xname=? AND child_xname=?
                             AND relation_type='operator_application'""",
                        (op["op_id"], source, target),
                    )
                    continue
                if dry_run:
                    operator_marker += 1
                    continue
                db.add_lineage_edge(
                    conn,
                    source,
                    target,
                    relation_type="operator_application",
                    origin="operator_contract",
                    idea_id=row["idea_id"],
                    op_id=op["op_id"],
                    evidence={
                        "method": "operator_source_ref_research_object",
                        "marker": marker,
                    },
                    confidence="declared",
                )
                operator_marker += 1

    if not dry_run:
        db.rebuild_factor_lineage(conn)
    return {"explicit_run_state_edges": explicit, "idea_text_edges": textual,
            "operator_marker_edges": operator_marker,
            "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--runs-root", default=str(Path.home() / ".quant-runs"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with db.get_conn(args.db) as conn:
        result = backfill(conn, Path(args.runs_root), dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
