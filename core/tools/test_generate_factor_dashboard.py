"""Tests for the static factor dashboard generator."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.generate_factor_dashboard import (
    collect_snapshot,
    render_html,
    write_atomic,
)


SCHEMA = """
CREATE TABLE factors (
  xname TEXT PRIMARY KEY,
  class_name TEXT,
  file_path TEXT,
  formula_text TEXT,
  status TEXT,
  verdict TEXT,
  latest_ic REAL,
  latest_icir REAL,
  latest_r2_x REAL,
  latest_res_ic REAL,
  last_updated_ts TEXT
);
CREATE TABLE factor_evals (
  id INTEGER PRIMARY KEY,
  factor_xname TEXT,
  idea_id INTEGER,
  ts TEXT,
  symbol TEXT,
  freq TEXT,
  ic_mean REAL,
  icir REAL,
  sharpe REAL,
  rank_ic REAL,
  eval_metrics TEXT,
  conditional_returns TEXT,
  eval_mode TEXT,
  significant INTEGER,
  raw_path TEXT
);
CREATE TABLE iteration_suggestions (
  suggestion_id INTEGER PRIMARY KEY,
  from_xname TEXT,
  idea_id INTEGER,
  change_note TEXT,
  reason TEXT,
  created_ts TEXT,
  status TEXT
);
CREATE TABLE factor_lineage_edges (
  edge_id INTEGER PRIMARY KEY,
  parent_xname TEXT,
  child_xname TEXT,
  suggestion_id INTEGER,
  origin TEXT,
  outcome TEXT,
  icir_delta REAL
);
CREATE TABLE lessons (
  id INTEGER PRIMARY KEY,
  type TEXT,
  scope TEXT,
  text TEXT,
  evidence TEXT,
  idea_id INTEGER,
  factor_xname TEXT,
  created_ts TEXT,
  deprecated_at TEXT
);
CREATE TABLE tags (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  description TEXT
);
CREATE TABLE factor_tags (
  factor_xname TEXT,
  tag_id INTEGER,
  PRIMARY KEY (factor_xname, tag_id)
);
"""


def _fixture_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT INTO factors VALUES (
              'TestFactor', 'TestClass', 'factors/TestFactor.h',
              'output = rank(imbalance)', 'evaluated', 'pass', 0.12, 2.4,
              0.35, 0.08, '2026-08-17 08:00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO factor_evals VALUES (
              1, 'TestFactor', NULL, '2026-08-17', NULL, NULL,
              0.12, 2.4, NULL, NULL, NULL, NULL, 'full', 1, NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO iteration_suggestions VALUES "
            "(1, 'TestFactor', NULL, 'next test', NULL, '2026-08-17', 'open')"
        )
        conn.execute("INSERT INTO lessons VALUES (1, 'success_pattern', 'factor', 'stable signal', '{}', NULL, 'TestFactor', '2026-08-17', NULL)")
        conn.execute("INSERT INTO tags VALUES (1, 'order_book', NULL)")
        conn.execute("INSERT INTO factor_tags VALUES ('TestFactor', 1)")


def test_snapshot_and_html_render() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "factors.db"
        output_path = Path(tmp) / "dashboard.html"
        _fixture_db(db_path)

        snapshot = collect_snapshot(db_path)
        assert snapshot["factors"][0]["xname"] == "TestFactor"
        assert snapshot["factors"][0]["verdict"] == "pass"
        assert snapshot["factors"][0]["tags"][0]["name"] == "order_book"
        assert abs(snapshot["factors"][0]["resic_ic_ratio"] - 0.08 / 0.12) < 1e-9
        assert len(snapshot["evaluations"]) == 1
        assert len(snapshot["iterations"]) == 1
        assert "lineage_edges" in snapshot
        assert "lineage_branches" in snapshot
        assert len(snapshot["lessons"]) == 1

        html = render_html(snapshot)
        assert "TestFactor" in html
        assert "血缘图谱" in html
        assert "FACTOR_DASHBOARD_DATA" in html
        assert "</script>" in html
        assert "state.sort = {key, dir: defaultDir};" in html
        assert "state.sort.dir *= -1;" in html
        assert "state.sorts" not in html
        assert "function rankCurrentFactors" not in html
        assert "function rankScoresFor" not in html
        assert "data-key=\"resic_ic_ratio\"" in html
        assert "通过" in html
        write_atomic(output_path, html)
        assert output_path.read_text(encoding="utf-8") == html


def main() -> None:
    test_snapshot_and_html_render()
    print("✓ generate_factor_dashboard tests passed")


if __name__ == "__main__":
    main()
