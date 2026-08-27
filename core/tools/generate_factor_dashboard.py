#!/usr/bin/env python3
"""Generate a self-contained static HTML dashboard for the factor library.

The output has no CDN, JavaScript dependency, or server requirement. Refresh it
after factor evaluation by rerunning this command and opening the HTML file.
"""
from __future__ import annotations

import argparse
import json
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

DEFAULT_OUTPUT = DB_PATH.parent / "factor_dashboard.html"


FACTOR_COLUMNS = [
    "xname", "class_name", "file_path", "formula_text", "params", "status",
    "verdict", "latest_ic", "latest_icir", "latest_sharpe", "latest_rank_ic",
    "latest_r2_x", "latest_res_ic", "created_ts",
    "last_updated_ts", "deprecated_at", "quality_score",
    "quality_grade", "intuition", "anchor_text", "origin_type", "cohort_tag",
    "operator_chain", "evaluation_status",
]


def _connect(db_path: Path) -> sqlite3.Connection:
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


def collect_snapshot(db_path: Path) -> dict[str, Any]:
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


TEMPLATE_DIR = Path(__file__).resolve().parent / "dashboard_template"


def _read_template(rel: str) -> str:
    path = TEMPLATE_DIR / rel
    if not path.is_file():
        raise FileNotFoundError(f"dashboard template part missing: {path}")
    return path.read_text(encoding="utf-8")




def render_html(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).replace("</", "<\\/")
    vendor_path = TEMPLATE_DIR / "vendor" / "d3-hierarchy.min.js"
    vendor = vendor_path.read_text(encoding="utf-8") if vendor_path.is_file() else ""
    return (_read_template("template.html")
            .replace("__VENDOR__", vendor)
            .replace("__CSS__", _read_template("style.css"))
            .replace("__JS__", _read_template("app.js"))
            .replace("__GENERATED_AT__",
                     snapshot.get("meta", {}).get("generatedAt", ""))
            .replace("__DATA__", payload))


def write_atomic(output_path: Path, html: str) -> None:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained static factor-library dashboard"
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite factor database")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="output HTML path (default: data/factor_dashboard.html)",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="try to open the generated page with the local desktop browser",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        snapshot = collect_snapshot(args.db)
        html = render_html(snapshot)
        write_atomic(args.output, html)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    output_path = args.output.expanduser().resolve()
    print(f"Factor dashboard written: {output_path}")
    print(f"Factors: {len(snapshot['factors'])}; size: {output_path.stat().st_size / 1024:.1f} KiB")
    if args.open:
        import webbrowser

        webbrowser.open(output_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
