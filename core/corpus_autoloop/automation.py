"""Bounded, resumable *foreground* dispatcher for the 81-chapter corpus loop.

No daemon, hidden retries, invented receipts or silent approvals. One step
per state transition/side effect; run(max_steps) stops on first missing review
artifact or unresolved external task. Work is serial in chapter order.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .admission_adapter import AdmissionAdapter
from .agent_runner import OpenCodeRunner
from .execution_adapter import CorpusExecutionAdapter, EvidenceError
from .fusion_adapter import FusionAdapter, generate_plan
from .fusion_confirmation import FusionConfirmationAdapter
from .generator import generate_factor, generate_hypothesis, generate_split
from .holdout_adapter import IndependentHoldoutAdapter
from .workflow import CorpusAutoloop, WorkflowConflict, _json


class CorpusSupervisor:
    """Single-worker state machine around existing individual stage adapters.

    Requires externally supplied fidelity/full-assessment files; no auto-review
    may claim financial validity. Does not retry transient platform task submissions.
    """
    def __init__(self, store: CorpusAutoloop, *, client=None, capabilities=None,
                 reviews_dir=None, executor_model=None, executor_binary="opencode",
                 dataset_ref=None, library_snapshot_ref=None, enable_platform_writes=False,
                 runner=None, execution_backend=None, holdout_platform=None,
                 library_lookup=None):
        self.store=store
        self.client=client
        self.capabilities=capabilities
        self.reviews_dir=Path(reviews_dir).expanduser() if reviews_dir else None
        self.executor_model=executor_model
        self.executor_binary=executor_binary
        self.dataset_ref=dataset_ref
        self.library_snapshot_ref=library_snapshot_ref
        self.enable_platform_writes=enable_platform_writes
        self.runner=runner
        self.backend=execution_backend
        self.holdout_platform=holdout_platform
        self.library_lookup=library_lookup

    @staticmethod
    def _out(obj, action, *, result=None, blocked=None):
        return {
            "object_id":obj["object_id"],"chapter":obj["source"]["chapter"],
            "before":obj["status"],"action":action,
            "blocked":blocked,
            "result":result if blocked is None else None,
        }

    def _review(self,obj,name):
        if self.reviews_dir is None:
            return None
        file=self.reviews_dir/obj["object_id"]/f"{name}.json"
        if not file.is_file():
            return None
        return json.loads(file.read_text(encoding="utf-8"))

    def _requires_write(self,obj,name):
        if not self.enable_platform_writes:
            return self._out(obj,name,blocked="pass --enable-platform-writes to perform real quant-mcp/platform side effects")
        return None

    def _requires_model(self,obj,name):
        if self.client is None:
            return self._out(obj,name,blocked="configure LLM endpoint; no fabricated hypothesis/factor is permitted")
        return None

    def _runner(self):
        return self.runner or OpenCodeRunner(
            model=self.executor_model,binary=self.executor_binary,backend=self.backend)

    def _adapter(self):
        return CorpusExecutionAdapter(self.store,backend=self.backend)

    def _fusion(self):
        return FusionAdapter(self.store,backend=self.backend)

    def _failure(self,obj,stage,reference,diagnosis):
        result=self.store.record_infeasible(
            obj["object_id"],revision=obj["revision"],
            stage=stage,attempt_ref=reference,reason=diagnosis)
        return self._out(obj,"record_infeasible",result=result["status"])

    def step(self,object_id=None):
        """Do at most one stage transition; all retries require a new call."""
        obj=self.store.get(object_id) if object_id else self.store.next_object()
        if obj is None:
            return {"action":"complete","status":"no_active_research_objects"}
        status=obj["status"]
        rev=obj["revision"]
        oid=obj["object_id"]

        if status in ("pending","awaiting_hypothesis"):
            gate=self._requires_model(obj,"hypothesis")
            if gate:
                return gate
            response=self.client.complete_from_corpus(obj) if hasattr(self.client,"complete_from_corpus") else None
            if isinstance(response,dict) and response.get("error")=="untranslatable":
                reason=response.get("reason","")
                if not isinstance(reason,str) or len(reason.strip())<15:
                    return self._out(obj,"hypothesis",blocked="LLM refusal lacks concrete explanation")
                fingerprint=hashlib.sha256(_json(response).encode()).hexdigest()[:20]
                return self._failure(obj,"hypothesis",f"model-attempt://{oid}/{fingerprint}",reason)
            hyp=generate_hypothesis(obj,client=self.client,response=response)
            result=self.store.record_hypothesis(oid,hyp,revision=rev)
            return self._out(obj,"hypothesis",result=result["status"])

        if status=="awaiting_factor":
            gate=self._requires_model(obj,"factor")
            if gate:
                return gate
            if not isinstance(self.capabilities,list) or not self.capabilities:
                return self._out(obj,"factor",blocked="supply actual verified --capabilities-file before factor generation")
            spec=generate_factor(obj,client=self.client,capabilities=self.capabilities)
            result=self.store.record_factor(oid,spec,revision=rev)
            return self._out(obj,"factor",result=result["status"])

        if status=="awaiting_evaluation":
            gate=self._requires_write(obj,"execution")
            if gate:
                return gate
            adapter=self._adapter()
            link=adapter._link(oid)
            if link is None:
                if not self.dataset_ref or not self.library_snapshot_ref:
                    return self._out(obj,"execution-start",
                        blocked="dataset_ref and library_snapshot_ref are required to initialize an actual quant run")
                result=adapter.begin(oid,expected_revision=rev,dataset_ref=self.dataset_ref,
                                     library_snapshot_ref=self.library_snapshot_ref)
                return self._out(obj,"execution-start",result=result)
            if not link.get("run_id"):
                if not self.dataset_ref or not self.library_snapshot_ref:
                    return self._out(obj,"execution-recover",
                                     blocked="reserved run requires dataset and library references")
                result=adapter.begin(oid,expected_revision=rev,dataset_ref=self.dataset_ref,
                                     library_snapshot_ref=self.library_snapshot_ref)
                return self._out(obj,"execution-recover",result=result)
            state=adapter.backend.run_load(link["run_id"])
            factor=(state.get("factors") or [None])[0]
            if factor is None:
                raise EvidenceError("bound run has no candidate")
            if factor.get("status")=="failed":
                return self._failure(obj,"evaluation",f"quant-run://{link['run_id']}/factor/0",
                    "实际因子执行代理运行失败，状态为 failed；"
                    f"failure_layer={factor.get('failure_layer') or 'unknown'}；"
                    "该候选未完成可复核的因子回测。")
            if factor.get("status")=="done":
                review=self._review(obj,"fidelity")
                if not isinstance(review,dict):
                    return self._out(obj,"execution-collect",
                        blocked=f"missing {oid}/fidelity.json with actual .h SHA-256 and reviewer")
                near=self._review(obj,"nearest")
                if near is not None and not isinstance(near,list):
                    raise WorkflowConflict("nearest.json must be an array of existing factor names")
                outcome=adapter.collect(
                    oid,expected_revision=rev,fidelity_review=review,
                    nearest_factors=near)
                return self._out(obj,"execution-collect",result=outcome["research_object"]["status"])
            if factor.get("status") in ("submitting","checking","running"):
                return self._out(obj,"execution-run",
                    blocked=f"quant run {link['run_id']} is {factor.get('status')}; "
                            "inspect platform job and reconcile before any resubmission")
            if not self.executor_model and self.runner is None:
                return self._out(obj,"execution-run",blocked="configured OpenCode executor model required")
            result=self._runner().execute(obj,link["run_id"])
            return self._out(obj,"execution-run",result=result)

        if status=="awaiting_confirmation":
            gate=self._requires_write(obj,"execution-confirm")
            if gate:
                return gate
            review=self._review(obj,"fidelity")
            if review is None:
                return self._out(obj,"execution-confirm",blocked=f"missing {oid}/fidelity.json")
            result=IndependentHoldoutAdapter(
                self.store,backend=self.backend,platform=self.holdout_platform
            ).confirm(oid,expected_revision=rev,fidelity_review=review)
            return self._out(obj,"execution-confirm",result=result["research_object"]["status"])

        if status=="awaiting_admission":
            gate=self._requires_write(obj,"execution-admit")
            if gate:
                return gate
            review=self._review(obj,"assessment")
            if review is None:
                return self._out(obj,"execution-admit",
                    blocked=f"missing {oid}/assessment.json: full tradability/stability independent assessment required")
            result=AdmissionAdapter(self.store,backend=self.backend).commit(
                oid,expected_revision=rev,review=review)
            return self._out(obj,"execution-admit",result=result["research_object"]["status"])

        if status=="awaiting_fusion":
            gate=self._requires_write(obj,"fusion")
            if gate:
                return gate
            adapter=self._fusion()
            try:
                trial=adapter.get(oid)
            except KeyError:
                gate=self._requires_model(obj,"fusion-plan")
                if gate:
                    return gate
                # Obtain real library metadata for one evidenced neighbor.
                near=obj["evaluation"]["independence"]["nearest_factors"]
                if not near:
                    return self._out(obj,"fusion-plan",blocked="no verified existing neighbor factor")
                if self.library_lookup is None:
                    from core.mcp.tools.factor_db import factor_detail
                    neighbor=factor_detail(near[0])
                else:
                    neighbor=self.library_lookup(near[0])
                proposal=generate_plan(
                    obj,client=self.client,library_neighbor=neighbor,
                    capabilities=self.capabilities)
                result=adapter.plan(oid,proposal,expected_revision=rev,
                                    capabilities=self.capabilities)
                return self._out(obj,"fusion-plan",result=result["status"])
            if trial["status"]=="planned" or not trial.get("run_id"):
                result=adapter.begin(oid,expected_revision=rev)
                return self._out(obj,"fusion-start",result=result)
            if trial["status"]=="prepared":
                state=adapter.backend.run_load(trial["run_id"])
                factor=(state.get("factors") or [None])[0]
                if not factor:
                    raise EvidenceError("fused candidate missing in actual run")
                if factor.get("status")=="failed":
                    report={
                        "base_factor_xname":obj["factor"]["name"],
                        "method":trial["plan"]["method"],"success":False,
                        "evidence_ref":f"quant-run://{trial['run_id']}/factor/0",
                        "failure_reason":"真实融合因子执行失败："
                            f"failure_layer={factor.get('failure_layer') or 'unknown'}",
                    }
                    result=self.store.record_fusion(oid,report,revision=rev)
                    return self._out(obj,"fusion-failed",result=result["status"])
                if factor.get("status")=="done":
                    review=self._review(obj,"fusion_fidelity")
                    if review is None:
                        return self._out(obj,"fusion-collect",
                            blocked=f"missing {oid}/fusion_fidelity.json")
                    output=adapter.collect(oid,expected_revision=rev,
                                           fidelity_review=review)
                    return self._out(obj,"fusion-collect",result=output["fusion"])
                if factor.get("status") in ("submitting","checking","running"):
                    return self._out(obj,"fusion-run",
                        blocked=f"fusion run {trial['run_id']} is in-flight; reconcile instead of retrying")
                if not self.executor_model and self.runner is None:
                    return self._out(obj,"fusion-run",blocked="configured OpenCode executor model required")
                result=self._runner().execute(
                    obj,trial["run_id"],phase="fusion",
                    candidate=trial["plan"]["factor_spec"])
                return self._out(obj,"fusion-run",result=result)
            if trial["status"]=="screening_passed":
                review=self._review(obj,"fusion_review")
                if review is None:
                    return self._out(obj,"fusion-confirm",
                        blocked=f"missing {oid}/fusion_review.json: predeclared target, significance and full audits")
                nearest=obj["evaluation"]["independence"]["nearest_factors"]
                neighbor=self.library_lookup(nearest[0]) if self.library_lookup else None
                if neighbor is None:
                    from core.mcp.tools.factor_db import factor_detail
                    neighbor=factor_detail(nearest[0])
                file_path=(neighbor.get("factor") or {}).get("file_path")
                if not file_path:
                    return self._out(obj,"fusion-confirm",blocked="nearest library factor lacks file_path")
                output=FusionConfirmationAdapter(
                    self.store,backend=self.backend,platform=self.holdout_platform,
                    library_lookup=self.library_lookup
                ).confirm(oid,expected_revision=rev,nearest_source_file=file_path,review=review)
                return self._out(obj,"fusion-confirm",result=output["research_object"]["status"])
            if trial["status"]=="failed":
                raise WorkflowConflict("fusion trial failed but research object not transitioned; reconcile ledger")
            raise WorkflowConflict(f"unsupported fusion trial status {trial['status']}")

        if status=="awaiting_split":
            gate=self._requires_model(obj,"split")
            if gate:
                return gate
            proposal=generate_split(obj,client=self.client)
            result=self.store.record_split(oid,proposal,revision=rev)
            return self._out(obj,"split",result={
                "status":result["status"],
                "children":[f"{oid}-1",f"{oid}-2"],"depth":obj["depth"]+1,
            })

        return self._out(obj,"terminal",blocked="object is already terminal or has an unknown state")

    def run(self, max_steps=20, object_id=None):
        if type(max_steps) is not int or not 1<=max_steps<=200:
            raise ValueError("max_steps must be 1..200")
        events=[]
        for _ in range(max_steps):
            result=self.step(object_id=object_id)
            events.append(result)
            if result.get("blocked") or result.get("action")=="complete":
                break
            # On a specified object, do not keep executing after its terminal state.
            if object_id and result.get("result") in (
                "terminal_admitted","terminal_fused","terminal_exhausted","terminal_split"):
                break
        return {
            "steps":events,
            "count":len(events),
            "halted_on":events[-1].get("blocked") if events else None,
            "summary":self.store.status(),
        }
