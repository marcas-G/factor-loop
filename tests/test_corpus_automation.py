"""Automated stepping tests without any live platform or model credentials."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.corpus_autoloop.automation import CorpusSupervisor
from core.corpus_autoloop.cli import main as cli_main
from core.corpus_autoloop.workflow import CorpusAutoloop

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/"corpora"/"daodejing"/"examples"


class FixtureModel:
    def __init__(self):
        self.calls=[]
    def complete(self, system, user):
        self.calls.append((system,user))
        if "Source" in system or "source_quote" in system:
            return json.loads((SAMPLES/"chapter_001_hypothesis.json").read_text(encoding="utf-8"))
        if "factor_spec" in system:
            raise RuntimeError("unexpected fusion request in chapter-one test")
        return json.loads((SAMPLES/"chapter_001_factor.json").read_text(encoding="utf-8"))


class RefusalModel:
    def complete_from_corpus(self,obj):
        return {"error":"untranslatable",
                "reason":"已经逐行分析当前章节，无法找到不依赖未来字段的可测量市场对应关系。"}
    def complete(self,system,user):
        raise AssertionError("should not call direct completion after explicit refusal")


class CorpusAutomationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=CorpusAutoloop(self.root/"corpus.sqlite")
        self.store.seed()

    def test_one_chapter_runs_hypothesis_factor_then_stops_at_platform_gate(self):
        model=FixtureModel()
        supervisor=CorpusSupervisor(
            self.store,client=model,capabilities=["trade","orderbook"])
        report=supervisor.run(max_steps=12,object_id="RO-DDJ-001")
        self.assertEqual([x["action"] for x in report["steps"]],
                         ["hypothesis","factor","execution"])
        self.assertIn("--enable-platform-writes",report["halted_on"])
        self.assertEqual(self.store.get("RO-DDJ-001")["status"],"awaiting_evaluation")
        self.assertEqual(len(model.calls),2)
        self.assertEqual(self.store.get("RO-DDJ-002")["status"],"pending")
        self.assertEqual(self.store.status()["total_objects"],81)

    def test_prevent_factor_generation_without_verified_capability_manifest(self):
        supervisor=CorpusSupervisor(self.store,client=FixtureModel())
        output=supervisor.run(max_steps=5,object_id="RO-DDJ-001")
        self.assertEqual([x["action"] for x in output["steps"]],["hypothesis","factor"])
        self.assertIn("--capabilities-file",output["halted_on"])
        self.assertEqual(self.store.get("RO-DDJ-001")["status"],"awaiting_factor")

    def test_refusal_is_recorded_and_moves_to_next_chapter_without_fake_hypothesis(self):
        supervisor=CorpusSupervisor(self.store,client=RefusalModel())
        first=supervisor.step()
        self.assertEqual(first["action"],"record_infeasible")
        self.assertEqual(self.store.get("RO-DDJ-001")["status"],"terminal_exhausted")
        nxt=self.store.next_object()
        self.assertEqual(nxt["object_id"],"RO-DDJ-002")
        self.assertEqual(self.store.events("RO-DDJ-001")[-1]["kind"],"infeasible")
        self.assertIsNone(self.store.get("RO-DDJ-001")["hypothesis"])

    def test_auto_run_without_model_never_writes_fabricated_factors(self):
        supervisor=CorpusSupervisor(self.store,enable_platform_writes=True)
        out=supervisor.run(max_steps=50)
        self.assertEqual(out["count"],1)
        self.assertIn("LLM",out["halted_on"])
        self.assertEqual(self.store.status()["states"]["pending"],81)

    def test_cli_auto_run_without_model_is_safe_and_idempotent(self):
        file=str(self.root/"corpus.sqlite")
        code=cli_main(["--db",file,"auto-run","--object-id","RO-DDJ-001",
                       "--max-steps","5"])
        self.assertEqual(code,0)
        self.assertEqual(self.store.get("RO-DDJ-001")["status"],"pending")


if __name__ == "__main__":
    unittest.main()
