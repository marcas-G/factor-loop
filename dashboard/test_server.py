"""Tests for dashboard/server.py (in-process HTTP round-trips)."""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import SnapshotCache, make_server

# SCHEMA 与 _fixture_db 从 core/tools/test_dashboard_snapshot.py 原样拷贝
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_api_snapshot_etag_cycle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "factors.db"
        _fixture_db(db)
        cache = SnapshotCache(str(db))
        port = _free_port()
        httpd = make_server(("127.0.0.1", port), cache, dist_dir=None)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            # 1) first GET: 200 + JSON + ETag
            r1 = urllib.request.urlopen(f"{base}/api/snapshot", timeout=5)
            body1 = r1.read()
            etag = r1.headers["ETag"]
            assert r1.status == 200 and etag
            assert json.loads(body1)["factors"][0]["xname"] == "TestFactor"

            # 2) db unchanged: If-None-Match → 304, no recompute (calls == 1)
            req = urllib.request.Request(f"{base}/api/snapshot",
                                         headers={"If-None-Match": etag})
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("expected 304")
            except urllib.error.HTTPError as e:
                assert e.code == 304
            assert cache.calls == 1

            # 3) db changed (mtime bumped): same ETag → 200 fresh body
            conn = sqlite3.connect(db)
            conn.execute("UPDATE factors SET latest_ic = 0.2 WHERE xname='TestFactor'")
            conn.commit(); conn.close()
            stamp = db.stat().st_mtime + 2
            os.utime(db, (stamp, stamp))
            resp = urllib.request.urlopen(req, timeout=5)
            assert resp.status == 200
            assert json.loads(resp.read())["factors"][0]["latest_ic"] == 0.2
        finally:
            httpd.shutdown()


def test_static_fallback_to_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "factors.db"
        _fixture_db(db)
        dist = Path(tmp) / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        port = _free_port()
        httpd = make_server(("127.0.0.1", port), SnapshotCache(str(db)), dist_dir=dist)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            assert urllib.request.urlopen(base, timeout=5).read() == b"<html>app</html>"
            # SPA route paths fall back to index.html
            assert urllib.request.urlopen(f"{base}/factor/x", timeout=5).read() == b"<html>app</html>"
            # missing asset under dist does NOT fall back (404, not html)
            try:
                urllib.request.urlopen(f"{base}/assets/nope.js", timeout=5)
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            httpd.shutdown()


def main() -> None:
    test_api_snapshot_etag_cycle()
    test_static_fallback_to_index()
    print("✓ server tests passed")


if __name__ == "__main__":
    main()
