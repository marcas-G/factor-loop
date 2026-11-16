"""TreEvo MVP tests. All data are synthetic. No platform/API/network required."""
from __future__ import annotations

import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.tre_evo import TreEvoStore, TreeConflict, TreeInvariantError
from core.tre_evo.contracts import ContractError, validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "standardization" / "examples"


def sample(name):
    return json.loads((EXAMPLE / f"{name}.json").read_text(encoding="utf-8"))


class TreeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "tre-evo.sqlite3"
        self.store = TreEvoStore(self.db)
        self.root = sample("hypothesis-root")
        self.child = sample("hypothesis-child")
        self.edge = sample("refinement-edge")
        self.pheno = sample("phenomenon")

    def seed(self):
        self.assertTrue(self.store.create_root(self.root)["created"])
        self.assertTrue(self.store.record_phenomenon(self.pheno)["created"])

    def test_tree_persists_across_process_reopen(self):
        self.seed()
        result = self.store.add_refinement(self.edge, self.child, expected_revision=1)
        self.assertEqual(result["revision"], 2)
        reopened = TreEvoStore(self.db)
        tree = reopened.tree(self.root["tree_id"])
        self.assertEqual(tree["revision"], 2)
        self.assertEqual(len(tree["nodes"]), 2)
        self.assertEqual(len(tree["edges"]), 1)
        self.assertEqual(len(tree["source_phenomena"]), 1)
        self.assertEqual(tree["edges"][0]["refinement_type"], "condition_specification")
        self.assertEqual(tree["nodes"][1]["parent_id"], self.root["node_id"])

    def test_idempotent_retries_do_not_increment_revision(self):
        self.seed()
        self.assertFalse(self.store.create_root(copy.deepcopy(self.root))["created"])
        self.assertFalse(self.store.record_phenomenon(copy.deepcopy(self.pheno))["created"])
        self.store.add_refinement(self.edge, self.child, expected_revision=1)
        retried = self.store.add_refinement(self.edge, self.child, expected_revision=1)
        self.assertFalse(retried["created"])
        self.assertEqual(self.store.tree(self.root["tree_id"])["revision"], 2)

    def test_cas_and_branching(self):
        self.seed()
        self.store.add_refinement(self.edge, self.child, expected_revision=1)
        sister = copy.deepcopy(self.child)
        sister["node_id"] = "H-DEMO-SISTER"
        sister["statement"] = "事件前波动状态也可能独立影响相同压力下的未来路径。"
        sister["source_phenomena"] = []
        edge = copy.deepcopy(self.edge)
        edge["edge_id"] = "E-DEMO-SISTER"
        edge["child_node_id"] = sister["node_id"]
        edge["refinement_type"] = "competing_explanation"
        edge["new_information"] = ["考虑事件前波动状态这一竞争解释"]
        with self.assertRaises(TreeConflict):
            self.store.add_refinement(edge, sister, expected_revision=1)
        result = self.store.add_refinement(edge, sister, expected_revision=2)
        self.assertEqual(result["revision"], 3)
        self.assertEqual(len(self.store.tree(self.root["tree_id"])["nodes"]), 3)

    def test_missing_parent_and_bad_links_are_rejected_atomically(self):
        self.seed()
        bad = copy.deepcopy(self.edge)
        bad["parent_node_id"] = "NOT-EXIST"
        self.child["parent_id"] = "NOT-EXIST"
        with self.assertRaises(TreeInvariantError):
            self.store.add_refinement(bad, self.child, expected_revision=1)
        self.assertEqual(self.store.tree(self.root["tree_id"])["revision"], 1)
        self.assertEqual(len(self.store.tree(self.root["tree_id"])["nodes"]), 1)
        self.child["parent_id"] = self.root["node_id"]
        bad["parent_node_id"] = bad["child_node_id"]
        self.child["parent_id"] = bad["parent_node_id"]
        with self.assertRaises(ContractError):
            self.store.add_refinement(bad, self.child, expected_revision=1)

    def test_unknown_or_unverified_phenomenon_cannot_be_claimed_as_evidence(self):
        self.store.create_root(self.root)
        with self.assertRaises(TreeInvariantError):
            self.store.add_refinement(self.edge, self.child, expected_revision=1)
        raw = [{"phenomenon_id": "P-A-1", "source_type": "A_local_break",
                "representations": {"factor": "X"}, "matched_conditions": {"symbol": "SHFE-AG"},
                "observed_deviation": "h1/h5 sign change", "interpretation": "FORBIDDEN"}]
        result = self.store.import_candidates(raw, source_ref="fixture-snapshot-01")
        self.assertEqual(result["new"], 1)
        with self.assertRaises(TreeInvariantError):
            self.store.add_refinement(self.edge, self.child, expected_revision=1)
        self.store.record_phenomenon(self.pheno)
        self.assertTrue(self.store.add_refinement(self.edge, self.child, expected_revision=1)["created"])

    def test_candidate_import_deduplicates_legacy_sequence_numbers(self):
        raw = [{"phenomenon_id": "P-A-1", "source_type": "A_local_break",
                "representations": {"factor": "X"}, "matched_conditions": {"symbol": "AG"},
                "observed_deviation": "sign flip"}]
        self.assertEqual(self.store.import_candidates(raw, source_ref="snapshotA")["new"], 1)
        raw[0]["phenomenon_id"] = "P-A-55"
        self.assertEqual(self.store.import_candidates(raw, source_ref="snapshotA")["new"], 0)
        self.assertEqual(self.store.import_candidates(raw, source_ref="snapshotB")["new"], 1)
        candidates = self.store.candidates()
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(x["review_status"] == "unverified" for x in candidates))

    def test_schema_and_provenance_rules(self):
        missing_reason = copy.deepcopy(self.edge)
        missing_reason["refinement_warrant"] = " "
        with self.assertRaises(ContractError):
            validate("edge", missing_reason)
        future_leak = copy.deepcopy(self.pheno)
        future_leak["data_window"]["feature_end_offset_ms"] = 10
        with self.assertRaises(ContractError):
            validate("phenomenon", future_leak)
        ungrounded = copy.deepcopy(self.pheno)
        ungrounded["example_status"] = "measured"
        with self.assertRaises(ContractError):
            validate("phenomenon", ungrounded)
        bad_root = copy.deepcopy(self.root)
        bad_root["parent_id"] = "P"
        with self.assertRaises(TreeInvariantError):
            self.store.create_root(bad_root)

    def test_cli_end_to_end(self):
        def run(*args):
            return subprocess.run(
                [sys.executable, "-m", "core.tre_evo.cli", "--db", str(self.db), *args],
                cwd=ROOT, capture_output=True, text=True
            )
        result = run("create-root", "--node", str(EXAMPLE / "hypothesis-root.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run("record-phenomenon", "--record", str(EXAMPLE / "phenomenon.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run("add-refinement", "--edge", str(EXAMPLE / "refinement-edge.json"),
                     "--child", str(EXAMPLE / "hypothesis-child.json"),
                     "--expected-revision", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run("show-tree", "--tree-id", "TREE-DEMO-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["revision"], 2)


class ReadOnlyLegacyAdapterTest(unittest.TestCase):
    def test_miner_can_scan_readonly_and_stage_without_promoting(self):
        import numpy  # deliberate optional miner requirement
        from core.tre_evo.phenomena import mine_legacy_candidates

        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / "factors.db"
            source = sqlite3.connect(str(legacy))
            source.executescript("""
                CREATE TABLE factors (xname TEXT, status TEXT, latest_icir REAL, latest_ic REAL);
                CREATE TABLE factor_ic_daily (
                    factor_xname TEXT, symbol TEXT, freq TEXT, y_horizon INTEGER,
                    date TEXT, ic REAL);
                CREATE TABLE factor_lineage_nodes (
                    xname TEXT, primary_root_xname TEXT);
                INSERT INTO factors VALUES ('FakeX','evaluated',2.0,0.04);
                INSERT INTO factor_ic_daily VALUES ('FakeX','SHFE-AG','main',1,'2026-01-01',0.05);
                INSERT INTO factor_ic_daily VALUES ('FakeX','SHFE-AG','main',5,'2026-01-01',-0.04);
                INSERT INTO factor_ic_daily VALUES ('FakeX','SHFE-AG','main',10,'2026-01-01',-0.02);
            """)
            source.commit()
            source.close()
            store = TreEvoStore(Path(temp) / "tre-evo.db")
            result = mine_legacy_candidates(source_db=legacy, store=store)
            self.assertGreaterEqual(result["new"], 1)
            self.assertEqual(result["review_status"], "unverified")
            self.assertEqual(mine_legacy_candidates(source_db=legacy, store=store)["new"], 0)
            self.assertEqual(len(store.candidates()), result["new"])
            with sqlite3.connect(str(legacy)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM factors").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
