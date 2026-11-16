"""Controlled commitment to existing factor DB ONLY after CPU holdout confirmation.

Preserves the original quant-mcp persist_factor(commit) path. Assessment is
explicitly supplied and reviewed; the LLM response alone is never a receipt.
"""
from __future__ import annotations

from pathlib import Path

from .execution_adapter import EvidenceError, NativeQuantBackend
from .workflow import CorpusAutoloop, WorkflowConflict


class NativePersistBackend(NativeQuantBackend):
    def persist_factor(self, run_id, factor_index, mode, verdict):
        from core.mcp.tools.persist import persist_factor
        return persist_factor(run_id=run_id, factor_index=factor_index,
                              mode=mode, verdict=verdict)


class AdmissionAdapter:
    def __init__(self, store: CorpusAutoloop, backend=None):
        self.store=store
        self.backend=backend or NativePersistBackend()

    def commit(self, objid, *, expected_revision, review):
        obj=self.store.get(objid)
        if obj["status"]!="awaiting_admission" or obj["revision"]!=expected_revision:
            raise WorkflowConflict("object must have passed independent holdout and be awaiting_admission")
        final=obj["evaluation"]
        if not final or final["data_split"]!="holdout_confirmation":
            raise EvidenceError("missing CPU independent confirmation")
        if not final["fidelity"]["passed"] or not final["predictive"]["passed"]:
            raise EvidenceError("cannot admit failed holdout")
        if final["independence"]["decision"]!="independent":
            raise EvidenceError("cannot admit redundant/inconclusive factor")
        if not isinstance(review,dict) or review.get("verdict")!="pass":
            raise EvidenceError("explicit full research assessment with verdict=pass required")
        reviewer=review.get("reviewer")
        if not isinstance(reviewer,str) or len(reviewer.strip())<2:
            raise EvidenceError("identified reviewer required")
        for k in ("assess_ref","tradability_ref","stability_ref"):
            if not isinstance(review.get(k),str) or len(review[k].strip())<8:
                raise EvidenceError(f"missing independent assessment reference {k}")
        if review.get("tradability_passed") is not True or review.get("stability_passed") is not True:
            raise EvidenceError("full tradability and stability gates must pass")
        if not isinstance(review.get("key_strengths"),list) or not isinstance(review.get("key_weaknesses"),list):
            raise EvidenceError("full assess strengths and weaknesses required")
        # Screening's original state still holds check_done evidence; do not
        # replay assessor's prepare or commit before holdout.
        prior_events=self.store.events(objid)
        screening=next((ev["payload"]["report"] for ev in prior_events
                        if ev["kind"]=="evaluation" and
                        ev["payload"].get("report",{}).get("data_split")=="screening"),None)
        if screening is None:
            raise EvidenceError("cannot locate original screening execution")
        run_id=screening["executor_run_id"]
        state=self.backend.run_load(run_id)
        f=(state.get("factors") or [None])[0]
        if not f or f.get("failure_layer")!="check_done":
            raise EvidenceError("no original platform check_done")
        if f.get("verdict") and f["verdict"].get("verdict")!="pass":
            raise EvidenceError("original persisted verdict disagrees with admission")
        verdict={
            "xname": f["name"],"verdict":"pass",
            "key_strengths":review["key_strengths"],
            "key_weaknesses":review["key_weaknesses"],
            "suggested_iteration":review.get("suggested_iteration",""),
            "iterable":False,
        }
        # Recovery from crash between production commit and isolated corpus ledger:
        # if the real state already contains a pass receipt, reuse it.
        persisted=f.get("persisted")
        if not isinstance(persisted,dict) or persisted.get("status")!="evaluated":
            persisted=self.backend.persist_factor(
                run_id=run_id,factor_index=0,mode="commit",verdict=verdict)
            if not isinstance(persisted,dict) or persisted.get("status")!="evaluated":
                raise EvidenceError(f"actual persist_factor commit failed: {persisted}")
            saved=self.backend.run_save(run_id,{
                "factors.0.verdict":verdict,
                "factors.0.persisted":persisted,
            })
            if isinstance(saved,dict) and saved.get("ok") is False:
                raise EvidenceError("production factor persisted but state save failed; reconcile run")
        if persisted.get("xname")!=obj["factor"]["name"]:
            raise EvidenceError("production receipt factor differs from research candidate")
        receipt={
            "factor_xname":persisted["xname"],
            "confirmation_ref":final["execution_ref"],
            "persist_ref":f"quant-run://{run_id}/factor/0/persisted",
            "assessment_ref":review["assess_ref"],
            "persisted_status":persisted["status"],
        }
        result=self.store.record_admission(objid,receipt,revision=expected_revision)
        return {"research_object":result,"production_receipt":persisted,
                "holdout_confirmation_ref":final["execution_ref"]}
