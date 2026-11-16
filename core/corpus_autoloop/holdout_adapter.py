"""CPU-only held-out date window verification for the existing platform.

The current GPU ridge_svd form fixes its input period; thus this module does
NOT claim independent GPU orthogonality. It re-evaluates predictive quality on
an explicitly separate CPU date range before allowing admission.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from .execution_adapter import EvidenceError, NativeQuantBackend
from .fixed_target import fixed_target_score
from .workflow import CorpusAutoloop, WorkflowConflict, _json, _stamp


DEFAULT_SCREENING_END = date(2025, 6, 30)
DEFAULT_HOLDOUT_START = "2025-07-01"
DEFAULT_HOLDOUT_END = "2025-12-31"


class NativeCPUHoldout:
    """Thin, real CPU-only submission API built on existing platform helpers."""
    def submit(self, *, factor_file, features, feeds, start_date, end_date):
        from core.platform import gpu

        @gpu._serialize_submit
        def submit_one():
            cookie = gpu.ensure_cookie(app=gpu.APP)
            if not cookie:
                raise EvidenceError("platform cookie unavailable")
            if not Path(factor_file).is_file():
                raise EvidenceError("factor source file missing")
            stem = Path(factor_file).stem
            before = {t.get("job_id") for t in gpu._tasks(cookie)
                      if t.get("feature","").startswith(f"{stem}_test_")}
            formkey = gpu._cpu_formkey(cookie)
            post = gpu._post_cpu(cookie, str(factor_file), features, formkey,
                                 feeds, start_date, end_date)
            if not post.get("ok"):
                raise EvidenceError(f"CPU holdout submit failed: {post.get('http_code')}")
            task = gpu._wait_new_cpu_tasks(
                cookie, stem, before, gpu.TASK_APPEAR_TIMEOUT_SEC)
            if not task.get("feature") or not task.get("run_id"):
                raise EvidenceError(f"CPU holdout task not found: {task.get('error')}")
            task.update({"engine":"cpu", "mode":"csv_ic"})
            return {"ok": True, "features": features, "tasks":{"csv_ic":task},
                    "date_range":{"start":start_date, "end":end_date}}
        return submit_one()

    def check(self, *, factor_file, factor_name, submission, check_output):
        from core.stages.check import check_factor_programmatic
        return check_factor_programmatic(
            {"name":factor_name,"factor_file":factor_file},
            submission,check_output)


class IndependentHoldoutAdapter:
    def __init__(self, store: CorpusAutoloop, *, backend=None, platform=None):
        self.store=store
        self.backend=backend or NativeQuantBackend()
        self.platform=platform or NativeCPUHoldout()
        with store._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS corpus_holdout_attempts(
                    object_id TEXT PRIMARY KEY REFERENCES research_objects(object_id),
                    screening_run_id TEXT NOT NULL,
                    feature_file_sha256 TEXT NOT NULL,
                    date_start TEXT NOT NULL,
                    date_end TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved','submitted','confirmed')),
                    task_json TEXT,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    @staticmethod
    def _dates(start, end):
        try:
            s,e=date.fromisoformat(start),date.fromisoformat(end)
        except (TypeError,ValueError) as exc:
            raise WorkflowConflict("holdout dates must be ISO YYYY-MM-DD") from exc
        if not (DEFAULT_SCREENING_END < s <= e):
            raise WorkflowConflict("holdout must be strictly after default CPU screening window ending 2025-06-30")
        return str(s),str(e)

    def confirm(self, objid, *, expected_revision, fidelity_review,
                start_date=DEFAULT_HOLDOUT_START, end_date=DEFAULT_HOLDOUT_END,
                output_dir=None):
        """Submit once to CPU holdout, check actual result, atomically record.

        If the network call crashes after submission and before receipt, the
        reserved row blocks blind retries: reconcile the platform job first.
        """
        start,end=self._dates(start_date,end_date)
        obj=self.store.get(objid)
        if obj["revision"]!=expected_revision or obj["status"]!="awaiting_confirmation":
            raise WorkflowConflict("requires an accepted screening result awaiting_confirmation")
        screening=obj["evaluation"]
        if not screening or screening["data_split"]!="screening":
            raise EvidenceError("prior screening report missing")
        if screening["independence"]["decision"]!="independent":
            raise EvidenceError("only independently screened factors can be holdout-confirmed here")
        if not screening["fidelity"]["passed"] or not screening["predictive"]["passed"]:
            raise EvidenceError("ineligible first-stage factor")
        run_id=screening["executor_run_id"]
        state=self.backend.run_load(run_id)
        if (state.get("corpus_autoloop") or {}).get("object_id")!=objid:
            raise EvidenceError("original run not owned by research object")
        factors=state.get("factors") or []
        if len(factors)!=1 or factors[0].get("failure_layer")!="check_done":
            raise EvidenceError("original factor not check_done")
        source=Path(factors[0]["factor_file"]).expanduser().resolve()
        if not source.is_file() or source.suffix!=".h":
            raise EvidenceError("actual generated .h is missing")
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=screening.get("audit",{}).get("factor_file_sha256"):
            raise EvidenceError("source file changed after screening; holdout invalid")
        if not isinstance(fidelity_review,dict) or fidelity_review.get("sha256")!=digest:
            raise EvidenceError("holdout fidelity review must match frozen source SHA-256")
        if not fidelity_review.get("passed") or not fidelity_review.get("evidence_ref"):
            raise EvidenceError("source fidelity must be confirmed before holdout")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM corpus_holdout_attempts WHERE object_id=?",(objid,)).fetchone()
            if row is None:
                db.execute("INSERT INTO corpus_holdout_attempts "
                           "(object_id,screening_run_id,feature_file_sha256,date_start,date_end,"
                           "status,created_at,updated_at) VALUES (?,?,?,?,?,'reserved',?,?)",
                           (objid,run_id,digest,start,end,_stamp(),_stamp()))
                submission=None
            else:
                if (row["screening_run_id"]!=run_id or
                    row["feature_file_sha256"]!=digest or
                    row["date_start"]!=start or row["date_end"]!=end):
                    raise WorkflowConflict("existing holdout task uses different inputs")
                if row["status"]!="submitted" or not row["task_json"]:
                    raise WorkflowConflict(
                        "holdout task has no submitted receipt; reconcile before retrying")
                submission=json.loads(row["task_json"])
        # A submitted task is recoverable by check-only. A crash between the
        # external POST and its receipt remains reserved, never auto-resubmitted.
        from core.stages.write_factor import extract_class_name_from_h, is_template_class
        class_name=extract_class_name_from_h(source) or factors[0].get("name") or obj["factor"]["name"]
        features=f"{class_name}<>" if is_template_class(source) else class_name
        feeds=",".join(f"SHFE-{c}" for c in obj["factor"]["categories"])
        if submission is None:
            submission=self.platform.submit(
                factor_file=str(source),features=features,feeds=feeds,
                start_date=start,end_date=end)
            task=(submission.get("tasks") or {}).get("csv_ic") or {}
            if not submission.get("ok") or not task.get("run_id") or not task.get("feature"):
                raise EvidenceError("actual CPU platform holdout task ID required")
            with self.store._connection() as db:
                db.execute("UPDATE corpus_holdout_attempts "
                           "SET status='submitted',task_json=?,updated_at=? WHERE object_id=?",
                           (_json(submission),_stamp(),objid))
        task=(submission.get("tasks") or {}).get("csv_ic") or {}
        if not task.get("run_id") or not task.get("feature"):
            raise EvidenceError("stored CPU holdout submission missing task identity")
        check_path=str(Path(output_dir or (self.store.path.parent/"holdout_checks"))/
                       f"{objid}_{task['run_id']}")
        Path(check_path).parent.mkdir(parents=True,exist_ok=True)
        checked=self.platform.check(
            factor_file=str(source),factor_name=features,
            submission=submission,check_output=check_path)
        if checked.get("failureLayer")!="check_done":
            raise EvidenceError(
                f"holdout check failed: {checked.get('failureLayer')}; original task remains submitted")
        original_pair=screening.get("audit",{}).get("screening_pair")
        if not isinstance(original_pair,str) or " vs " not in original_pair:
            raise EvidenceError("screening must lock an exact X/Y pair before holdout")
        target=original_pair.split(" vs ",1)[1].strip()
        fixed=fixed_target_score(checked,source,target=target,exact_pair=original_pair)
        zero,icir,rank=fixed["zero_ratio"],fixed["icir"],fixed["rank_ic"]
        score_kind="fixed_pair"
        # A holdout sign reversal is not replication, even if |ICIR| is large.
        screened_icir=screening["predictive"]["metric_value"]
        same_direction=(icir*screened_icir>0 and icir*rank>0)
        passed=(abs(icir)>=0.3 and abs(rank)>=0.01 and same_direction)
        taskid=str(task["run_id"])
        # Pull the frozen X/Y row from raw heldout CSV, never check output's
        # independently selected "best" summary.
        report={
            "factor_xname":obj["factor"]["name"],
            "executor_run_id":f"cpu-holdout-{taskid}",
            "execution_ref":f"quant-cpu-holdout://{taskid}/{task['feature']}",
            "library_snapshot_ref":screening["library_snapshot_ref"],
            "dataset_ref":f"cpu-holdout:{start}:{end}",
            "data_split":"holdout_confirmation",
            "fidelity":{"passed":True,"evidence_ref":fidelity_review["evidence_ref"]},
            "predictive":{"passed":passed,"metric_name":f"holdout_{score_kind}_ICIR",
                          "metric_value":icir,
                          "evidence_ref":f"quant-cpu-holdout://{taskid}/eval_metrics"},
            "independence":screening["independence"],
            "audit":{"rank_ic":rank,"zero_rate":zero,"source_sha256":digest,
                     "gpu_independence_reused_from_screening":True,
                     "holdout_cpu_only":True,"same_direction":same_direction,
                     "holdout_pair":fixed["pair"],"raw_csv_ref":fixed["csv_path"],
                     "date_range":{"start":start,"end":end}},
        }
        result=self.store.record_evaluation(objid,report,revision=expected_revision)
        with self.store._connection() as db:
            db.execute("UPDATE corpus_holdout_attempts SET status='confirmed',"
                       "report_json=?,updated_at=? WHERE object_id=?",
                       (_json(report),_stamp(),objid))
        return {"research_object":result,"report":report}
