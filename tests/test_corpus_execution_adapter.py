"""Integration tests for quant-run bridge. No real network, LLM or platform access."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.corpus_autoloop.agent_runner import OpenCodeRunner
from core.corpus_autoloop.execution_adapter import (
    CorpusExecutionAdapter, EvidenceError, evaluate_state,
)
from core.corpus_autoloop.workflow import CorpusAutoloop, WorkflowConflict

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "corpora" / "daodejing" / "examples"


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


class FakeBackend:
    """Implements *actual* MCP entry points but in in-memory fixtures."""
    def __init__(self):
        self.runs = {}
        self.inits = 0
        self.persists = 0
        self.saves = 0

    def run_init(self, *, idea, factors, parent_session):
        self.inits += 1
        rid = f"unit-test-run-{self.inits}"
        self.runs[rid] = {
            "run_id": rid, "parent_session": parent_session, "idea_id": None,
            "factors": [{"name": factors[0]["name"], "status":"pending",
                         "failure_layer": None, "factor_file": None, "evidence": None}],
        }
        return {"run_id": rid}

    def persist_candidates(self, *, run_id, idea_text, factors):
        self.persists += 1
        self.runs[run_id]["idea_id"] = 900
        return {"idea_id": 900, "n_factors": len(factors)}

    def run_load(self, run_id):
        return copy.deepcopy(self.runs[run_id])

    def run_save(self, run_id, patch):
        self.saves += 1
        self.runs[run_id].update(copy.deepcopy(patch))
        return {"ok": True}

    def run_list(self):
        return [{"run_id": x} for x in self.runs]


class AdapterIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = CorpusAutoloop(self.path / "corpus.sqlite")
        self.store.seed()
        self.id = "RO-DDJ-001"
        self.hyp = load("chapter_001_hypothesis.json")
        self.fac = load("chapter_001_factor.json")
        obj = self.store.record_hypothesis(self.id, self.hyp, revision=1)
        self.store.record_factor(self.id, self.fac, revision=obj["revision"])
        self.backend = FakeBackend()
        self.adapter = CorpusExecutionAdapter(self.store, self.backend)
        self.factor_file = self.path / "DaoDeJing_Ch01_ImbalanceDisagreement.h"
        self.factor_file.write_text(
            "#pragma once\n// real C++ source placeholder for offline adapter test\n", encoding="utf-8"
        )

    def begin(self):
        return self.adapter.begin(
            self.id, expected_revision=3,
            dataset_ref="actual-dataset-screening-2024",
            library_snapshot_ref="actual-library-2026-11-16",
        )

    def complete(self, *, r2=0.1, residual=0.03, zero_rate=0.1):
        rid = self.begin()["run_id"]
        f = self.backend.runs[rid]["factors"][0]
        f.update({
            "status": "done", "failure_layer": "check_done",
            "factor_file": str(self.factor_file),
            "evidence": {
                "eval_metrics": {
                    "core_metrics": {"screening": {"icir": 0.55, "spearman": 0.021}},
                    "deep_best": {"daily_icir": 0.42, "daily_rank_ic": 0.018},
                    "zero_rate": zero_rate,
                },
                "ridge_svd_agg": {"R2_X": r2, "res_IC": residual, "engine":"gpu"},
            },
        })
        review = {
            "passed": True, "reviewer": "research-source-reviewer",
            "evidence_ref": "research-review://artifact/code-01",
            "sha256": hashlib.sha256(self.factor_file.read_bytes()).hexdigest(),
        }
        return rid, review

    def test_begin_is_idempotent_and_owns_correct_real_run(self):
        first = self.begin()
        again = self.begin()
        self.assertEqual(first["run_id"], again["run_id"])
        self.assertEqual(self.backend.inits, 1)
        self.assertEqual(self.backend.persists, 1)
        self.assertEqual(self.backend.saves, 1)
        self.assertEqual(self.adapter._link(self.id)["status"], "prepared")
        state = self.backend.run_load(first["run_id"])
        self.assertEqual(state["corpus_autoloop"]["source_unit_id"],"daodejing-wangbi-001")
        self.assertEqual(self.store.get(self.id)["status"],"awaiting_evaluation")

    def test_recover_reserved_run_without_double_persist(self):
        rid=self.begin()["run_id"]
        with self.store._connection() as db:
            db.execute("UPDATE corpus_execution_links SET run_id=NULL,status='reserved' WHERE object_id=?",
                       (self.id,))
        result=self.begin()
        self.assertEqual(result["run_id"],rid)
        self.assertEqual(self.backend.persists,1)
        self.assertEqual(self.backend.inits,1)

    def test_collect_independent_real_metrics_before_holdout(self):
        rid,review=self.complete()
        outcome=self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        self.assertEqual(outcome["research_object"]["status"],"awaiting_confirmation")
        report=outcome["report"]
        self.assertEqual(report["executor_run_id"],rid)
        self.assertEqual(report["predictive"]["metric_value"],0.55)
        self.assertEqual(report["independence"]["decision"],"independent")
        self.assertEqual(self.adapter._link(self.id)["status"],"observed")
        self.assertEqual(len(self.store.events(self.id)),4)
        with self.assertRaises(WorkflowConflict):
            self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)

    def test_redundancy_requires_real_nearest_existing_factor(self):
        _,review=self.complete(r2=0.92,residual=0.002)
        inconclusive=self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        self.assertEqual(inconclusive["report"]["independence"]["decision"],"inconclusive")
        self.assertEqual(inconclusive["research_object"]["status"],"awaiting_evaluation")

    def test_redundant_with_verified_nearest_enters_fusion(self):
        _,review=self.complete(r2=0.92,residual=0.002)
        output=self.adapter.collect(
            self.id,expected_revision=3,fidelity_review=review,
            nearest_factors=["ExistingLiquidityFactor"])
        self.assertEqual(output["research_object"]["status"],"awaiting_fusion")
        self.assertEqual(output["report"]["independence"]["nearest_factors"],
                         ["ExistingLiquidityFactor"])

    def test_sparse_factor_uses_daily_scores(self):
        _,review=self.complete(zero_rate=0.81)
        output=self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        self.assertEqual(output["report"]["predictive"]["metric_value"],0.42)
        self.assertEqual(output["report"]["audit"]["metric_kind"],"daily")

    def test_rejects_missing_misbound_or_precommitted_evidence(self):
        rid,review=self.complete()
        bad=copy.deepcopy(review)
        bad["sha256"]="incorrect"
        with self.assertRaises(EvidenceError):
            self.adapter.collect(self.id,expected_revision=3,fidelity_review=bad)
        self.backend.runs[rid]["factors"][0]["persisted"]={"status":"evaluated"}
        with self.assertRaises(EvidenceError):
            self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        del self.backend.runs[rid]["factors"][0]["persisted"]
        self.backend.runs[rid]["parent_session"]="other task"
        with self.assertRaises(EvidenceError):
            self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)

    def test_requires_terminal_real_execution(self):
        rid = self.begin()["run_id"]
        f=self.backend.runs[rid]["factors"][0]
        f.update({"status":"submitting","failure_layer":None,
                  "factor_file":str(self.factor_file),"evidence":None})
        review={"passed":True,"reviewer":"human","evidence_ref":"real://review",
                "sha256":hashlib.sha256(self.factor_file.read_bytes()).hexdigest()}
        with self.assertRaises(EvidenceError):
            self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)

    def test_runner_requires_single_legacy_task_and_actual_end_state(self):
        started=self.begin()
        repo=self.path / "repo"
        (repo / ".zcode/agents/executors").mkdir(parents=True)
        (repo / ".zcode/agents/executors/run-factor-agent.md").write_text(
            "integration test only",encoding="utf-8")
        calls=[]
        class Result:
            returncode=0
        def fake_spawn(argv,**kwargs):
            calls.append(argv)
            task=json.loads((repo / ".tmp/agent_task.json").read_text(encoding="utf-8"))
            self.assertEqual(task["input"]["run_id"],started["run_id"])
            f=self.backend.runs[started["run_id"]]["factors"][0]
            f.update({"status":"done","failure_layer":"check_done"})
            return Result()
        runner=OpenCodeRunner(
            root=repo, model="local-test-model", timeout=60,
            spawn=fake_spawn, backend=self.backend)
        result=runner.execute(self.store.get(self.id),started["run_id"])
        self.assertEqual(result["failure_layer"],"check_done")
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],"opencode")
        self.assertFalse((repo / ".tmp/agent_task.json").exists())
        task_path=repo / ".tmp/agent_task.json"
        task_path.write_text("occupied",encoding="utf-8")
        with self.assertRaises(WorkflowConflict):
            runner.execute(self.store.get(self.id),started["run_id"])
        self.assertEqual(task_path.read_text(encoding="utf-8"),"occupied")

    def test_begin_requires_unmodified_dataset_identity_and_correct_revision(self):
        self.begin()
        with self.assertRaises(WorkflowConflict):
            self.adapter.begin(self.id,expected_revision=3,
                dataset_ref="other-dataset",library_snapshot_ref="actual-library-2026-11-16")
        with self.assertRaises(WorkflowConflict):
            self.adapter.begin(self.id,expected_revision=2,
                dataset_ref="actual-dataset-screening-2024",
                library_snapshot_ref="actual-library-2026-11-16")


if __name__ == "__main__":
    unittest.main()
