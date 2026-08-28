"""Tests for the dashboard snapshot collector (shared by API server)."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools.dashboard_snapshot import collect_snapshot

# SCHEMA 与 _fixture_db 从 test_generate_factor_dashboard.py 原样拷贝
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


def test_collect_snapshot_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "factors.db"
        _fixture_db(db_path)
        snap = collect_snapshot(db_path)
        f = snap["factors"][0]
        assert f["xname"] == "TestFactor"
        assert f["gate_pass"] is True and f["failed_gates"] == []
        assert abs(f["agg_score"] - 0.25 * (0.12 / 0.15 + 2.4 / 8 + 1.0 + (0.7 - 0.35) / 0.7)) < 1e-6
        assert f["tags"][0]["name"] == "order_book"
        assert abs(f["resic_ic_ratio"] - 0.08 / 0.12) < 1e-9
        for key in ("evaluations", "iterations", "lineage_edges",
                    "lineage_branches", "lessons", "meta"):
            assert key in snap
        assert "generatedAt" in snap["meta"]


def test_uri_db_path() -> None:
    # server 会传 file:...?mode=ro&immutable=1 形式,必须与裸路径等价
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "factors.db"
        _fixture_db(db_path)
        snap = collect_snapshot(f"file:{db_path}?mode=ro&immutable=1")
        assert snap["factors"][0]["xname"] == "TestFactor"


def main() -> None:
    test_collect_snapshot_fields()
    test_uri_db_path()
    print("✓ dashboard_snapshot tests passed")


if __name__ == "__main__":
    main()
