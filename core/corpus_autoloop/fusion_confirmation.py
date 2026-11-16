"""Holdout comparison of original, nearest library factor and fused factor.

One *predeclared* paired date window; compare the same Y target, not whichever
best-looking x/y pair each run selects. Success requires actual production
persist receipt. A mismatch or missing platform artifact fails closed.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from .admission_adapter import NativePersistBackend
from .execution_adapter import EvidenceError, _metric_value, _float
from .fusion_adapter import FusionAdapter
from .holdout_adapter import NativeCPUHoldout, DEFAULT_HOLDOUT_START, DEFAULT_HOLDOUT_END, DEFAULT_SCREENING_END
from .fixed_target import fixed_target_score
from .workflow import CorpusAutoloop, WorkflowConflict, _json, _stamp


class FusionConfirmationAdapter:
    def __init__(self,store:CorpusAutoloop,*,backend=None,platform=None,library_lookup=None):
        self.store=store
        self.backend=backend or NativePersistBackend()
        self.platform=platform or NativeCPUHoldout()
        self.library_lookup=library_lookup
        self.trials=FusionAdapter(store,backend=self.backend)
        with store._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS corpus_fusion_holdout(
                    object_id TEXT PRIMARY KEY REFERENCES research_objects(object_id),
                    date_start TEXT NOT NULL,
                    date_end TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved','done')),
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def confirm(self,objid,*,expected_revision,nearest_source_file,
                review, start_date=DEFAULT_HOLDOUT_START,
                end_date=DEFAULT_HOLDOUT_END,delta_icir_floor=0.05):
        obj=self.store.get(objid)
        if obj["revision"]!=expected_revision or obj["status"]!="awaiting_fusion":
            raise WorkflowConflict("object is not awaiting fusion at given revision")
        trial=self.trials.get(objid)
        if trial["status"]!="screening_passed" or not trial["run_id"]:
            raise WorkflowConflict("actual fusion screening must pass first")
        if not isinstance(review,dict) or review.get("reviewer") in (None,""):
            raise EvidenceError("identified confirmation reviewer required")
        if not isinstance(review.get("evaluation_ref"),str) or len(review["evaluation_ref"])<8:
            raise EvidenceError("predeclared same-horizon comparison protocol required")
        for required in ("target","tradability_ref","stability_ref","statistical_protocol_ref"):
            if not isinstance(review.get(required),str) or len(review[required].strip())<5:
                raise EvidenceError(f"missing predeclared fusion review field {required}")
        if (review.get("tradability_passed") is not True or
            review.get("stability_passed") is not True or
            review.get("multiplicity_controlled") is not True):
            raise EvidenceError("fusion needs independent tradability, stability and multiplicity review")
        if review.get("allow_single_holdout_comparison") is not True:
            raise EvidenceError("explicit one-shot holdout authorization required")
        try:
            start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
        except (ValueError,TypeError) as exc:
            raise WorkflowConflict("invalid holdout dates") from exc
        if not DEFAULT_SCREENING_END<start<=end:
            raise WorkflowConflict("fusion holdout overlaps screening period")
        if type(delta_icir_floor) not in (int,float) or not 0<delta_icir_floor<1:
            raise WorkflowConflict("invalid predeclared fusion improvement threshold")
        plan=trial["plan"]
        # The nearest factor must really be the one recorded in the production
        # library. A model-provided path is not accepted as proof of identity.
        if self.library_lookup is None:
            from core.mcp.tools.factor_db import factor_detail
            library_detail=factor_detail(plan["similar_factor_name"])
        else:
            library_detail=self.library_lookup(plan["similar_factor_name"])
        fmeta=library_detail.get("factor") if isinstance(library_detail,dict) else None
        if (not isinstance(fmeta,dict) or
            fmeta.get("xname")!=plan["similar_factor_name"] or
            not fmeta.get("file_path") or
            Path(fmeta["file_path"]).expanduser().resolve()!=
                Path(nearest_source_file).expanduser().resolve()):
            raise EvidenceError("nearest C++ source not verified against actual factor library")
        original_run=self.backend.run_load(obj["evaluation"]["executor_run_id"])
        fused_run=self.backend.run_load(trial["run_id"])
        if (fused_run.get("parent_session")!=trial["token"] or
            (original_run.get("corpus_autoloop") or {}).get("object_id")!=objid):
            raise EvidenceError("fusion/original run provenance mismatch")
        original=(original_run.get("factors") or [None])[0]
        fused=(fused_run.get("factors") or [None])[0]
        if not original or not fused:
            raise EvidenceError("missing original or fused factor")
        sources={
            "original":(original["name"],Path(original["factor_file"]).resolve()),
            "similar":(plan["similar_factor_name"],Path(nearest_source_file).expanduser().resolve()),
            "fused":(fused["name"],Path(fused["factor_file"]).resolve()),
        }
        expected_fused_sha=trial["screening_report"].get("audit",{}).get("factor_file_sha256")
        if not expected_fused_sha:
            raise EvidenceError("fusion screening has no frozen source hash")
        if hashlib.sha256(sources["fused"][1].read_bytes()).hexdigest()!=expected_fused_sha:
            raise EvidenceError("fused .h changed after screening")
        for role,(name,path) in sources.items():
            if path.suffix!=".h" or not path.is_file():
                raise EvidenceError(f"{role} C++ source not found")
        # All labels, dates and comparison baselines are locked before the
        # first CPU submission. Never automatically retry partial POSTs.
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior=db.execute("SELECT 1 FROM corpus_fusion_holdout WHERE object_id=?",
                             (objid,)).fetchone()
            if prior:
                raise WorkflowConflict("fusion holdout already reserved; investigate before rerun")
            db.execute("INSERT INTO corpus_fusion_holdout VALUES (?,?,?,'reserved',NULL,?,?)",
                       (objid,str(start),str(end),_stamp(),_stamp()))
        outcomes={}
        from core.stages.write_factor import extract_class_name_from_h, is_template_class
        for role,(name,source) in sources.items():
            class_name=extract_class_name_from_h(source) or name
            features=f"{class_name}<>" if is_template_class(source) else class_name
            submission=self.platform.submit(
                factor_file=str(source),features=features,
                feeds=",".join(f"SHFE-{c}" for c in obj["factor"]["categories"]),
                start_date=str(start),end_date=str(end))
            task=(submission.get("tasks") or {}).get("csv_ic") or {}
            if not submission.get("ok") or not task.get("run_id") or not task.get("feature"):
                raise EvidenceError(f"{role} actual holdout submission failed")
            check_root=self.store.path.parent / "fusion_holdout_checks"
            check_root.mkdir(parents=True,exist_ok=True)
            checked=self.platform.check(
                factor_file=str(source),factor_name=name,submission=submission,
                check_output=str(check_root/f"{objid}_{role}_{task['run_id']}"))
            if checked.get("failureLayer")!="check_done":
                raise EvidenceError(f"{role} holdout check not complete")
            outcomes[role]={
                "task_id":task["run_id"],
                "execution_ref":f"quant-cpu-holdout://{task['run_id']}/{task['feature']}",
                "score":fixed_target_score(checked, source, target=review["target"]),
            }
        targets={o["score"]["target"] for o in outcomes.values()}
        if len(targets)!=1:
            raise EvidenceError(
                "fused/original/nearest evaluated different Y targets; aligned comparison required")
        if next(iter(targets))!=review["target"]:
            raise EvidenceError("observed Y target differs from predeclared fusion target")
        old=max(abs(outcomes["original"]["score"]["icir"]),
                abs(outcomes["similar"]["score"]["icir"]))
        fused_score=abs(outcomes["fused"]["score"]["icir"])
        delta=fused_score-old
        source_ref=obj["evaluation"]["execution_ref"]
        evidence_ref=";".join(o["execution_ref"] for o in outcomes.values())
        if delta<delta_icir_floor or abs(outcomes["fused"]["score"]["rank_ic"])<0.01:
            decision={
                "base_factor_xname":obj["factor"]["name"],
                "method":plan["method"],"success":False,
                "evidence_ref":evidence_ref,
                "failure_reason":f"独立确认同一 Y 目标上融合增益 {delta:.4f} 未过预定阈值 "
                                 f"{delta_icir_floor:.4f} 或 |rank_ic|<0.01",
            }
            result=self.store.record_fusion(objid,decision,revision=expected_revision)
            production=None
        else:
            f=fused
            persisted=f.get("persisted")
            if not isinstance(persisted,dict) or persisted.get("status")!="evaluated":
                verdict={"xname":f["name"],"verdict":"pass",
                         "key_strengths":[f"fusion holdout delta |ICIR|={delta:.4f}"],
                         "key_weaknesses":["one-shot holdout; GPU redundancy from screening"],
                         "suggested_iteration":"","iterable":False}
                persisted=self.backend.persist_factor(
                    run_id=trial["run_id"],factor_index=0,mode="commit",verdict=verdict)
                if not isinstance(persisted,dict) or persisted.get("status")!="evaluated":
                    raise EvidenceError(f"fusion persist failed: {persisted}")
                saved=self.backend.run_save(trial["run_id"],{
                    "factors.0.verdict":verdict,
                    "factors.0.persisted":persisted,
                })
                if isinstance(saved,dict) and saved.get("ok") is False:
                    raise EvidenceError("fusion factor persisted but receipt could not be saved")
            if persisted.get("xname")!=plan["factor_spec"]["name"]:
                raise EvidenceError("fused factor persistence identity mismatch")
            decision={
                "base_factor_xname":obj["factor"]["name"],
                "method":plan["method"],"success":True,
                "evidence_ref":evidence_ref,
                "source_evaluation_ref":source_ref,
                "confirmed_dataset_ref":f"cpu-fusion-holdout:{start}:{end}",
                "fused_factor_xname":persisted["xname"],
                "persist_ref":f"quant-run://{trial['run_id']}/factor/0/persisted",
                "data_split":"holdout_confirmation","incremental_value":delta,
            }
            result=self.store.record_fusion(objid,decision,revision=expected_revision)
            production=persisted
        receipt={"objects":outcomes,"delta_abs_icir":delta,
                 "holdout_window":{"start":str(start),"end":str(end)},
                 "evaluation_protocol":review["evaluation_ref"],
                 "target":review["target"],
                 "research_review":{
                     "reviewer":review["reviewer"],
                     "statistical_protocol_ref":review["statistical_protocol_ref"],
                     "tradability_ref":review["tradability_ref"],
                     "stability_ref":review["stability_ref"],
                     "multiplicity_controlled":True,
                 },
                 "result_status":result["status"],"decision":decision}
        with self.store._connection() as db:
            db.execute("UPDATE corpus_fusion_holdout SET status='done',receipt_json=?,updated_at=? "
                       "WHERE object_id=?",(_json(receipt),_stamp(),objid))
        return {"research_object":result,"holdout":receipt,"production_receipt":production}
