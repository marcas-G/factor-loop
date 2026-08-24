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
    db_path = db_path.expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"factor database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
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

    db_file = db_path.expanduser().resolve()
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


CSS = r"""
:root {
  color-scheme: light;
  --ink: #18212b;
  --muted: #667085;
  --subtle: #8792a2;
  --line: #d9e0e8;
  --background: #f4f6f8;
  --surface: #ffffff;
  --surface-2: #eef2f6;
  --accent: #0f766e;
  --accent-soft: #d9f0ed;
  --blue: #2563eb;
  --red: #dc2626;
  --amber: #b45309;
  --violet: #7c3aed;
  --shadow: 0 1px 4px rgba(16, 24, 40, .08);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; overflow-x: hidden; }
body {
  min-height: 100vh;
  background: var(--background);
  color: var(--ink);
  font-size: 14px;
  line-height: 1.5;
}
button, input, select { font: inherit; color: inherit; }
button { cursor: pointer; }
.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid var(--line);
  background: rgba(255,255,255,.96);
  backdrop-filter: blur(8px);
}
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1560px;
  min-height: 64px;
  margin: 0 auto;
  padding: 10px 24px;
}
.brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border: 1px solid #b9d5d1;
  border-radius: 7px;
  background: #e7f4f2;
  color: #075e57;
  font-weight: 750;
}
.brand h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
}
.brand p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.icon-button {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}
.icon-button:hover { border-color: #a9b6c5; background: var(--surface-2); }
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  max-width: 1560px;
  margin: 0 auto;
  padding: 18px 24px 36px;
}
.layout > * { min-width: 0; }
.main-column { min-width: 0; }
.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.metric {
  min-height: 84px;
  padding: 13px 14px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.metric dt { margin: 0; color: var(--muted); font-size: 12px; }
.metric dd { margin: 7px 0 0; font-size: 24px; font-weight: 700; line-height: 1.1; }
.metric small { display: block; margin-top: 5px; color: var(--subtle); font-size: 11px; }
.section {
  margin-bottom: 14px;
  padding: 14px;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.section-header h2 { margin: 0; font-size: 15px; }
.section-header span { color: var(--muted); font-size: 12px; }
.chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(240px, .75fr);
  gap: 14px;
  align-items: stretch;
}
.chart-box { min-width: 0; border: 1px solid var(--line); border-radius: 6px; background: #fbfcfe; }
.chart-box svg { display: block; width: 100%; height: auto; }
.chart-title {
  padding: 9px 11px 0;
  margin: 0;
  color: #42515f;
  font-size: 12px;
  font-weight: 650;
}
.chart-note { padding: 0 11px 9px; margin: 0; color: var(--subtle); font-size: 11px; }
.lineage-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.lineage-controls .control { width: min(260px, 34vw); }
.lineage-stage {
  position: relative;
  height: 560px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background:
    linear-gradient(180deg, rgba(244, 246, 248, .4), rgba(255, 255, 255, 0) 46%),
    #fbfcfe;
}
#lineageChart {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
  touch-action: none;
}
#lineageChart.dragging { cursor: grabbing; }
.lineage-legend {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  max-width: 62%;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, .9);
  box-shadow: var(--shadow);
  font-size: 11px;
  color: #42515f;
  pointer-events: none;
}
.lineage-legend i {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 4px;
  border-radius: 3px;
  vertical-align: -1px;
}
.lineage-hint {
  position: absolute;
  right: 10px;
  bottom: 9px;
  max-width: 44%;
  padding: 5px 9px;
  border-radius: 6px;
  background: rgba(238, 242, 246, .94);
  color: var(--subtle);
  font-size: 11px;
  pointer-events: none;
}
.lineage-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--subtle);
}
.lineage-empty[hidden] { display: none; }
.graph-node { cursor: pointer; }
.graph-node rect {
  stroke-width: 1.5;
  filter: drop-shadow(0 2px 3px rgba(16, 24, 40, .08));
  transition: stroke-width .12s ease, filter .12s ease;
}
.graph-node:hover rect { stroke-width: 2.2; filter: drop-shadow(0 3px 6px rgba(16, 24, 40, .16)); }
.graph-node.selected rect { stroke-width: 2.5; }
.graph-node text {
  pointer-events: none;
  fill: #1f2a37;
  font-size: 10.5px;
  font-weight: 650;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.graph-node .node-status {
  font-size: 9px;
  font-weight: 600;
  fill: #667085;
}
.graph-edge {
  stroke: #8da0b3;
  stroke-opacity: .55;
  stroke-width: 1.4;
  marker-end: url(#lineageArrow);
}
.graph-edge.improved { stroke: #12805c; stroke-opacity: .72; }
.graph-edge.declined { stroke: #c2410c; stroke-opacity: .72; }
.graph-edge.operator-edge {
  stroke: #0f766e;
  stroke-opacity: .8;
  stroke-dasharray: 6 3;
}
.controls {
  display: grid;
  grid-template-columns: minmax(220px, 1.6fr) repeat(3, minmax(120px, 1fr)) auto;
  gap: 8px;
  margin-bottom: 12px;
}
.sort-header {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
  width: 100%;
  min-height: 34px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: #526273;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}
th:first-child .sort-header { justify-content: flex-start; }
.sort-header:hover { color: var(--ink); }
.sort-badge {
  display: inline-block;
  min-width: 18px;
  margin-left: 4px;
  padding: 1px 4px;
  border-radius: 4px;
  background: #d9f0ed;
  color: #0b5f58;
  font-size: 10px;
  text-align: center;
}
.control, .search {
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}
.search { padding: 0 10px; }
.control { padding: 0 8px; }
.control:focus, .search:focus, .icon-button:focus-visible, .action:focus-visible {
  outline: 2px solid #7fb7b1;
  outline-offset: 1px;
}
.action {
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  font-weight: 600;
}
.action:hover { background: var(--surface-2); }
.table-wrap { max-width: 100%; overflow-x: auto; }
table { width: 100%; min-width: 980px; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: right; vertical-align: middle; white-space: nowrap; }
th { position: sticky; top: 0; z-index: 2; background: #f8fafb; color: #526273; font-size: 12px; }
th:first-child, td:first-child { text-align: left; }
tbody tr:hover { background: #f6faf9; }
tbody tr.selected { background: #e8f4f2; }
.factor-cell { max-width: 340px; white-space: normal; }
.factor-title { display: flex; align-items: center; gap: 6px; min-width: 0; }
.factor-title button {
  max-width: 100%;
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 650;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.factor-title button:hover { color: var(--accent); text-decoration: underline; }
.factor-subtitle {
  overflow: hidden;
  color: var(--muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag-row { display: flex; gap: 4px; margin-top: 4px; overflow: hidden; }
.tag {
  max-width: 110px;
  overflow: hidden;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-2);
  color: #4d5766;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.badge {
  display: inline-block;
  min-width: 58px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 650;
  text-align: center;
}
.evaluated { background: #dcfce7; color: #166534; }
.dead_end { background: #fee2e2; color: #991b1b; }
.draft { background: #e0edff; color: #1e40af; }
.submitted { background: #fef3c7; color: #92400e; }
.failed { background: #f3e8ff; color: #6b21a8; }
.verdict-pass { background: #dcfce7; color: #166534; }
.verdict-fail { background: #fee2e2; color: #991b1b; }
.number { font-variant-numeric: tabular-nums; }
.pos { color: #047857; font-weight: 650; }
.neg { color: #be123c; font-weight: 650; }
.empty { padding: 34px; color: var(--muted); text-align: center; }
.detail-panel {
  display: none;
}
.inline-detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  padding: 14px 14px 18px;
  border-top: 2px solid var(--accent);
  background: #f8fafb;
}
.inline-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  grid-column: 1 / -1;
}
.inline-detail .detail-section {
  grid-column: span 1;
  min-width: 0;
  margin-top: 0;
}
.inline-detail .detail-section.full { grid-column: 1 / -1; }
.inline-detail .tag-row, .inline-detail .detail-grid { grid-column: 1 / -1; }
.inline-detail .detail-section h3 { margin-top: 0; }
.inline-detail .detail-table { margin-top: 2px; font-size: 11.5px; }
.inline-detail .detail-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); margin: 0; }
.inline-detail .detail-metric { padding: 6px 7px; }
.inline-detail .detail-metric strong { font-size: 13px; }
.inline-detail pre { max-height: 190px; }
.inline-detail .lesson { max-height: 220px; overflow: auto; }
.expanded-row td { padding: 0 !important; background: #f8fafb; }
.chevron {
  display: inline-block;
  width: 14px;
  color: var(--accent);
  font-size: 11px;
}
.detail-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.detail-title { min-width: 0; }
.detail-title h2 {
  margin: 0;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 15px;
}
.detail-title p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 14px 0;
}
.detail-metric { padding: 8px 9px; border: 1px solid var(--line); border-radius: 5px; background: #fbfcfe; }
.detail-metric span { display: block; color: var(--muted); font-size: 11px; }
.detail-metric strong { display: block; margin-top: 2px; font-size: 14px; }
.detail-section { margin-top: 16px; }
.detail-section h3 { margin: 0 0 7px; font-size: 13px; }
pre {
  max-height: 280px;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: #f8fafb;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.detail-table { width: 100%; min-width: 0; }
.detail-table th, .detail-table td { min-width: 0; padding: 6px 4px; font-size: 11.5px; white-space: normal; }
.detail-table th:first-child, .detail-table td:first-child { text-align: left; }
.lesson {
  margin-bottom: 8px;
  padding: 9px;
  border-left: 3px solid var(--line);
  border-radius: 4px;
  background: #f8fafb;
  font-size: 12px;
}
.lesson.success_pattern { border-left-color: #16a34a; }
.lesson.dead_end { border-left-color: #dc2626; }
.lesson strong { display: block; margin-bottom: 3px; }
.lesson p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.placeholder {
  display: grid;
  place-items: center;
  min-height: 300px;
  color: var(--muted);
  text-align: center;
}
.status-line {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 11px;
}
.footer {
  max-width: 1560px;
  margin: 0 auto;
  padding: 0 24px 28px;
  color: var(--muted);
  font-size: 11px;
}
.sr-only {
  position: absolute;
  width: 1px; height: 1px;
  margin: -1px; padding: 0;
  overflow: hidden;
  clip: rect(0,0,0,0);
  border: 0;
}
@media (max-width: 1220px) {
  .metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .layout { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 780px) {
  body.sheet-open { overflow: hidden; }
  .header-row { align-items: flex-start; flex-direction: column; padding: 12px 14px; }
  .brand p { max-width: 100%; }
  .header-actions { width: 100%; justify-content: flex-end; }
  .layout { padding: 12px 10px 26px; }
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .section { padding: 10px; border-radius: 6px; }
  .chart-grid { grid-template-columns: minmax(0, 1fr); }
  .controls { grid-template-columns: minmax(0, 1fr); }
  .table-wrap { margin: 0 -10px; }
  .factor-cell { max-width: 220px; }
  .detail-panel {
    position: fixed;
    right: 8px;
    bottom: 8px;
    left: 8px;
    z-index: 40;
    display: none;
    max-height: min(80vh, 680px);
    border-radius: 8px;
    box-shadow: 0 12px 40px rgba(16, 24, 40, .28);
  }
  .detail-panel.open { display: block; }
}
@media print {
  .header-actions, .controls, .table-wrap { display: none; }
  .layout { display: block; }
  .detail-panel {
    position: static;
    display: block;
    overflow: visible;
    max-height: none;
    border: 0;
    box-shadow: none;
  }
}
"""


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>因子库静态看板</title>
<style>__CSS__</style>
</head>
<body>
<header class="app-header">
  <div class="header-row">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">F</div>
      <div>
        <h1>因子库静态看板</h1>
        <p id="dbMeta"></p>
      </div>
    </div>
    <div class="header-actions">
      <button class="icon-button" id="refreshHint" type="button" title="刷新方式：重新执行生成命令" aria-label="刷新方式">↻</button>
      <button class="icon-button" id="printButton" type="button" title="打印当前看板" aria-label="打印">⎙</button>
    </div>
  </div>
</header>

<main class="layout">
  <div class="main-column">
    <dl class="metrics" id="metricCards"></dl>

    <section class="section" aria-labelledby="overviewTitle">
      <div class="section-header">
        <h2 id="overviewTitle">库内概览</h2>
        <span>横轴为库内解释方差 R²，纵轴为 |ICIR|；点击圆点查看因子</span>
      </div>
      <div class="chart-grid">
        <figure class="chart-box" id="scatterBox" aria-label="冗余度与预测强度散点图">
          <p class="chart-title">冗余度 × 预测强度</p>
          <svg id="scatterChart" viewBox="0 0 720 355" role="img"></svg>
        </figure>
        <figure class="chart-box" id="statusBox" aria-label="因子状态分布">
          <p class="chart-title">状态分布</p>
          <svg id="statusChart" viewBox="0 0 320 355" role="img"></svg>
        </figure>
      </div>
    </section>

    <section class="section" aria-labelledby="lineageTitle">
      <div class="section-header">
        <div>
          <h2 id="lineageTitle">血缘图谱</h2>
          <span id="lineageMeta">拖拽平移，滚轮缩放，点击节点查看因子</span>
        </div>
        <div class="lineage-controls">
          <label class="sr-only" for="lineageBranchFilter">分支</label>
          <select class="control" id="lineageBranchFilter"></select>
          <button class="action" id="lineageFitButton" type="button">适应</button>
          <button class="action" id="lineageResetButton" type="button">重置</button>
        </div>
      </div>
      <div class="lineage-stage" id="lineageStage">
        <svg id="lineageChart" role="img" aria-label="因子血缘关系图"></svg>
        <div class="lineage-legend" aria-hidden="true">
          <span><i style="background:#12805c"></i>已评估</span>
          <span><i style="background:#c2410c"></i>放弃</span>
          <span><i style="background:#2563eb"></i>草稿</span>
          <span><i style="background:#b7791f"></i>已提交</span>
          <span><i style="background:#7c3aed"></i>失败</span>
          <span style="display:inline-flex;align-items:center;gap:4px"><i style="background:#0f766e;border-radius:2px;height:2px;width:14px;margin-right:0"></i>算子应用</span>
        </div>
        <div class="lineage-hint">滚轮缩放 · 拖拽平移 · 点击节点查看详情</div>
        <div class="lineage-empty" id="lineageEmpty" hidden>暂无血缘数据</div>
      </div>
    </section>

    <section class="section" aria-labelledby="factorTitle">
      <div class="section-header">
        <div>
          <h2 id="factorTitle">因子列表</h2>
          <span id="resultCount"></span>
        </div>
        <button class="action" id="exportButton" type="button">CSV</button>
      </div>
      <div class="controls">
        <label class="sr-only" for="searchInput">搜索</label>
        <input class="search" id="searchInput" type="search" placeholder="搜索因子、公式、标签或意图">
        <label class="sr-only" for="statusFilter">状态</label>
        <select class="control" id="statusFilter"></select>
        <label class="sr-only" for="tagFilter">标签</label>
        <select class="control" id="tagFilter"></select>
        <button class="action" id="resetButton" type="button">重置</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th><button class="sort-header" data-key="xname" data-label="因子" type="button"></button></th>
              <th><button class="sort-header" data-key="verdict" data-label="结论" type="button"></button></th>
              <th><button class="sort-header" data-key="latest_ic" data-label="IC" type="button"></button></th>
              <th><button class="sort-header" data-key="latest_icir" data-label="ICIR" type="button"></button></th>
              <th><button class="sort-header" data-key="latest_r2_x" data-label="R²" type="button"></button></th>
              <th><button class="sort-header" data-key="latest_res_ic" data-label="残差IC" type="button"></button></th>
              <th><button class="sort-header" data-key="resic_ic_ratio" data-label="残差IC/IC" type="button"></button></th>
              <th><button class="sort-header" data-key="last_updated_ts" data-label="更新时间" type="button"></button></th>
            </tr>
          </thead>
          <tbody id="factorRows"></tbody>
        </table>
      </div>
      <div class="empty" id="emptyMessage" hidden>没有匹配的因子</div>
    </section>
  </div>

  <aside class="detail-panel" id="detailPanel" aria-live="polite"></aside>
</main>
<footer class="footer" id="footerMeta"></footer>

<script>
window.FACTOR_DASHBOARD_DATA = __DATA__;
</script>
<script>
"use strict";
const DATA = window.FACTOR_DASHBOARD_DATA;
const byName = new Map(DATA.factors.map(f => [f.xname, f]));
const evalsByName = new Map();
const iterationsByName = new Map();
const lessonsByName = new Map();
for (const ev of DATA.evaluations) {
  if (!evalsByName.has(ev.factor_xname)) evalsByName.set(ev.factor_xname, []);
  evalsByName.get(ev.factor_xname).push(ev);
}
for (const it of DATA.iterations) {
  for (const name of new Set([it.from_xname, it.to_xname])) {
    if (!iterationsByName.has(name)) iterationsByName.set(name, []);
    iterationsByName.get(name).push(it);
  }
}
for (const lesson of DATA.lessons) {
  if (!lessonsByName.has(lesson.factor_xname)) lessonsByName.set(lesson.factor_xname, []);
  lessonsByName.get(lesson.factor_xname).push(lesson);
}
const state = {
  query: "",
  status: "all",
  tag: "all",
  sort: null,
  selected: null
};
const STATUS_LABELS = {
  evaluated: "已评估",
  dead_end: "放弃",
  draft: "草稿",
  submitted: "已提交",
  failed: "失败"
};
const STATUS_COLORS = {
  evaluated: "#12805c",
  dead_end: "#c2410c",
  draft: "#2563eb",
  submitted: "#b7791f",
  failed: "#7c3aed"
};
const VERDICT_LABELS = {
  pass: "通过",
  fail: "失败"
};
function esc(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function conclusionOf(f) {
  if (f.status === "evaluated") return "pass";
  if (f.status === "dead_end") return "fail";
  return f.verdict || "";
}
function verdictLabel(f) {
  return conclusionOf(f) ? (VERDICT_LABELS[conclusionOf(f)] || conclusionOf(f)) : "未评估";
}
function verdictBadge(f) {
  const conclusion = conclusionOf(f);
  if (conclusion === "pass" || conclusion === "fail") {
    return `<span class="badge verdict-${esc(conclusion)}">${esc(VERDICT_LABELS[conclusion] || conclusion)}</span>`;
  }
  return `<span class="badge ${esc(f.status)}">${esc(STATUS_LABELS[f.status] || f.status)}</span>`;
}
function fmt(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 10000) return n.toLocaleString("zh-CN", {maximumFractionDigits: 1});
  return n.toFixed(digits);
}
function pct(value) { return value === null || value === undefined ? "—" : fmt(value * 100, 2) + "%"; }
function cls(value) { return value > 0 ? "pos" : value < 0 ? "neg" : ""; }
function shortTime(value) {
  if (!value) return "—";
  const d = new Date(value.includes("T") ? value + (value.endsWith("Z") ? "" : "Z") : value.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return esc(value);
  return d.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
}
function fullTime(value) {
  if (!value) return "—";
  return esc(value);
}
function uniqueStatuses() {
  return [...new Set(DATA.factors.map(f => f.status))].sort();
}
function uniqueTags() {
  const counts = new Map();
  for (const f of DATA.factors) for (const t of f.tags || []) {
    counts.set(t.name, (counts.get(t.name) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
function searchFactor(factor) {
  if (state.status !== "all" && factor.status !== state.status) return false;
  if (state.tag !== "all" && !(factor.tags || []).some(t => t.name === state.tag)) return false;
  if (!state.query) return true;
  const q = state.query.toLowerCase();
  return [factor.xname, factor.class_name, factor.formula_text, factor.intuition,
          factor.status, factor.verdict, ...(factor.tags || []).map(t => t.name)]
    .filter(Boolean).some(v => String(v).toLowerCase().includes(q));
}
function useInlineDetails() {
  return !window.matchMedia("(max-width: 780px)").matches;
}
function toggleSelected(xname) {
  state.selected = state.selected === xname ? null : xname;
  render();
}
function compareBySort(a, b, sort) {
  const key = sort.key;
  if (["xname", "status", "last_updated_ts"].includes(key)) {
    const av = String(a[key] || "").toLowerCase();
    const bv = String(b[key] || "").toLowerCase();
    const cmp = av.localeCompare(bv);
    return (cmp || 0) * sort.dir;
  }
  if (key === "verdict") {
    const cmp = conclusionOf(a).localeCompare(conclusionOf(b));
    return (cmp || 0) * sort.dir;
  }
  const av = a[key] === null || a[key] === undefined || a[key] === "" ? null : Number(a[key]);
  const bv = b[key] === null || b[key] === undefined || b[key] === "" ? null : Number(b[key]);
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  return (av - bv) * sort.dir;
}
function currentFactors() {
  const rows = DATA.factors.filter(searchFactor);
  if (state.sort) rows.sort((a, b) => compareBySort(a, b, state.sort) || String(a.xname).localeCompare(String(b.xname)));
  return rows;
}
function median(values) {
  const nums = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}
function renderMetrics() {
  const fs = DATA.factors;
  const passed = fs.filter(f => f.status === "evaluated");
  const failed = fs.filter(f => f.status === "dead_end");
  const icir = fs.map(f => f.latest_icir === null ? null : Math.abs(f.latest_icir));
  const redundant = fs.filter(f => f.latest_r2_x !== null).map(f => f.latest_r2_x);
  const significant = DATA.evaluations.filter(e => e.significant);
  const cards = [
    ["因子总数", fs.length, `${passed.length + failed.length} 个已评估`],
    ["通过", passed.length, `${failed.length} 个失败`],
    ["中位 |ICIR|", fmt(median(icir), 2), `${fs.filter(f => f.latest_icir !== null).length} 个有 ICIR`],
    ["中位库内 R²", pct(median(redundant)), `${redundant.length} 个有冗余检测`],
    ["显著评估", significant.length, `${DATA.evaluations.length} 条评估快照`]
  ];
  document.getElementById("metricCards").innerHTML = cards.map(([label, value, note]) =>
    `<div class="metric"><dt>${esc(label)}</dt><dd>${esc(value)}</dd><small>${esc(note)}</small></div>`
  ).join("");
}
function renderScatter() {
  const svg = document.getElementById("scatterChart");
  const points = DATA.factors.filter(f => f.latest_r2_x !== null && f.latest_icir !== null)
    .map(f => ({f, x: Math.max(0, Math.min(1, f.latest_r2_x)), y: Math.abs(f.latest_icir)}));
  const w = 720, h = 355, left = 54, right = 22, top = 18, bottom = 48;
  const maxY = Math.max(1, ...points.map(p => p.y));
  const niceY = maxY <= 3 ? 3 : maxY <= 6 ? 6 : Math.ceil(maxY / 2) * 2;
  const xScale = x => left + x * (w-left-right);
  const yScale = y => h-bottom - (y/niceY) * (h-top-bottom);
  let grid = "";
  for (let i=0; i<=4; i++) {
    const yv = niceY*i/4, y = yScale(yv);
    grid += `<line x1="${left}" y1="${y}" x2="${w-right}" y2="${y}" stroke="#dfe5eb"/><text x="${left-8}" y="${y+4}" text-anchor="end" font-size="11" fill="#667085">${yv.toFixed(yv<10?1:0)}</text>`;
  }
  for (let i=0; i<=5; i++) {
    const xv = i/5, x = xScale(xv);
    grid += `<line x1="${x}" y1="${top}" x2="${x}" y2="${h-bottom}" stroke="#eef1f5"/><text x="${x}" y="${h-bottom+20}" text-anchor="middle" font-size="11" fill="#667085">${(xv*100).toFixed(0)}%</text>`;
  }
  const circles = points.map(p => {
    const selected = p.f.xname === state.selected;
    return `<circle data-xname="${esc(p.f.xname)}" class="point" cx="${xScale(p.x)}" cy="${yScale(p.y)}" r="${selected ? 7 : 5}" fill="${STATUS_COLORS[p.f.status] || "#64748b"}" fill-opacity=".82" stroke="${selected ? "#111827" : "#fff"}" stroke-width="${selected ? 2 : 1}"><title>${esc(p.f.xname)}\nR² ${fmt(p.x,3)} / |ICIR| ${fmt(p.y,2)}</title></circle>`;
  }).join("");
  svg.innerHTML = `${grid}
    <line x1="${left}" y1="${h-bottom}" x2="${w-right}" y2="${h-bottom}" stroke="#98a2b3"/>
    <line x1="${left}" y1="${top}" x2="${left}" y2="${h-bottom}" stroke="#98a2b3"/>
    <text x="${(left+w-right)/2}" y="${h-9}" text-anchor="middle" font-size="12" fill="#475467">库内解释方差 R²</text>
    <text x="15" y="${(top+h-bottom)/2}" text-anchor="middle" font-size="12" fill="#475467" transform="rotate(-90 15 ${(top+h-bottom)/2})">|ICIR|</text>
    ${circles}`;
  svg.querySelectorAll("circle.point").forEach(c => c.addEventListener("click", () => {
    state.selected = c.dataset.xname; render(); }));
}
function renderStatusChart() {
  const svg = document.getElementById("statusChart");
  const counts = new Map();
  for (const f of DATA.factors) counts.set(f.status, (counts.get(f.status) || 0) + 1);
  const entries = [...counts.entries()].sort((a,b) => b[1]-a[1]);
  const w = 320, left = 104, right = 36, rowH = 38, top = 18, h = Math.max(355, top + entries.length*rowH + 26);
  const max = Math.max(1, ...entries.map(e => e[1]));
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = entries.map(([status, count], i) => {
    const y = top + i*rowH, width = Math.max(2, (count/max)*(w-left-right));
    return `<text x="0" y="${y+14}" font-size="11" fill="#475467">${esc(STATUS_LABELS[status] || status)}</text>
      <rect x="${left}" y="${y}" width="${width}" height="19" rx="3" fill="${STATUS_COLORS[status] || "#64748b"}" fill-opacity=".82"><title>${esc(status)}: ${count}</title></rect>
      <text x="${left+width+7}" y="${y+14}" font-size="11" font-weight="650" fill="#344054">${count}</text>`;
  }).join("");
}
const graphState = {
  branch: "all",
  cache: null,
  view: null,
  dragging: false,
  lastX: 0,
  lastY: 0
};
function shortFactorName(name) {
  return String(name || "").length > 20 ? String(name).slice(0, 18) + "…" : String(name || "—");
}
function buildLineageModel(branch) {
  const allNodes = DATA.factors.map(f => ({
    xname: f.xname,
    label: f.xname,
    status: f.status
  }));
  const byName = new Map(allNodes.map(n => [n.xname, n]));
  const adj = new Map();
  const rev = new Map();
  for (const e of DATA.lineage_edges || []) {
    if (!byName.has(e.parent_xname) || !byName.has(e.child_xname)) continue;
    if (!adj.has(e.parent_xname)) adj.set(e.parent_xname, []);
    adj.get(e.parent_xname).push(e.child_xname);
    rev.set(e.child_xname, e.parent_xname);
  }
  const roots = allNodes.filter(n => !rev.has(n.xname));
  const rootOf = new Map();
  for (const root of roots) {
    const queue = [root.xname];
    if (!rootOf.has(root.xname)) rootOf.set(root.xname, root.xname);
    while (queue.length) {
      const cur = queue.shift();
      for (const child of adj.get(cur) || []) {
        if (!rootOf.has(child)) {
          rootOf.set(child, root.xname);
          queue.push(child);
        }
      }
    }
  }
  for (const n of allNodes) {
    if (!rootOf.has(n.xname)) rootOf.set(n.xname, n.xname);
  }
  const nodes = allNodes.filter(n => branch === "all" || rootOf.get(n.xname) === branch);
  const nodeSet = new Set(nodes.map(n => n.xname));
  const edges = (DATA.lineage_edges || []).filter(e =>
    nodeSet.has(e.parent_xname) && nodeSet.has(e.child_xname)
  );
  return {nodes, edges, rootOf};
}
function computeLineageLayout(model) {
  const nodes = model.nodes.map(n => ({
    ...n,
    x: 0, y: 0, vx: 0, vy: 0,
    w: Math.min(172, Math.max(104, String(n.label).length * 6.1 + 18)),
    h: 34,
    root: model.rootOf.get(n.xname) || n.xname
  }));
  const byName = new Map(nodes.map(n => [n.xname, n]));
  const edges = model.edges.filter(e => byName.has(e.parent_xname) && byName.has(e.child_xname));
  const roots = [...new Set(nodes.map(n => n.root))];
  const W = 1600, H = 1000;
  const centers = new Map();
  roots.forEach((root, i) => {
    const angle = (i / Math.max(1, roots.length)) * 2 * Math.PI;
    const radius = Math.min(W, H) * 0.32;
    centers.set(root, {
      x: W / 2 + Math.cos(angle) * radius,
      y: H / 2 + Math.sin(angle) * radius * 0.7
    });
  });
  let seed = 20260820;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  nodes.forEach(n => {
    const c = centers.get(n.root) || {x: W / 2, y: H / 2};
    n.x = c.x + (rnd() - 0.5) * 420;
    n.y = c.y + (rnd() - 0.5) * 420;
  });
  const repulsion = 290000;
  const edgeSpring = 0.045;
  const rootSpring = 0.006;
  const gravity = 0.0015;
  for (let iter = 0; iter < 520; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const d2 = dx * dx + dy * dy + 1;
        const d = Math.sqrt(d2);
        const force = repulsion / d2;
        const fx = (dx / d) * force, fy = (dy / d) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }
    for (const e of edges) {
      const a = byName.get(e.parent_xname), b = byName.get(e.child_xname);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const fx = (dx / d) * d * edgeSpring, fy = (dy / d) * d * edgeSpring;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
    for (const n of nodes) {
      const c = centers.get(n.root) || {x: W / 2, y: H / 2};
      n.vx += (c.x - n.x) * rootSpring;
      n.vy += (c.y - n.y) * rootSpring;
      n.vx += (W / 2 - n.x) * gravity;
      n.vy += (H / 2 - n.y) * gravity;
      const maxV = 9;
      n.vx = Math.max(-maxV, Math.min(maxV, n.vx));
      n.vy = Math.max(-maxV, Math.min(maxV, n.vy));
      n.x += n.vx;
      n.y += n.vy;
      n.vx *= 0.84;
      n.vy *= 0.84;
    }
  }
  return {nodes, edges};
}
function getLineageLayout() {
  if (!graphState.cache || graphState.cache.branch !== graphState.branch) {
    graphState.cache = {
      branch: graphState.branch,
      layout: computeLineageLayout(buildLineageModel(graphState.branch))
    };
  }
  return graphState.cache.layout;
}
function fitGraphView() {
  const layout = getLineageLayout();
  if (!layout.nodes.length) return;
  const minX = Math.min(...layout.nodes.map(n => n.x - n.w / 2)) - 120;
  const minY = Math.min(...layout.nodes.map(n => n.y - n.h / 2)) - 90;
  const maxX = Math.max(...layout.nodes.map(n => n.x + n.w / 2)) + 120;
  const maxY = Math.max(...layout.nodes.map(n => n.y + n.h / 2)) + 90;
  graphState.view = {
    branch: graphState.branch,
    x: minX,
    y: minY,
    w: Math.max(960, maxX - minX),
    h: Math.max(560, maxY - minY)
  };
}
function applyGraphView(svg) {
  if (!graphState.view || graphState.view.branch !== graphState.branch) fitGraphView();
  svg.setAttribute("viewBox",
    `${graphState.view.x} ${graphState.view.y} ${graphState.view.w} ${graphState.view.h}`);
}
function lineageEdgePath(e, byId) {
  const p = byId.get(e.parent_xname), c = byId.get(e.child_xname);
  if (!p || !c) return "";
  const dx = c.x - p.x, dy = c.y - p.y;
  const d = Math.max(1, Math.hypot(dx, dy));
  const sx = p.x + (dx / d) * (p.w / 2 + 4);
  const sy = p.y + (dy / d) * (p.h / 2 + 4);
  const ex = c.x - (dx / d) * (c.w / 2 + 9);
  const ey = c.y - (dy / d) * (c.h / 2 + 9);
  const cls = (e.outcome === "improved" ? " improved" : e.outcome === "declined" ? " declined" : "")
    + (e.operator_name ? " operator-edge" : "");
  const title = e.operator_name ? `<title>算子: ${esc(e.operator_name)}</title>` : "";
  return `<line class="graph-edge${cls}" x1="${sx.toFixed(1)}" y1="${sy.toFixed(1)}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}">${title}</line>`;
}
function lineageNodeHtml(n) {
  const color = STATUS_COLORS[n.status] || "#64748b";
  const selected = state.selected === n.xname ? " selected" : "";
  const label = shortFactorName(n.label);
  return `<g class="graph-node${selected}" data-xname="${esc(n.xname)}" transform="translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(n.xname)}">
    <rect x="${(-n.w / 2).toFixed(1)}" y="${(-n.h / 2).toFixed(1)}" width="${n.w}" height="${n.h}" rx="6" fill="${color}18" stroke="${selected ? "#0f766e" : color}"></rect>
    <text x="0" y="-2" text-anchor="middle">${esc(label)}</text>
    <text class="node-status" x="0" y="12" text-anchor="middle">${esc(STATUS_LABELS[n.status] || n.status)}</text>
  </g>`;
}
function renderLineage() {
  const svg = document.getElementById("lineageChart");
  const empty = document.getElementById("lineageEmpty");
  const layout = getLineageLayout();
  empty.hidden = layout.nodes.length > 0;
  if (!layout.nodes.length) {
    svg.innerHTML = "";
    return;
  }
  applyGraphView(svg);
  const byId = new Map(layout.nodes.map(n => [n.xname, n]));
  svg.innerHTML = `
    <defs>
      <marker id="lineageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="#8da0b3"></path>
      </marker>
    </defs>
    <g>${layout.edges.map(e => lineageEdgePath(e, byId)).join("")}</g>
    <g>${layout.nodes.map(lineageNodeHtml).join("")}</g>`;
  svg.querySelectorAll(".graph-node").forEach(g => {
    g.addEventListener("click", event => {
      event.stopPropagation();
      state.selected = g.dataset.xname;
      render();
    });
    g.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        state.selected = g.dataset.xname;
        render();
      }
    });
  });
  document.getElementById("lineageMeta").textContent =
    `${layout.nodes.length} 节点 · ${layout.edges.length} 边 · ${new Set(layout.nodes.map(n => n.root)).size} 分支`;
}
function fillLineageSelect() {
  const select = document.getElementById("lineageBranchFilter");
  const branches = (DATA.lineage_branches || []).slice();
  select.innerHTML = `<option value="all">全部分支 (${DATA.factors.length})</option>` +
    branches.map(b =>
      `<option value="${esc(b.root_xname)}">${esc(shortFactorName(b.root_xname))} · ${b.member_count} 因子</option>`
    ).join("");
  select.value = graphState.branch;
}
function onLineageWheel(event) {
  event.preventDefault();
  const svg = document.getElementById("lineageChart");
  const rect = svg.getBoundingClientRect();
  const px = (event.clientX - rect.left) / Math.max(1, rect.width);
  const py = (event.clientY - rect.top) / Math.max(1, rect.height);
  const factor = event.deltaY > 0 ? 1.18 : 0.85;
  const v = graphState.view;
  const nw = Math.min(14000, Math.max(420, v.w * factor));
  const nh = Math.min(12000, Math.max(360, v.h * factor));
  v.x += px * (v.w - nw);
  v.y += py * (v.h - nh);
  v.w = nw;
  v.h = nh;
  svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}
function onLineagePointerDown(event) {
  if (event.target.closest && event.target.closest(".graph-node")) return;
  graphState.dragging = true;
  graphState.lastX = event.clientX;
  graphState.lastY = event.clientY;
  document.getElementById("lineageChart").classList.add("dragging");
  document.getElementById("lineageChart").setPointerCapture(event.pointerId);
}
function onLineagePointerMove(event) {
  if (!graphState.dragging || !graphState.view) return;
  const svg = document.getElementById("lineageChart");
  const rect = svg.getBoundingClientRect();
  graphState.view.x -= (event.clientX - graphState.lastX) * graphState.view.w / Math.max(1, rect.width);
  graphState.view.y -= (event.clientY - graphState.lastY) * graphState.view.h / Math.max(1, rect.height);
  graphState.lastX = event.clientX;
  graphState.lastY = event.clientY;
  svg.setAttribute("viewBox",
    `${graphState.view.x} ${graphState.view.y} ${graphState.view.w} ${graphState.view.h}`);
}
function onLineagePointerUp(event) {
  graphState.dragging = false;
  const svg = document.getElementById("lineageChart");
  svg.classList.remove("dragging");
  if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
}
function factorCell(f, open) {
  const tags = (f.tags || []).slice(0,3).map(t => `<span class="tag">${esc(t.name)}</span>`).join("");
  const chevron = open ? "▾" : "▸";
  return `<div class="factor-cell">
    <div class="factor-title"><button data-select="${esc(f.xname)}" type="button" title="${esc(f.xname)}"><span class="chevron" aria-hidden="true">${chevron}</span> ${esc(f.xname)}</button></div>
    <div class="factor-subtitle">${esc(f.class_name || "未分类")}</div>
    ${tags ? `<div class="tag-row">${tags}</div>` : ""}
  </div>`;
}
function sortBadge(key) {
  if (!state.sort || state.sort.key !== key) return "";
  return `<span class="sort-badge">${state.sort.dir > 0 ? "↑" : "↓"}</span>`;
}
function renderTable() {
  const rows = currentFactors();
  const inline = useInlineDetails();
  document.getElementById("resultCount").textContent = `${rows.length} / ${DATA.factors.length} 个因子`;
  document.getElementById("emptyMessage").hidden = rows.length > 0;
  document.getElementById("factorRows").innerHTML = rows.map(f => {
    const selected = f.xname === state.selected;
    const detailRow = inline && selected
      ? `<tr class="expanded-row"><td colspan="9">${inlineDetailHtml(f)}</td></tr>` : "";
    return `<tr data-xname="${esc(f.xname)}" class="${selected ? "selected" : ""}">
      <td>${factorCell(f, selected)}</td>
      <td>${verdictBadge(f)}</td>
      <td class="number ${cls(f.latest_ic)}">${fmt(f.latest_ic)}</td>
      <td class="number ${cls(f.latest_icir)}">${fmt(f.latest_icir, 2)}</td>
      <td class="number">${pct(f.latest_r2_x)}</td>
      <td class="number ${cls(f.latest_res_ic)}">${fmt(f.latest_res_ic)}</td>
      <td class="number ${cls(f.resic_ic_ratio)}">${pct(f.resic_ic_ratio)}</td>
      <td>${shortTime(f.last_updated_ts)}</td>
    </tr>${detailRow}`;
  }).join("");
  document.querySelectorAll("#factorRows tr[data-xname]").forEach(tr => tr.addEventListener("click", () => {
    toggleSelected(tr.dataset.xname);
  }));
  document.querySelectorAll("button[data-select]").forEach(btn => {
    btn.addEventListener("click", event => {
      event.stopPropagation(); toggleSelected(btn.dataset.select);
    });
  });
  document.querySelectorAll("[data-collapse]").forEach(btn => {
    btn.addEventListener("click", event => {
      event.stopPropagation(); state.selected = null; render();
    });
  });
  document.querySelectorAll(".sort-header").forEach(button => {
    button.innerHTML = `<span>${esc(button.dataset.label || button.dataset.key)}</span>${sortBadge(button.dataset.key)}`;
    button.title = "点击按此列排序；再次点击切换升降序";
  });
}
function detailMetric(label, value) {
  return `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
}
function detailBody(f) {
  const evals = evalsByName.get(f.xname) || [];
  const lessons = lessonsByName.get(f.xname) || [];
  const iterations = (iterationsByName.get(f.xname) || []).filter(i => i.change_note || i.reason);
  const hasIntuition = Boolean(f.intuition);
  const tagHtml = (f.tags || []).map(t => `<span class="tag" title="${esc(t.description || t.name)}">${esc(t.name)}</span>`).join("");
  const evalHtml = evals.length ? `<table class="detail-table"><thead><tr><th>时间</th><th>IC</th><th>ICIR</th><th>模式</th><th>显著</th></tr></thead><tbody>
    ${evals.slice(0,12).map(e => `<tr><td>${shortTime(e.ts)}</td><td class="${cls(e.ic_mean)}">${fmt(e.ic_mean)}</td><td class="${cls(e.icir)}">${fmt(e.icir,2)}</td><td>${esc(e.eval_mode || "—")}</td><td>${e.significant ? "是" : "否"}</td></tr>`).join("")}
    </tbody></table>` : `<p class="empty">暂无评估快照</p>`;
  const lessonHtml = lessons.length ? lessons.map(l => `
    <article class="lesson ${esc(l.type)}"><strong>${l.type === "success_pattern" ? "成功模式" : "放弃原因"}</strong><p>${esc(l.text)}</p></article>`).join("")
    : `<p class="empty">暂无实验结论</p>`;
  const iterationHtml = iterations.length ? `<table class="detail-table"><thead><tr><th>时间</th><th>迭代建议</th></tr></thead><tbody>
    ${iterations.slice(0,12).map(i => `<tr><td>${shortTime(i.ts)}</td><td>${esc(i.change_note || i.reason)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="empty">暂无迭代记录</p>`;
  return `
    ${tagHtml ? `<div class="tag-row" style="margin-top:8px">${tagHtml}</div>` : ""}
    <div class="detail-grid">
      ${detailMetric("IC", fmt(f.latest_ic))}
      ${detailMetric("ICIR", fmt(f.latest_icir,2))}
      ${detailMetric("库内 R²", pct(f.latest_r2_x))}
      ${detailMetric("残差 IC", fmt(f.latest_res_ic))}
      ${detailMetric("残差IC/IC", pct(f.resic_ic_ratio))}
      ${detailMetric("Rank IC", fmt(f.latest_rank_ic))}
    </div>
    <div class="detail-section ${hasIntuition ? "" : "full"}"><h3>公式</h3><pre>${esc(f.formula_text || "未记录")}</pre></div>
    ${hasIntuition ? `<div class="detail-section"><h3>研究意图</h3><pre>${esc(f.intuition)}</pre></div>` : ""}
    <div class="detail-section"><h3>评估历史</h3>${evalHtml}</div>
    <div class="detail-section"><h3>迭代记录</h3>${iterationHtml}</div>
    <div class="detail-section full"><h3>实验结论</h3>${lessonHtml}</div>
    <div class="detail-section full"><h3>文件</h3><pre>${esc(f.file_path || "未记录")}</pre></div>`;
}
function inlineDetailHtml(f) {
  return `<div class="inline-detail">
    <div class="inline-detail-head">
      <div class="detail-title">
        <h2>${esc(f.xname)}</h2>
        <p>${esc(f.class_name || "未分类")} · ${esc(STATUS_LABELS[f.status] || f.status)} · 结论 ${esc(verdictLabel(f))} · 更新 ${fullTime(f.last_updated_ts)}</p>
      </div>
      <button class="icon-button" data-collapse="${esc(f.xname)}" type="button" title="收起详情" aria-label="收起详情">×</button>
    </div>
    ${detailBody(f)}
  </div>`;
}
function renderDetail() {
  const panel = document.getElementById("detailPanel");
  const f = state.selected ? byName.get(state.selected) : null;
  panel.classList.toggle("open", Boolean(f));
  document.body.classList.toggle("sheet-open", Boolean(f));
  panel.scrollTop = 0;
  if (!f) {
    panel.innerHTML = `<div class="placeholder"><div><strong>选择一个因子</strong><br>查看公式、评估历史、迭代建议和实验结论</div></div>`;
    return;
  }
  panel.innerHTML = `
    <div class="detail-top">
      <div class="detail-title">
        <h2>${esc(f.xname)}</h2>
        <p>${esc(f.class_name || "未分类")} · ${esc(STATUS_LABELS[f.status] || f.status)} · 结论 ${esc(verdictLabel(f))} · 更新 ${fullTime(f.last_updated_ts)}</p>
      </div>
      <button class="icon-button" id="closeDetail" type="button" title="关闭详情" aria-label="关闭详情">×</button>
    </div>
    ${detailBody(f)}`;
  document.getElementById("closeDetail").addEventListener("click", () => {
    state.selected = null; render();
  });
}
function fillSelects() {
  const status = document.getElementById("statusFilter");
  status.innerHTML = `<option value="all">全部状态</option>` + uniqueStatuses().map(s =>
    `<option value="${esc(s)}">${esc(STATUS_LABELS[s] || s)} (${DATA.factors.filter(f => f.status===s).length})</option>`).join("");
  status.value = state.status;
  const tags = document.getElementById("tagFilter");
  tags.innerHTML = `<option value="all">全部标签</option>` + uniqueTags().map(([name,count]) =>
    `<option value="${esc(name)}">${esc(name)} (${count})</option>`).join("");
  tags.value = state.tag;
}
function renderHeader() {
  document.getElementById("dbMeta").textContent =
    `${DATA.meta.dbPath} · 数据更新 ${DATA.meta.dbModifiedAt} · 快照 ${DATA.meta.generatedAt}`;
  document.getElementById("footerMeta").textContent =
    `静态快照 · 页面自包含，无需端口 · 重新执行生成命令后刷新页面即可更新`;
}
function csvCell(value) { return `"${String(value ?? "").replaceAll('"','""')}"`; }
function exportCsv() {
  const headers = ["xname","class_name","status","verdict","latest_ic","latest_icir","latest_r2_x","latest_res_ic","resic_ic_ratio","last_updated_ts"];
  const rows = currentFactors();
  const csv = [headers.join(","), ...rows.map(f => headers.map(h => csvCell(f[h])).join(","))].join("\n");
  const blob = new Blob(["\ufeff" + csv], {type: "text/csv;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `factor_dashboard_${DATA.meta.generatedAt.slice(0,10)}.csv`;
  link.click(); URL.revokeObjectURL(link.href);
}
function render() {
  renderMetrics(); renderScatter(); renderStatusChart(); renderLineage(); renderTable();
  if (!useInlineDetails()) {
    renderDetail();
  } else {
    document.getElementById("detailPanel").classList.remove("open");
    document.body.classList.remove("sheet-open");
  }
}
function init() {
  state.selected = null;
  renderHeader(); fillSelects(); fillLineageSelect(); render();
  document.getElementById("searchInput").addEventListener("input", event => {
    state.query = event.target.value.trim(); renderTable();
  });
  document.getElementById("statusFilter").addEventListener("change", event => {
    state.status = event.target.value; renderTable();
  });
  document.getElementById("tagFilter").addEventListener("change", event => {
    state.tag = event.target.value; renderTable();
  });
  document.getElementById("resetButton").addEventListener("click", () => {
    state.query = ""; state.status = "all"; state.tag = "all";
    document.getElementById("searchInput").value = "";
    document.getElementById("statusFilter").value = "all";
    document.getElementById("tagFilter").value = "all";
    renderTable();
  });
  document.querySelectorAll(".sort-header").forEach(button => button.addEventListener("click", event => {
    const key = button.dataset.key;
    const defaultDir = key === "xname" || key === "status" ? 1 : -1;
    if (!state.sort || state.sort.key !== key) {
      state.sort = {key, dir: defaultDir};
    } else {
      state.sort.dir *= -1;
    }
    renderTable();
  }));
  document.getElementById("exportButton").addEventListener("click", exportCsv);
  document.getElementById("printButton").addEventListener("click", () => window.print());
  document.getElementById("refreshHint").addEventListener("click", () => alert("这是只读静态快照。更新数据后重新运行：python3 core/tools/generate_factor_dashboard.py"));
  document.getElementById("lineageBranchFilter").addEventListener("change", event => {
    graphState.branch = event.target.value;
    graphState.cache = null;
    graphState.view = null;
    renderLineage();
  });
  document.getElementById("lineageFitButton").addEventListener("click", () => {
    graphState.view = null;
    renderLineage();
  });
  document.getElementById("lineageResetButton").addEventListener("click", () => {
    graphState.branch = "all";
    document.getElementById("lineageBranchFilter").value = "all";
    graphState.cache = null;
    graphState.view = null;
    renderLineage();
  });
  const lineageSvg = document.getElementById("lineageChart");
  lineageSvg.addEventListener("wheel", onLineageWheel, {passive: false});
  lineageSvg.addEventListener("pointerdown", onLineagePointerDown);
  lineageSvg.addEventListener("pointermove", onLineagePointerMove);
  lineageSvg.addEventListener("pointerup", onLineagePointerUp);
  lineageSvg.addEventListener("pointercancel", onLineagePointerUp);
  document.addEventListener("keydown", event => {
    if (event.key === "/" && event.target.tagName !== "INPUT") {
      event.preventDefault(); document.getElementById("searchInput").focus();
    }
    if (event.key === "Escape" && state.selected) {
      state.selected = null; render();
    }
  });
  window.matchMedia("(max-width: 780px)").addEventListener("change", event => {
    if (event.matches) {
      state.selected = null;
    }
    render();
  });
}
init();
</script>
</body>
</html>
"""


def render_html(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).replace("</", "<\\/")
    return HTML.replace("__CSS__", CSS).replace("__DATA__", payload)


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
