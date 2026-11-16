"""Hypothesis Refinement Agent tests: no real model, market data, or backtests."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.tre_evo import TreEvoStore, TreeConflict, TreeInvariantError
from core.tre_evo.contracts import ContractError
from core.tre_evo.model_client import ChatCompletionsClient, ModelError, read_json_text
from core.tre_evo.refinement import propose, validate_critique
from core.tre_evo.review_queue import ReviewQueue

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "docs" / "standardization" / "examples"


def fixture(name):
    return json.loads((EX / (name + ".json")).read_text(encoding="utf-8"))


class RefinementAgentTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "tre-evo.db"
        self.store = TreEvoStore(self.path)
        self.store.create_root(fixture("hypothesis-root"))
        self.store.record_phenomenon(fixture("phenomenon"))
        self.queue = ReviewQueue(self.store)
        self.gen = fixture("refinement-generation")
        self.critique = fixture("refinement-critique")

    def generate(self, generation=None, critique=None, *, max_candidates=2):
        return propose(
            self.store, "TREE-DEMO-001", "H-DEMO-ROOT",
            generation=generation if generation is not None else self.gen,
            critique=critique if critique is not None else self.critique,
            max_candidates=max_candidates, phenomenon_ids=["P-DEMO-001"],
        )

    def test_proposal_queue_does_not_mutate_tree_until_human_accepts(self):
        result = self.generate()
        self.assertEqual(result["revision"], 1)
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["node"]["evidence_status"], "untested")
        self.assertEqual(proposal["node"]["node_status"], "open")
        self.assertEqual(proposal["edge"]["source_evidence_refs"], [])
        response = self.queue.enqueue(result["proposals"])
        self.assertEqual(response["count"], 1)
        self.assertTrue(response["proposals"][0]["created"])
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 1)
        self.assertEqual(len(self.store.tree("TREE-DEMO-001")["nodes"]), 1)
        self.assertEqual(self.queue.get(proposal["proposal_id"])["status"], "pending")
        accepted = self.queue.accept(
            proposal["proposal_id"], reviewer="test-human",
            reason="研究机制角色更加具体，且明确了与备择解释的观测区别"
        )
        self.assertTrue(accepted["created"])
        self.assertEqual(accepted["revision"], 2)
        self.assertEqual(self.queue.get(proposal["proposal_id"])["status"], "accepted")
        self.assertEqual(self.queue.get(proposal["proposal_id"])["reviewer"], "test-human")
        self.assertEqual(len(TreEvoStore(self.path).tree("TREE-DEMO-001")["edges"]), 1)
        retried = self.queue.accept(
            proposal["proposal_id"], reviewer="test-human",
            reason="再次读取已经接受的评审记录"
        )
        self.assertFalse(retried["created"])
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 2)

    def test_reject_preserves_review_reason_and_tree(self):
        p = self.generate()["proposals"][0]
        self.queue.enqueue([p])
        rejected = self.queue.reject(
            p["proposal_id"], reviewer="reviewer", reason="补单机制仍需检查是否独立于原有波动状态"
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 1)
        self.assertEqual(self.queue.get(p["proposal_id"])["decision_reason"],
                         "补单机制仍需检查是否独立于原有波动状态")
        with self.assertRaises(TreeConflict):
            self.queue.accept(p["proposal_id"], reviewer="reviewer",
                              reason="不能反向接受已拒绝的提议")

    def test_critic_revise_blocks_accept_even_with_human_action(self):
        critique = copy.deepcopy(self.critique)
        critique["assessments"][0]["decision"] = "revise"
        critique["assessments"][0]["checks"]["discriminating_prediction"] = False
        p = self.generate(critique=critique)["proposals"][0]
        self.queue.enqueue([p])
        with self.assertRaises(TreeInvariantError):
            self.queue.accept(
                p["proposal_id"], reviewer="reviewer",
                reason="即便是人类操作也不能绕过批评审查结果"
            )
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 1)

    def test_invalid_critic_and_hallucinated_source_are_rejected(self):
        bad = copy.deepcopy(self.critique)
        bad["assessments"][0]["checks"]["parent_fidelity"] = False
        with self.assertRaises(ContractError):
            self.generate(critique=bad)
        generation = copy.deepcopy(self.gen)
        generation["candidates"][0]["phenomenon_refs"] = ["NOT-IN-STORE"]
        with self.assertRaises(ContractError):
            self.generate(generation=generation)

    def test_restatement_and_duplicate_sibling_are_rejected(self):
        duplicate = copy.deepcopy(self.gen)
        duplicate["candidates"][0]["statement"] = fixture("hypothesis-root")["statement"]
        with self.assertRaises(ContractError):
            self.generate(generation=duplicate)
        first = self.generate()["proposals"][0]
        self.queue.enqueue([first])
        self.queue.accept(first["proposal_id"], reviewer="reviewer",
                          reason="该细化明确补充了机制角色及可观测条件")
        with self.assertRaises(ContractError):
            self.generate()

    def test_stale_proposals_are_not_silently_attached(self):
        first = self.generate()["proposals"][0]
        alt = copy.deepcopy(self.gen)
        alt["candidates"][0]["statement"] = "在事件前成交压力相近时，先前波动状态也可能解释后续价格响应速度的分化。"
        alt["candidates"][0]["refinement_warrant"] = "把原有承接机制挑战进一步约束为波动状态的竞争性解释，并尝试区分二者。"
        alt["candidates"][0]["new_information"] = ["增加事件前波动状态的竞争解释"]
        second = self.generate(generation=alt)["proposals"][0]
        self.queue.enqueue([first, second])
        self.queue.accept(first["proposal_id"], reviewer="reviewer",
                          reason="补单解释与价格响应之间的可观察关联值得继续分析")
        with self.assertRaises(TreeConflict):
            self.queue.accept(second["proposal_id"], reviewer="reviewer",
                              reason="旧版本下的候选不应该在树已经改变后被写入")
        self.assertEqual(self.queue.get(second["proposal_id"])["status"], "pending")
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 2)

    def test_abstention_is_valid_and_creates_no_work_item(self):
        abstain = {"diagnosis": {
            "focus_gap": "没有可追踪的异常现象",
            "why_this_gap": "缺少观测条件，任何拆分都可能只是词语归类",
            "other_open_gaps": ["观测数据覆盖不足"],
        }, "candidates": [], "abstain_reason": "缺少能够产生差异预测的研究抓手"}
        result = self.generate(generation=abstain, critique=None)
        self.assertEqual(result["proposals"], [])
        self.assertEqual(self.queue.enqueue(result["proposals"])["count"], 0)
        self.assertEqual(len(self.queue.list()), 0)

    def test_mocked_model_proposal_and_critic_are_separate_calls(self):
        class FakeProvider:
            def __init__(self, gen, review):
                self.responses = [gen, review]
                self.system_prompts = []
            def complete(self, system, user):
                self.system_prompts.append(system)
                return self.responses.pop(0)
        client = FakeProvider(self.gen, self.critique)
        result = propose(self.store, "TREE-DEMO-001", "H-DEMO-ROOT", client=client,
                         phenomenon_ids=["P-DEMO-001"])
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(len(client.system_prompts), 2)
        self.assertIn("细化", client.system_prompts[0])
        self.assertIn("批评", client.system_prompts[1])
        self.assertEqual(self.store.tree("TREE-DEMO-001")["revision"], 1)

    def test_cli_full_offline_review_cycle(self):
        def run(*args):
            return subprocess.run(
                [sys.executable, "-m", "core.tre_evo.cli", "--db", str(self.path), *args],
                cwd=ROOT, capture_output=True, text=True)
        result = run(
            "propose-refinements", "--tree-id", "TREE-DEMO-001",
            "--parent-id", "H-DEMO-ROOT", "--phenomenon-id", "P-DEMO-001",
            "--response-file", str(EX / "refinement-generation.json"),
            "--critique-file", str(EX / "refinement-critique.json")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal_id = json.loads(result.stdout)["proposals"][0]["proposal_id"]
        self.assertEqual(json.loads(run("show-refinement-proposal", "--proposal-id", proposal_id).stdout)
                         ["status"], "pending")
        accept = run("accept-refinement", "--proposal-id", proposal_id,
                     "--reviewer", "reviewer", "--reason",
                     "确认新的机制角色和可观察预测与原假设一致")
        self.assertEqual(accept.returncode, 0, accept.stderr)
        self.assertEqual(json.loads(accept.stdout)["status"], "accepted")
        show = run("show-tree", "--tree-id", "TREE-DEMO-001")
        self.assertEqual(len(json.loads(show.stdout)["nodes"]), 2)

    def test_model_url_security_and_response_parsing(self):
        with self.assertRaises(ModelError):
            ChatCompletionsClient(base_url="http://remote.example/v1", model="test")
        with self.assertRaises(ModelError):
            ChatCompletionsClient(base_url="https://secret:password@example.com/v1", model="test")
        self.assertEqual(read_json_text('{"ok":true}')["ok"], True)
        with self.assertRaises(ModelError):
            read_json_text("not JSON")

    def test_human_review_case_pack_is_illustrative_not_validated(self):
        pack = json.loads((ROOT / "docs" / "standardization" /
                           "refinement-review-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(pack["dataset_status"], "illustrative_seed_not_expert_labeled")
        self.assertGreaterEqual(len(pack["cases"]), 8)
        labels = {x["reference_review_label"] for x in pack["cases"]}
        self.assertIn("potentially_useful", labels)
        self.assertIn("reject", labels)
        self.assertTrue(all(x["annotation_status"] == "illustrative_seed_not_expert_labeled"
                            for x in pack["cases"]))


if __name__ == "__main__":
    unittest.main()
