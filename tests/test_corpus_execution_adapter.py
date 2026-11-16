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
from core.corpus_autoloop.holdout_adapter import IndependentHoldoutAdapter
from core.corpus_autoloop.admission_adapter import AdmissionAdapter
from core.corpus_autoloop.fusion_adapter import FusionAdapter, generate_plan
from core.corpus_autoloop.fusion_confirmation import FusionConfirmationAdapter
from core.corpus_autoloop.workflow import CorpusAutoloop, WorkflowConflict
from core.corpus_autoloop import contracts

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
        for key,value in patch.items():
            if key.startswith("factors.0."):
                self.runs[run_id]["factors"][0][key[len("factors.0."):]]=copy.deepcopy(value)
            else:
                self.runs[run_id][key]=copy.deepcopy(value)
        return {"ok": True}

    def persist_factor(self, run_id, factor_index, mode, verdict):
        self.persist_calls=getattr(self,"persist_calls",0)+1
        if mode!="commit" or verdict.get("verdict")!="pass":
            return {"ok":False,"error":"bad test contract"}
        return {"xname":self.runs[run_id]["factors"][factor_index]["name"],
                "status":"evaluated","metrics":{"icir":0.55}}

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

    def test_cpu_holdout_and_real_admission_are_separate_committed_steps(self):
        _,review=self.complete()
        screening=self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        self.assertEqual(screening["research_object"]["status"],"awaiting_confirmation")
        class Platform:
            def __init__(self):
                self.submit_count=0
                self.last_kwargs=None
            def submit(self,**kwargs):
                self.submit_count+=1
                self.last_kwargs=kwargs
                return {"ok":True,"features":self.last_kwargs["features"],
                        "tasks":{"csv_ic":{"run_id":"real-cpu-job-007",
                                           "feature":"CorpusFactor_test_007"}}}
            def check(self,**kwargs):
                return {"failureLayer":"check_done",
                        "evidence":{"eval_metrics":{
                            "zero_rate":0.2,
                            "core_metrics":{"screening":{"icir":0.47,"spearman":0.021}},
                        }}}
        platform=Platform()
        holdout=IndependentHoldoutAdapter(
            self.store,backend=self.backend,platform=platform)
        outcome=holdout.confirm(self.id,expected_revision=4,fidelity_review=review)
        self.assertEqual(platform.submit_count,1)
        self.assertEqual(platform.last_kwargs["start_date"],"2025-07-01")
        self.assertEqual(platform.last_kwargs["end_date"],"2025-12-31")
        self.assertEqual(outcome["research_object"]["status"],"awaiting_admission")
        self.assertEqual(outcome["report"]["data_split"],"holdout_confirmation")
        self.assertEqual(outcome["report"]["audit"]["gpu_independence_reused_from_screening"],True)
        receipt=AdmissionAdapter(self.store,backend=self.backend).commit(
            self.id,expected_revision=5,review={
                "verdict":"pass","reviewer":"actual-human-reviewer",
                "assess_ref":"research://assess/report-001",
                "tradability_ref":"research://tradability/001",
                "stability_ref":"research://stability/001",
                "tradability_passed":True,"stability_passed":True,
                "key_strengths":["OOS daily ICIR above threshold"],
                "key_weaknesses":["Ridge measured in screening only"],
            })
        self.assertEqual(receipt["research_object"]["status"],"terminal_admitted")
        self.assertEqual(self.backend.persist_calls,1)
        with self.assertRaises(WorkflowConflict):
            AdmissionAdapter(self.store,backend=self.backend).commit(
                self.id,expected_revision=5,review={"verdict":"pass"})

    def test_cpu_holdout_prevents_reuse_of_screening_dates(self):
        _,review=self.complete()
        self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        holdout=IndependentHoldoutAdapter(self.store,backend=self.backend,platform=object())
        with self.assertRaises(WorkflowConflict):
            holdout.confirm(self.id,expected_revision=4,fidelity_review=review,
                            start_date="2025-06-01",end_date="2025-06-30")

    def test_missing_holdout_evidence_blocks_confirmation_without_resubmitting(self):
        _,review=self.complete()
        self.adapter.collect(self.id,expected_revision=3,fidelity_review=review)
        class MissingMetrics:
            calls=0
            def submit(self,**kwargs):
                self.calls+=1
                return {"ok":True,"tasks":{"csv_ic":{"run_id":"task-52","feature":"fake_test_52"}}}
            def check(self,**kwargs):
                return {"failureLayer":"check_done","evidence":{}}
        backend=MissingMetrics()
        holdout=IndependentHoldoutAdapter(self.store,backend=self.backend,platform=backend)
        with self.assertRaises(EvidenceError):
            holdout.confirm(self.id,expected_revision=4,fidelity_review=review)
        self.assertEqual(self.store.get(self.id)["status"],"awaiting_confirmation")
        with self.assertRaises(WorkflowConflict):
            holdout.confirm(self.id,expected_revision=4,fidelity_review=review)
        self.assertEqual(backend.calls,1)

    def fusion_plan(self):
        return {
            "base_factor_name":self.fac["name"],
            "similar_factor_name":"ExistingLiquidityFactor",
            "method":"条件化压力差异与既有流动性状态",
            "fusion_hypothesis":"成交失衡冲突在不同流动性条件下可能更有增量预测能力",
            "falsifiable_increment":"在同一独立保留期、同一价格目标上，融合信号的绝对 ICIR 高于两条原信号",
            "alternative_explanation":"融合结果只是对已有流动性状态的重复加权",
            "factor_spec":{
                "name":"DDJCh01FusionFactor",
                "formula":"state_gated_imbalance_conflict",
                "intuition":"在流动性状态门控下测量失衡冲突",
                "hypothesis":"成交失衡冲突在不同流动性条件下可能更有增量预测能力",
                "tags":["daodejing","fusion"],
                "params":{},"categories":["AG"],
                "required_data":["trade","orderbook"],
                "feature_uses_future":False,
            }
        }

    def start_fusion(self):
        _,review=self.complete(r2=0.91,residual=0.001)
        screening=self.adapter.collect(self.id,expected_revision=3,fidelity_review=review,
                                        nearest_factors=["ExistingLiquidityFactor"])
        self.assertEqual(screening["research_object"]["status"],"awaiting_fusion")
        fusion=FusionAdapter(self.store,backend=self.backend)
        plan=self.fusion_plan()
        created=fusion.plan(self.id,plan,expected_revision=4,
                            capabilities=["orderbook","trade"])
        self.assertEqual(created["status"],"planned")
        self.assertEqual(fusion.plan(self.id,plan,expected_revision=4)["status"],"planned")
        begin=fusion.begin(self.id,expected_revision=4)
        self.assertEqual(begin["status"],"prepared")
        rid=begin["run_id"]
        fused_file=self.path / "DDJCh01FusionFactor.h"
        fused_file.write_text("#pragma once\n// artificial fused factor test\n",encoding="utf-8")
        f=self.backend.runs[rid]["factors"][0]
        f.update({
            "status":"done","failure_layer":"check_done",
            "factor_file":str(fused_file),
            "evidence":{
                "eval_metrics":{
                    "core_metrics":{"screening":{
                        "icir":0.62,"spearman":0.032,"zero_ratio":0.05,
                        "pair":"X.fused vs Y.target_5s",
                    }},
                },
                "ridge_svd_agg":{"R2_X":0.45,"res_IC":0.02,"engine":"gpu"},
            },
        })
        fidelity={
            "passed":True,"reviewer":"factor-reviewer",
            "evidence_ref":"review://actual-source-fusion",
            "sha256":hashlib.sha256(fused_file.read_bytes()).hexdigest(),
        }
        passed=fusion.collect(self.id,expected_revision=4,fidelity_review=fidelity)
        self.assertEqual(passed["fusion"],"screening_passed_not_yet_confirmed")
        self.assertEqual(self.store.get(self.id)["status"],"awaiting_fusion")
        return fusion,fused_file

    def test_fusion_plan_real_screen_and_paired_holdout_success(self):
        fusion,fused_file=self.start_fusion()
        similar=self.path/"ExistingLiquidityFactor.h"
        similar.write_text("#pragma once\n// real-nearest fixture\n",encoding="utf-8")
        class ThreeWayCPU:
            def __init__(self):
                self.submits=[]
            def submit(self,**kwargs):
                self.submits.append(kwargs)
                index=len(self.submits)
                return {"ok":True,"tasks":{"csv_ic":{
                    "feature":f"factor_test_{index}","run_id":f"cpu-real-{index}"
                }}}
            def check(self,**kwargs):
                stem=Path(kwargs["factor_file"]).stem
                icir={
                    "DaoDeJing_Ch01_ImbalanceDisagreement":0.44,
                    "ExistingLiquidityFactor":0.43,
                    "DDJCh01FusionFactor":0.63,
                }[stem]
                return {"failureLayer":"check_done","evidence":{
                    "eval_metrics":{"core_metrics":{"screening":{
                        "icir":icir,"spearman":0.022,
                        "zero_ratio":0.1,"pair":f"X.{stem} vs Y.target_5s"
                    }}}
                }}
        platform=ThreeWayCPU()
        result=FusionConfirmationAdapter(self.store,backend=self.backend,platform=platform).confirm(
            self.id,expected_revision=4,nearest_source_file=str(similar),
            review={"reviewer":"independent-researcher",
                    "evaluation_ref":"protocol://same-target-Y.target_5s",
                    "allow_single_holdout_comparison":True})
        self.assertEqual(len(platform.submits),3)
        self.assertEqual(result["research_object"]["status"],"terminal_fused")
        self.assertGreater(result["holdout"]["delta_abs_icir"],0.05)
        self.assertEqual(self.backend.persist_calls,1)
        self.assertEqual(self.store.next_object()["object_id"],"RO-DDJ-002")
        with self.assertRaises(WorkflowConflict):
            FusionConfirmationAdapter(self.store,backend=self.backend,platform=platform).confirm(
                self.id,expected_revision=4,nearest_source_file=str(similar),
                review={"reviewer":"independent-researcher",
                        "evaluation_ref":"protocol://same-target-Y.target_5s",
                        "allow_single_holdout_comparison":True})
        self.assertEqual(len(platform.submits),3)

    def test_fusion_can_only_use_evidenced_nearest_and_full_review(self):
        _,review=self.complete(r2=0.93,residual=0.001)
        self.adapter.collect(self.id,expected_revision=3,fidelity_review=review,
                             nearest_factors=["ExistingLiquidityFactor"])
        bad=self.fusion_plan()
        bad["similar_factor_name"]="ModelInventedFactor"
        with self.assertRaises(contracts.ContractError):
            generate_plan(self.store.get(self.id),response=bad)
        correct=self.fusion_plan()
        self.assertEqual(
            generate_plan(self.store.get(self.id),response=correct,
                          capabilities=["orderbook","trade"])["factor_spec"]["name"],
            "DDJCh01FusionFactor")

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
