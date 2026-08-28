#!/usr/bin/env python3
"""Snapshot collector for the factor dashboard (shared by API server and legacy generator)."""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DB_PATH  # noqa: E402
from core.db.db import (  # noqa: E402
    GATE_R2_MAX,
    NORM_IC_SAT,
    NORM_ICIR_SAT,
    NORM_RES_IC_SAT,
    leaderboard_gates,
)

DEFAULT_DB = DB_PATH


FACTOR_COLUMNS = [
    "xname", "class_name", "file_path", "formula_text", "params", "status",
    "verdict", "latest_ic", "latest_icir", "latest_sharpe", "latest_rank_ic",
    "latest_r2_x", "latest_res_ic", "created_ts",
    "last_updated_ts", "deprecated_at", "quality_score",
    "quality_grade", "intuition", "anchor_text", "origin_type", "cohort_tag",
    "operator_chain", "evaluation_status",
]


def _connect(db_path: Path | str) -> sqlite3.Connection:
    raw = str(db_path)
    if raw.startswith("file:"):
        # Pre-built URI (e.g. file:...?mode=ro&immutable=1): used when the db
        # sits on a read-only mount where SQLite must skip creating -shm/-wal.
        # Path.query sticks on "?" so split manually.
        path_part, _, query = raw.partition("?")
        fs_path = Path(path_part[len("file:"):]).expanduser().resolve()
        if not fs_path.is_file():
            raise FileNotFoundError(f"factor database not found: {raw}")
        uri = f"file:{fs_path}?{query}" if query else f"file:{fs_path}?mode=ro"
    else:
        fs_path = db_path.expanduser().resolve()
        if not fs_path.is_file():
            raise FileNotFoundError(f"factor database not found: {db_path}")
        uri = f"file:{fs_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_tables(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    required = {
        "factors", "factor_evals", "iteration_suggestions",
        "lessons", "tags", "factor_tags",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"database is missing factor tables: {', '.join(missing)}")


def _select_factors(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    available = _existing_columns(conn, "factors")
    columns = [column for column in FACTOR_COLUMNS if column in available]
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM factors ORDER BY last_updated_ts DESC, xname"
    )
    return [dict(row) for row in rows]


def _select_evals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, factor_xname, idea_id, ts, symbol, freq, ic_mean, icir,
                   sharpe, rank_ic, eval_metrics, eval_mode, significant, raw_path
            FROM factor_evals
            ORDER BY ts DESC, id DESC
            """
        )
    ]


def _select_iterations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.suggestion_id AS id, s.from_xname,
                   COALESCE(e.child_xname, s.from_xname) AS to_xname,
                   s.idea_id, s.change_note, s.reason,
                   e.outcome, e.icir_delta,
                   s.created_ts AS ts, s.status
            FROM iteration_suggestions s
            LEFT JOIN factor_lineage_edges e
              ON e.suggestion_id = s.suggestion_id AND e.origin = 'suggestion'
            ORDER BY s.created_ts DESC, s.suggestion_id DESC
            """
        )
    ]


def _select_lineage_edges(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT e.parent_xname, e.child_xname, e.relation_type, e.outcome,
                       e.confidence, e.op_id, o.name AS operator_name
                FROM factor_lineage_edges e
                LEFT JOIN operators o ON o.op_id = e.op_id
                ORDER BY e.parent_xname, e.child_xname
                """
            )
        ]
    except sqlite3.OperationalError:
        return []


def _select_lineage_branches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT root_xname, root_status, member_count, max_depth,
                       evaluated_count, dead_end_count
                FROM factor_lineage_branches
                ORDER BY member_count DESC, root_xname
                """
            )
        ]
    except sqlite3.OperationalError:
        return []


def _select_lessons(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, type, scope, text, evidence, idea_id, factor_xname,
                   created_ts, deprecated_at
            FROM lessons
            ORDER BY created_ts DESC, id DESC
            """
        )
    ]


def _select_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT ft.factor_xname, t.id AS tag_id, t.name, t.description
            FROM factor_tags ft
            JOIN tags t ON t.id = ft.tag_id
            ORDER BY t.name
            """
        )
    ]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _clean_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: _json_value(value) for key, value in record.items()}
        for record in records
    ]


def _attach_agg_scores(factors: list[dict[str, Any]]) -> None:
    """给每个因子补聚合闸门 + 分项分(与 factor_leaderboard 同一套常量与公式)。"""
    for factor in factors:
        passed, failed = leaderboard_gates(
            factor.get("latest_ic"), factor.get("latest_icir"),
            factor.get("latest_res_ic"), factor.get("latest_r2_x"),
        )
        factor["gate_pass"] = passed
        factor["failed_gates"] = failed
        ic, icir = factor.get("latest_ic"), factor.get("latest_icir")
        res_ic, r2 = factor.get("latest_res_ic"), factor.get("latest_r2_x")
        factor["s_ic"] = (
            min(abs(ic) / NORM_IC_SAT, 1.0)
            if isinstance(ic, (int, float)) else None
        )
        factor["s_icir"] = (
            min(abs(icir) / NORM_ICIR_SAT, 1.0)
            if isinstance(icir, (int, float)) else None
        )
        factor["s_res_ic"] = (
            min(abs(res_ic) / NORM_RES_IC_SAT, 1.0)
            if isinstance(res_ic, (int, float)) else None
        )
        factor["s_r2"] = (
            max((GATE_R2_MAX - r2) / GATE_R2_MAX, 0.0)
            if isinstance(r2, (int, float)) else None
        )
        parts = [factor["s_ic"], factor["s_icir"], factor["s_res_ic"], factor["s_r2"]]
        factor["agg_score"] = (
            round(sum(parts) / 4, 6) if all(p is not None for p in parts) else None
        )


def collect_snapshot(db_path: Path | str) -> dict[str, Any]:
    with _connect(db_path) as conn:
        _require_tables(conn)
        factors = _clean_records(_select_factors(conn))
        evals = _clean_records(_select_evals(conn))
        iterations = _clean_records(_select_iterations(conn))
        lineage_edges = _clean_records(_select_lineage_edges(conn))
        lineage_branches = _clean_records(_select_lineage_branches(conn))
        lessons = _clean_records(_select_lessons(conn))
        tags = _clean_records(_select_tags(conn))

    tags_by_factor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in tags:
        tags_by_factor[str(tag["factor_xname"])].append(
            {"name": tag["name"], "description": tag["description"]}
        )
    for factor in factors:
        factor["tags"] = tags_by_factor.get(str(factor["xname"]), [])
        ic = factor.get("latest_ic")
        residual_ic = factor.get("latest_res_ic")
        factor["resic_ic_ratio"] = (
            residual_ic / ic
            if isinstance(ic, (int, float))
            and isinstance(residual_ic, (int, float))
            and ic != 0
            else None
        )
    _attach_agg_scores(factors)

    raw_path = str(db_path)
    db_file = (
        Path(raw_path.partition("?")[0][len("file:"):])
        if raw_path.startswith("file:")
        else db_path
    ).expanduser().resolve()
    return {
 "factors": factors,
        "evaluations": evals,
        "iterations": iterations,
        "lineage_edges": lineage_edges,
        "lineage_branches": lineage_branches,
        "lessons": lessons,
        "meta": {
            "dbPath": str(db_file),
            "dbModifiedAt": datetime.fromtimestamp(
                db_file.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
    }
