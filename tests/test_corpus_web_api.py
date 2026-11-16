"""Contracts for read-only corpus research web API."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.corpus_autoloop import web_api


def fake_units():
    return [
        {"unit_id": f"daodejing-wangbi-{i:03d}",
         "chapter": i, "title": f"第{i}章", "part": "道经" if i<=37 else "德经",
         "text": f"章{i}原文，用于只读显示。", "source_file": f"data/chapters/{i:03d}.json",
         "source_status": "draft"}
        for i in range(1, 82)
    ]


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "never-create.sqlite3"
        self.fake = patch.object(web_api, "load_chapters", side_effect=fake_units)
        self.fake.start()
        self.addCleanup(self.fake.stop)

    def create_db(self):
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""
                CREATE TABLE research_objects (
                  object_id TEXT, source_id TEXT, parent_id TEXT, depth INTEGER,
                  status TEXT, revision INTEGER, hypothesis_json TEXT, factor_json TEXT,
                  evaluation_json TEXT, fusion_json TEXT, admission_json TEXT,
                  split_json TEXT, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE research_events (id INTEGER PRIMARY KEY, object_id TEXT,
                   kind TEXT, recorded_at TEXT);
            """)

    def test_missing_database_is_preview_not_fake_run(self):
        result = web_api.load_dashboard(self.path)
        self.assertFalse(result["initialized"])
        self.assertFalse(self.path.exists())
        self.assertEqual(result["mode"], "corpus_preview")
        self.assertEqual(result["summary"]["chapters"], 81)
        self.assertEqual(result["summary"]["totalObjects"], 0)
        self.assertEqual(result["summary"]["admitted"], 0)
        self.assertEqual(result["objects"][0]["status"], "uninitialized")
        self.assertIsNone(result["objects"][0]["metricValue"])
        self.assertEqual(result["chapters"][80]["part"], "德经")
        self.assertEqual(web_api.object_detail(result, "RO-DDJ-001")["source"]["chapter"], 1)

    def test_read_real_sqlite_without_mutating_it(self):
        self.create_db()
        hypothesis = {"hypothesis": "两个信号出现冲突时可能具有新信息",
                      "source_quote": "章1原文", "required_data": ["trade"]}
        factor = {"name": "ExampleSignal", "formula": "a-b", "intuition": "signal"}
        eval_report = {
            "execution_ref": "quant-run://run1", "data_split": "screening",
            "predictive": {"metric_name": "ICIR", "metric_value": 0.41, "passed": True},
            "independence": {"decision": "redundant", "r2_x": 0.91,
                             "res_ic": 0.001, "nearest_factors": ["BookImbalance"]},
        }
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO research_objects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("RO-DDJ-001", "daodejing-wangbi-001", None, 0,
                          "awaiting_fusion", 4, json.dumps(hypothesis),
                          json.dumps(factor), json.dumps(eval_report), None, None, None,
                          "2026-01-01", "2026-11-16"))
            conn.execute("INSERT INTO research_objects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("RO-DDJ-001-1", "daodejing-wangbi-001", "RO-DDJ-001", 1,
                          "terminal_exhausted", 5, None, None, None, None, None, None,
                          "2026-01-01", "2026-11-16"))
            conn.execute("INSERT INTO research_events VALUES (?,?,?,?)",
                         (1,"RO-DDJ-001", "evaluation", "2026-11-16T11:00:00Z"))
        before = self.path.stat().st_mtime_ns
        snap = web_api.load_dashboard(self.path)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertTrue(snap["initialized"])
        self.assertEqual(snap["summary"]["running"], 1)
        self.assertEqual(snap["summary"]["closed"], 1)
        self.assertEqual(snap["summary"]["totalObjects"], 2)
        self.assertEqual(snap["summary"]["nextObjectId"], "RO-DDJ-001")
        self.assertEqual(snap["objects"][0]["r2"], 0.91)
        self.assertEqual(snap["objects"][0]["resIc"], 0.001)
        detail = web_api.object_detail(snap,"RO-DDJ-001")
        self.assertEqual(len(detail["lineage"]), 2)
        self.assertEqual(detail["events"][0]["kind"], "evaluation")
        self.assertIsNone(web_api.object_detail(snap, "../config.py"))
        self.assertIsNone(web_api.object_detail(snap, "RO-DDJ-099"))

    def test_empty_existing_database_does_not_look_like_live_run(self):
        self.create_db()
        snap = web_api.load_dashboard(self.path)
        self.assertTrue(snap["initialized"])
        self.assertEqual(snap["summary"]["totalObjects"], 0)
        self.assertEqual(snap["summary"]["admitted"], 0)
        self.assertEqual(snap["chapters"][0]["group"], "uninitialized")


if __name__ == "__main__":
    unittest.main()
