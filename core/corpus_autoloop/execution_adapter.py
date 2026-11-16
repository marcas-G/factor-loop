"""Real quant-mcp run-state bridge for corpus research.

This module can create an actual quant-mcp run and persist its candidate in
the existing factor DB. It never calls platform submit/check by itself:
the existing run-factor-agent owns write/submit/check/restest. Importing
evidence is read-only. Independent holdout submission is intentionally blocked
until the platform can select and prove a different dataset.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .contracts import ContractError
from .workflow import CorpusAutoloop, WorkflowConflict, _json, _stamp


class EvidenceError(WorkflowConflict):
    """Missing, misattributed, or insufficient executor evidence."""


class NativeQuantBackend:
    """Lazy imports allow import and unit tests without a production Factor DB."""
    def run_init(self, *, idea, factors, parent_session):
        from core.mcp.tools.state import run_init
        return run_init(idea=idea, factors=factors, parentSession=parent_session)

    def persist_candidates(self, *, run_id, idea_text, factors):
        from core.mcp.tools.persist import persist_candidates
        return persist_candidates(run_id=run_id, idea_text=idea_text, factors=factors)

    def run_load(self, run_id):
        from core.mcp.tools.state import run_load
        return run_load(run_id=run_id)

    def run_save(self, run_id, patch):
        from core.mcp.tools.state import run_save
        return run_save(run_id=run_id, patch=patch)

    def run_list(self):
        from core.mcp.tools.state import run_list
        return run_list()


def _source_checksum(state):
    path = (state or {}).get("factor_file")
    if not path:
        raise EvidenceError("factor source path missing in actual run state")
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.suffix != ".h":
        raise EvidenceError("existing generated .h file required")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _float(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise EvidenceError(f"{name} must be an actual numeric metric")
    num = float(value)
    if not math.isfinite(num):
        raise EvidenceError(f"{name} must be finite")
    return num


def _metric_value(ev, key):
    summary = ((ev.get("eval_metrics") or {}).get("core_metrics") or {}).get("screening") or {}
    value = summary.get(key)
    if value is not None:
        return _float(value, f"core_metrics.screening.{key}")
    raw = ev.get("eval_metrics") or {}
    if key == "icir":
        return _float(raw.get("icir", raw.get("2_icir")), "eval_metrics.icir")
    if key == "spearman":
        return _float(raw.get("deep_best", {}).get("daily_rank_ic"), "deep_best.daily_rank_ic")
    raise EvidenceError(f"cannot derive {key} from platform result")


def evaluate_state(run_id, state, *, dataset_ref, library_snapshot_ref, fidelity,
                   nearest_factors=None, sparse_ratio=None,
                   icir_floor=0.3, rank_ic_floor=0.01):
    """Extract structured screening metrics from the *actual* quant-mcp state.

    Policy mirrors the assess skill's dual signal/effect gates, but is not its
    full tradability/stability assessment; never equate this with a final verdict.
    """
    if state.get("run_id") != run_id:
        raise EvidenceError("run_id mismatch")
    factors = state.get("factors") or []
    if len(factors) != 1:
        raise EvidenceError("expected one factor in this research execution")
    f = factors[0]
    if f.get("status") != "done" or f.get("failure_layer") != "check_done":
        raise EvidenceError("run-factor-agent has not finished check_done")
    evidence = f.get("evidence") or {}
    if not isinstance(evidence, dict) or not evidence.get("eval_metrics"):
        raise EvidenceError("actual check output eval_metrics missing")
    if f.get("persisted") or f.get("verdict"):
        raise EvidenceError(
            "existing assess already committed a verdict; cannot assume the new "
            "corpus confirmation/admission process still controls library writes"
        )
    sha = _source_checksum(f)
    if not isinstance(fidelity, dict):
        raise EvidenceError("explicit implementation-fidelity review is required")
    if (fidelity.get("sha256") != sha or
        type(fidelity.get("passed")) is not bool or
        not isinstance(fidelity.get("reviewer"), str) or
        not fidelity["reviewer"].strip() or
        not isinstance(fidelity.get("evidence_ref"), str) or
        not fidelity["evidence_ref"].strip()):
        raise EvidenceError("fidelity review must bind to actual .h SHA-256 and identified reviewer")
    # The sparse path must use daily IC, not falsely inflated pooled ICIR.
    metrics = evidence["eval_metrics"]
    sparse = sparse_ratio
    if sparse is None:
        sparse = metrics.get("zero_rate")
    if sparse is not None:
        sparse = _float(sparse, "zero_rate")
        if not 0 <= sparse <= 1:
            raise EvidenceError("invalid zero_rate")
    if sparse is not None and sparse >= 0.5:
        deep = metrics.get("deep_best") or {}
        icir = _float(deep.get("daily_icir"), "daily_icir (required for sparse signal)")
        rank_ic = _float(deep.get("daily_rank_ic"), "daily_rank_ic (required for sparse signal)")
        metric_kind = "daily"
    else:
        icir = _metric_value(evidence, "icir")
        rank_ic = _metric_value(evidence, "spearman")
        metric_kind = "screening"
    if sparse is None:
        raise EvidenceError("zero_rate must be sourced from actual platform evidence or a verified override")
    predictive_ok = abs(icir) >= icir_floor and abs(rank_ic) >= rank_ic_floor
    agg = evidence.get("ridge_svd_agg") or {}
    r2, res = agg.get("R2_X", agg.get("r2_x")), agg.get("res_IC", agg.get("res_ic"))
    if r2 is not None and res is not None:
        r2, res = _float(r2, "R2_X"), _float(res, "res_IC")
        if not -0.01 <= r2 <= 1.01:
            raise EvidenceError("R2_X outside plausible range")
    else:
        r2 = res = None
    near = [s for s in (nearest_factors or []) if isinstance(s, str) and s and s != f.get("name")]
    if r2 is None or res is None:
        decision = "inconclusive"
    elif r2 > 0.8 and abs(res) < 0.01:
        decision = "redundant" if near else "inconclusive"
    else:
        decision = "independent"
    if not dataset_ref or not library_snapshot_ref:
        raise EvidenceError("actual dataset and factor library snapshot references are required")
    # The result is an interpretation of existing evidence, not a synthesized metric.
    return {
        "factor_xname": f["name"],
        "executor_run_id": run_id,
        "execution_ref": f"quant-run://{run_id}/factor/0",
        "library_snapshot_ref": library_snapshot_ref,
        "dataset_ref": dataset_ref,
        "data_split": "screening",
        "fidelity": {"passed": fidelity["passed"], "evidence_ref": fidelity["evidence_ref"]},
        "predictive": {"passed": predictive_ok, "metric_name": f"{metric_kind}_ICIR",
                       "metric_value": icir,
                       "evidence_ref": f"quant-run://{run_id}/factor/0/eval_metrics"},
        "independence": {"decision": decision, "r2_x": r2, "res_ic": res,
                         "nearest_factors": near if decision == "redundant" else [],
                         "evidence_ref": f"quant-run://{run_id}/factor/0/ridge_svd_agg"},
        "audit": {"rank_ic": rank_ic, "zero_rate": sparse, "metric_kind": metric_kind,
                  "factor_file_sha256": sha, "fidelity_reviewer": fidelity["reviewer"],
                  "note": "screening only; full assess, costs and independent holdout remain required"},
    }


class CorpusExecutionAdapter:
    def __init__(self, store: CorpusAutoloop, backend=None):
        self.store = store
        self.backend = backend if backend is not None else NativeQuantBackend()
        with store._connection() as db:
            db.execute("""
            CREATE TABLE IF NOT EXISTS corpus_execution_links(
                object_id TEXT NOT NULL REFERENCES research_objects(object_id),
                phase TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                run_id TEXT UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('reserved','prepared','observed')),
                dataset_ref TEXT NOT NULL,
                library_snapshot_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(object_id,phase)
            )
            """)

    def _link(self, objid, phase="screening"):
        with self.store._connection() as db:
            row = db.execute(
                "SELECT * FROM corpus_execution_links WHERE object_id=? AND phase=?",
                (objid, phase)).fetchone()
            return dict(row) if row else None

    def _recover(self, token):
        # Original run_list omits parent_session; check each run via the real
        # run_load tool. Never infer ownership from newest mtime.
        matches = []
        for item in self.backend.run_list():
            rid = item.get("run_id")
            if not rid:
                continue
            state = self.backend.run_load(rid)
            if state.get("parent_session") == token:
                matches.append(rid)
        if len(matches) > 1:
            raise WorkflowConflict("multiple runs share ownership token; manual reconciliation required")
        return matches[0] if matches else None

    def begin(self, objid, *, expected_revision, dataset_ref, library_snapshot_ref):
        """Create/recover one real quant run, persist candidate exactly once.

        This writes to the existing idea DB via persist_candidates; opt-in only.
        It never starts a platform job. Caller must invoke an actual factor Agent.
        """
        obj = self.store.get(objid)
        if obj["revision"] != expected_revision or obj["status"] != "awaiting_evaluation":
            raise WorkflowConflict("stale object or not awaiting real screening evaluation")
        if not all(isinstance(x, str) and len(x.strip()) >= 8
                   for x in (dataset_ref, library_snapshot_ref)):
            raise WorkflowConflict("dataset_ref and library_snapshot_ref must be concrete identifiers")
        factor = obj["factor"]
        token = f"corpus:{objid}:screening:{expected_revision}"
        # Reserve before any external side effects; subsequent retries recover
        # from state.parent_session and do not create a second platform run.
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM corpus_execution_links WHERE object_id=? AND phase='screening'",
                             (objid,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO corpus_execution_links VALUES (?,?,?,?,?,?,?,?,?)",
                    (objid, "screening", token, None, "reserved", dataset_ref,
                     library_snapshot_ref, _stamp(), _stamp()))
            elif row["dataset_ref"] != dataset_ref or row["library_snapshot_ref"] != library_snapshot_ref:
                raise WorkflowConflict("execution already reserved with different dataset/library snapshot")
        link = self._link(objid)
        run_id = link["run_id"] or self._recover(token)
        factor_fields = {key: factor[key] for key in
                         ("name","formula","intuition","hypothesis","tags","categories","params")}
        if not run_id:
            created = self.backend.run_init(idea=obj["hypothesis"]["hypothesis"],
                                            factors=[factor_fields], parent_session=token)
            run_id = created["run_id"]
        state = self.backend.run_load(run_id)
        if state.get("parent_session") != token:
            raise WorkflowConflict("recovered run does not match ownership token")
        if state.get("idea_id") is None:
            saved = self.backend.persist_candidates(
                run_id=run_id, idea_text=obj["hypothesis"]["hypothesis"], factors=[factor_fields])
            if not isinstance(saved, dict) or saved.get("n_factors") != 1 or saved.get("ok") is False:
                raise WorkflowConflict("persist_candidates did not create exactly one factor")
        state = self.backend.run_load(run_id)
        if len(state.get("factors") or []) != 1 or state["factors"][0].get("name") != factor["name"]:
            raise WorkflowConflict("run candidate does not match research object")
        if not state.get("corpus_autoloop"):
            outcome = self.backend.run_save(run_id, {"corpus_autoloop": {
                "object_id": objid, "source_unit_id": obj["source_id"],
                "phase": "screening", "dataset_ref": dataset_ref,
                "library_snapshot_ref": library_snapshot_ref, "token": token}})
            if isinstance(outcome, dict) and outcome.get("ok") is False:
                raise WorkflowConflict(f"run_save failed: {outcome}")
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE corpus_execution_links SET run_id=?,status='prepared',updated_at=? "
                "WHERE object_id=? AND phase='screening' AND (run_id IS NULL OR run_id=?)",
                (run_id, _stamp(), objid, run_id))
        return {"object_id": objid, "run_id": run_id, "factor_index": 0,
                "status": "prepared", "requires_agent": True,
                "dataset_ref": dataset_ref, "library_snapshot_ref": library_snapshot_ref}

    def collect(self, objid, *, expected_revision, fidelity_review,
                nearest_factors=None, zero_rate=None):
        """Read *real* state written by platform_check_factor/restest, then
        atomically submit its normalized screening report to ResearchObject."""
        obj = self.store.get(objid)
        if obj["revision"] != expected_revision or obj["status"] != "awaiting_evaluation":
            raise WorkflowConflict("object not ready for a fresh evaluation")
        link = self._link(objid)
        if not link or not link["run_id"]:
            raise WorkflowConflict("start actual executor first (begin)")
        state = self.backend.run_load(link["run_id"])
        if state.get("parent_session") != link["token"]:
            raise EvidenceError("run ownership mismatch")
        if (state.get("corpus_autoloop") or {}).get("object_id") != objid:
            raise EvidenceError("run corpus metadata mismatch")
        report = evaluate_state(
            link["run_id"], state, dataset_ref=link["dataset_ref"],
            library_snapshot_ref=link["library_snapshot_ref"],
            fidelity=fidelity_review, nearest_factors=nearest_factors,
            sparse_ratio=zero_rate)
        if report["factor_xname"] != obj["factor"]["name"]:
            raise EvidenceError("renamed factor requires explicit alias audit before ingestion")
        result = self.store.record_evaluation(objid, report, revision=expected_revision)
        with self.store._connection() as db:
            db.execute("UPDATE corpus_execution_links SET status='observed',updated_at=? "
                       "WHERE object_id=? AND phase='screening'", (_stamp(),objid))
        return {"research_object": result, "report": report}
