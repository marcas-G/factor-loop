"""Deterministic corpus research tests. No external model or platform is called."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.corpus_autoloop import CorpusAutoloop, WorkflowConflict
from core.corpus_autoloop import contracts
from core.corpus_autoloop.corpus import load_chapters
from core.corpus_autoloop.generator import generate_hypothesis,generate_factor,generate_split,factor_handoff

ROOT=Path(__file__).resolve().parents[1]


def research_hypothesis():
    return {
        "source_quote":"道可道",
        "source_principle":"原文强调语言表述与真实对象的差别",
        "market_analogy":"单一盘口代理与多过程的交易状态可能有偏差",
        "hypothesis":"盘口单一表示与其补充过程的差异可能包含未来价格响应信息",
        "observable_prediction":"在当前盘口状态相近时，补单状态不同对应不同未来响应",
        "alternative_explanation":"波动状态造成共同相关性",
        "required_data":["orderbook","trade"],
        "assumptions":["数据在预测起点前可用"],
        "causal_limit":"仅观察性相关，不能证明因果"
    }


def factor_spec(hyp=None,name="CorpusTestFactor"):
    return {
        "name":name,"formula":"sum(pre_t_order_imbalance) - sum(pre_t_order_replenishment)",
        "intuition":"测量盘口不平衡与补充过程的差异",
        "hypothesis":(hyp or research_hypothesis())["hypothesis"],
        "tags":["corpus_autoloop","test_only"],"params":{},
        "categories":["AG"],"required_data":["orderbook","trade"],
        "feature_uses_future":False,
    }


def report(name="CorpusTestFactor",novelty="independent",split="holdout_confirmation",
           predictive=True,fidelity=True):
    return {
        "factor_xname":name,"executor_run_id":"synthetic-run-1",
        "execution_ref":"fixture://not-a-real-platform-run",
        "library_snapshot_ref":"fixture://factor-library-v1",
        "data_split":split,
        "fidelity":{"passed":fidelity,"evidence_ref":"fixture://fidelity"},
        "predictive":{"passed":predictive,"metric_name":"ICIR",
                      "metric_value":0.2 if predictive else 0.01,
                      "evidence_ref":"fixture://screening"},
        "independence":{"decision":novelty,"r2_x":0.82 if novelty=="redundant" else 0.1,
                        "res_ic":0.001 if novelty=="redundant" else 0.06,
                        "nearest_factors":["ExistingFactor"] if novelty=="redundant" else [],
                        "evidence_ref":"fixture://ridge-svd"},
    }


def bad_fusion(name="CorpusTestFactor"):
    return {"base_factor_xname":name,"success":False,
            "method":"conditional_weighting","evidence_ref":"fixture://fusion-check",
            "failure_reason":"no independent incremental performance"}


def good_fusion(name="CorpusTestFactor"):
    return {"base_factor_xname":name,"success":True,
            "method":"conditional_weighting","evidence_ref":"fixture://fusion-holdout",
            "data_split":"holdout_confirmation","incremental_value":0.02,
            "fused_factor_xname":"FusedCorpusFactor","persist_ref":"fixture://persisted"}


def split_proposal():
    return {"failure_diagnosis":"相似因子融合没有提升独立确认表现；可能混合了不同承接机制",
            "children":[
                {"hypothesis":"仅考虑事件前的快速补充活动是否有预测性",
                 "split_reason":"区分短时间快速恢复机制",
                 "changed_mechanism":"fast_replenishment",
                 "observable_prediction":"快速补充组响应更短",
                 "alternative_explanation":"由波动状态解释","required_data":["orderbook"]},
                {"hypothesis":"仅考虑事件前的持续补充活动是否有预测性",
                 "split_reason":"区分持续补充机制",
                 "changed_mechanism":"persistent_replenishment",
                 "observable_prediction":"持续补充组响应更长",
                 "alternative_explanation":"由事件持续性解释","required_data":["orderbook"]},
            ]}


class CorpusAutoloopTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"research.sqlite3"
        self.w=CorpusAutoloop(self.db)
        self.w.seed()
        self.id="RO-DDJ-001"

    def step_hypothesis_factor(self,objid=None):
        objid=objid or self.id
        obj=self.w.get(objid)
        if obj["status"] in ("pending","awaiting_hypothesis"):
            h=research_hypothesis()
            self.w.record_hypothesis(objid,h,revision=obj["revision"])
            obj=self.w.get(objid)
        fac=factor_spec(obj["hypothesis"])
        self.w.record_factor(objid,fac,revision=obj["revision"])
        return self.w.get(objid)

    def test_all_81_source_chapters_provenance_and_order(self):
        ch=load_chapters()
        self.assertEqual(len(ch),81)
        self.assertEqual([x["chapter"] for x in ch],list(range(1,82)))
        self.assertTrue(ch[0]["text"].startswith("道可道"))
        self.assertEqual(ch[36]["part"],"道经")
        self.assertEqual(ch[37]["part"],"德经")
        self.assertTrue(ch[-1]["text"])
        self.assertEqual(len({x["content_sha256"] for x in ch}),81)

    def test_seed_is_idempotent_and_readable_after_restart(self):
        self.assertEqual(self.w.seed()["new_research_objects"],0)
        self.assertEqual(self.w.get(self.id)["depth"],0)
        self.assertEqual(self.w.next_object()["object_id"],self.id)
        other=CorpusAutoloop(self.db)
        self.assertEqual(other.status()["total_objects"],81)
        self.assertIn("道可道",other.get(self.id)["source"]["text"])

    def test_chapter_grounding_and_field_availability(self):
        obj=self.w.get(self.id)
        gen=generate_hypothesis(obj,response=research_hypothesis())
        self.assertTrue(gen["source_quote"] in obj["source"]["text"])
        bad=research_hypothesis()
        bad["source_quote"]="文中并不存在的虚构原文"
        with self.assertRaises(contracts.ContractError):
            generate_hypothesis(obj,response=bad)
        obj=self.w.record_hypothesis(self.id,research_hypothesis(),revision=1)
        self.assertEqual(obj["status"],"awaiting_factor")
        missing=factor_spec(obj["hypothesis"])
        missing["required_data"]=["nonexistent_future_column"]
        with self.assertRaises(ValueError):
            generate_factor(self.w.get(self.id),response=missing,capabilities=["orderbook","trade"])
        result=generate_factor(self.w.get(self.id),response=factor_spec(obj["hypothesis"]),
                               capabilities=["orderbook","trade"])
        self.assertFalse(result["feature_uses_future"])

    def test_confirmed_independent_admission_requires_receipt(self):
        obj=self.step_hypothesis_factor()
        handoff=factor_handoff(obj)
        self.assertEqual(handoff["execution_status"],"not_submitted")
        self.assertEqual(handoff["factors"][0]["name"],"CorpusTestFactor")
        self.assertNotIn("run_id",handoff)
        screening=self.w.record_evaluation(self.id,report(split="screening"),revision=obj["revision"])
        self.assertEqual(screening["status"],"awaiting_confirmation")
        confirmed=self.w.record_evaluation(self.id,report(),revision=screening["revision"])
        self.assertEqual(confirmed["status"],"awaiting_admission")
        with self.assertRaises(contracts.ContractError):
            self.w.record_admission(self.id,{"factor_xname":"CorpusTestFactor",
                         "confirmation_ref":"fixture://independent-test"},revision=confirmed["revision"])
        saved=self.w.record_admission(self.id,{"factor_xname":"CorpusTestFactor",
                         "confirmation_ref":"fixture://independent-test",
                         "persist_ref":"fixture://persisted-library-row"},revision=confirmed["revision"])
        self.assertEqual(saved["status"],"terminal_admitted")
        self.assertEqual(self.w.next_object()["object_id"],"RO-DDJ-002")
        self.assertEqual(len(self.w.events(self.id)),5)

    def test_redundant_fusion_success_only_with_holdout_and_persist(self):
        obj=self.step_hypothesis_factor()
        r=self.w.record_evaluation(self.id,report(novelty="redundant"),revision=obj["revision"])
        self.assertEqual(r["status"],"awaiting_fusion")
        poor=good_fusion()
        poor["incremental_value"]=0
        with self.assertRaises(contracts.ContractError):
            self.w.record_fusion(self.id,poor,revision=r["revision"])
        result=self.w.record_fusion(self.id,good_fusion(),revision=r["revision"])
        self.assertEqual(result["status"],"terminal_fused")
        self.assertEqual(len(self.w.events(self.id)),4)

    def test_redundant_failure_splits_into_two_and_depth_is_bounded(self):
        obj=self.step_hypothesis_factor()
        r=self.w.record_evaluation(self.id,report(novelty="redundant"),revision=obj["revision"])
        s=self.w.record_fusion(self.id,bad_fusion(),revision=r["revision"])
        self.assertEqual(s["status"],"awaiting_split")
        proposal=generate_split(self.w.get(self.id),response=split_proposal())
        parent=self.w.record_split(self.id,proposal,revision=s["revision"])
        self.assertEqual(parent["status"],"terminal_split")
        children=[self.id+"-1",self.id+"-2"]
        self.assertEqual([self.w.get(x)["depth"] for x in children],[1,1])
        self.assertTrue(all(self.w.get(x)["status"]=="awaiting_factor" for x in children))
        self.assertEqual(self.w.next_object()["object_id"],children[0])

        obj=self.step_hypothesis_factor(children[0])
        r=self.w.record_evaluation(children[0],report(novelty="redundant"),revision=obj["revision"])
        f=self.w.record_fusion(children[0],bad_fusion(),revision=r["revision"])
        self.assertEqual(f["status"],"awaiting_split")
        sub=split_proposal()
        sub["children"][0]["hypothesis"]="只检验事件前1秒快速补单状态"
        sub["children"][1]["hypothesis"]="只检验事件前5秒持续补单状态"
        self.w.record_split(children[0],sub,revision=f["revision"])
        self.assertEqual(self.w.get(children[0]+"-1")["depth"],2)
        leaf=children[0]+"-1"
        obj=self.step_hypothesis_factor(leaf)
        result=self.w.record_evaluation(leaf,report(predictive=False),revision=obj["revision"])
        self.assertEqual(result["status"],"terminal_exhausted")
        with self.assertRaises(ValueError):
            generate_split(self.w.get(leaf),response=sub)
        self.assertLessEqual(self.w.status()["total_objects"],85)

    def test_bad_evaluation_cannot_be_used_for_admission_or_fusion(self):
        obj=self.step_hypothesis_factor()
        missing=report()
        del missing["execution_ref"]
        with self.assertRaises(contracts.ContractError):
            self.w.record_evaluation(self.id,missing,revision=obj["revision"])
        self.assertEqual(self.w.get(self.id)["revision"],obj["revision"])
        invalid=report()
        invalid["independence"]["decision"]="redundant"
        invalid["independence"]["nearest_factors"]=[]
        with self.assertRaises(contracts.ContractError):
            self.w.record_evaluation(self.id,invalid,revision=obj["revision"])

    def test_conflicting_revisions_and_no_silent_mutation(self):
        self.w.record_hypothesis(self.id,research_hypothesis(),revision=1)
        with self.assertRaises(WorkflowConflict):
            self.w.record_hypothesis(self.id,research_hypothesis(),revision=1)
        self.assertEqual(self.w.get(self.id)["status"],"awaiting_factor")

    def test_cli_source_to_research_hypothesis(self):
        fixture=Path(self.tmp.name)/"hypothesis.json"
        fixture.write_text(json.dumps(research_hypothesis(),ensure_ascii=False),encoding="utf-8")
        def run(*argv):
            return subprocess.run([sys.executable,"-m","core.corpus_autoloop.cli",
                                   "--db",str(self.db),*argv],
                                  cwd=ROOT,text=True,capture_output=True)
        next_result=run("next")
        self.assertEqual(next_result.returncode,0,next_result.stderr)
        self.assertEqual(json.loads(next_result.stdout)["object_id"],self.id)
        r=run("hypothesis","--object-id",self.id,"--expected-revision","1",
              "--response-file",str(fixture))
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)["status"],"awaiting_factor")
        self.assertEqual(json.loads(run("status").stdout)["total_objects"],81)

if __name__=="__main__":
    unittest.main()
