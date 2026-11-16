"""A resumable source-unit research queue with bounded failure-driven splitting.

Opt-in only: this ledger never writes to the live Factor DB and never fabricates
backtests. An external execution Agent must supply verifiable experiment records.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import contracts
from .corpus import load_chapters

MAX_SPLIT_DEPTH = 2
ACTIVE = {
    "pending", "awaiting_hypothesis", "awaiting_factor", "awaiting_evaluation",
    "awaiting_confirmation", "awaiting_admission", "awaiting_fusion", "awaiting_split",
}
TERMINAL = {"terminal_admitted", "terminal_fused", "terminal_exhausted", "terminal_split"}
STATES = ACTIVE | TERMINAL


class WorkflowConflict(ValueError):
    """State, version, or idempotency violation."""


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _json(item):
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _default_db():
    return Path(os.getenv("CORPUS_AUTOLOOP_DB_PATH", "~/.quant-corpus-autoloop/research.sqlite3")).expanduser()


class CorpusAutoloop:
    """Single-runner workflow; SQLite CAS ensures no lost writes.

    The CLI has no distributed lease. Do not run parallel research executors on
    the same DB until explicit work ownership and lease expiry have been added.
    """

    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path is not None else _default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS corpus_units(
                    unit_id TEXT PRIMARY KEY,
                    chapter INTEGER NOT NULL UNIQUE,
                    document TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_objects(
                    object_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES corpus_units(unit_id),
                    parent_id TEXT REFERENCES research_objects(object_id),
                    depth INTEGER NOT NULL CHECK(depth BETWEEN 0 AND 2),
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision>0),
                    hypothesis_json TEXT,
                    factor_json TEXT,
                    evaluation_json TEXT,
                    fusion_json TEXT,
                    admission_json TEXT,
                    split_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_objects_source ON research_objects(source_id,depth);
                CREATE TABLE IF NOT EXISTS research_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_id TEXT NOT NULL REFERENCES research_objects(object_id),
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=30000")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _one(db, objid):
        row = db.execute("SELECT * FROM research_objects WHERE object_id=?", (objid,)).fetchone()
        if row is None:
            raise KeyError(f"unknown research object {objid}")
        data = dict(row)
        for k in ("hypothesis_json", "factor_json", "evaluation_json",
                  "fusion_json", "admission_json", "split_json"):
            data[k.replace("_json", "")] = json.loads(data.pop(k)) if data[k] else None
        return data

    @staticmethod
    def _check(db, objid, expected, allowed):
        obj = CorpusAutoloop._one(db, objid)
        if type(expected) is not int or obj["revision"] != expected:
            raise WorkflowConflict(f"stale revision: expected={expected}, actual={obj['revision']}")
        if obj["status"] not in allowed:
            raise WorkflowConflict(f"{objid}: status {obj['status']} not in {sorted(allowed)}")
        return obj

    @staticmethod
    def _change(db, objid, old_rev, new_status, kind, payload, **columns):
        if new_status not in STATES:
            raise WorkflowConflict("invalid status transition target")
        assignments = ["status=?", "revision=revision+1", "updated_at=?"]
        params = [new_status, _stamp()]
        for col, value in columns.items():
            if col not in ("hypothesis_json", "factor_json", "evaluation_json",
                           "fusion_json", "admission_json", "split_json"):
                raise WorkflowConflict("unapproved stored column")
            assignments.append(f"{col}=?")
            params.append(_json(value))
        sql = "UPDATE research_objects SET " + ",".join(assignments) + " WHERE object_id=? AND revision=?"
        result = db.execute(sql, params + [objid, old_rev])
        if result.rowcount != 1:
            raise WorkflowConflict("concurrent update detected")
        db.execute("INSERT INTO research_events(object_id,kind,payload,recorded_at) VALUES(?,?,?,?)",
                   (objid, kind, _json(payload), _stamp()))
        return CorpusAutoloop._one(db, objid)

    def seed(self) -> dict:
        """Idempotently register all 81 chapters. No network access or model call."""
        units = load_chapters()
        created = 0
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for u in units:
                row = db.execute("SELECT sha256 FROM corpus_units WHERE unit_id=?", (u["unit_id"],)).fetchone()
                if row is not None and row[0] != u["content_sha256"]:
                    raise WorkflowConflict(f"source text mutated after registration: {u['unit_id']}")
                if row is None:
                    db.execute("INSERT INTO corpus_units VALUES(?,?,?,?,?)",
                               (u["unit_id"], u["chapter"], u["title"],
                                u["content_sha256"], _json(u)))
                objid = "RO-DDJ-" + f"{u['chapter']:03d}"
                row = db.execute("SELECT source_id FROM research_objects WHERE object_id=?", (objid,)).fetchone()
                if row and row[0] != u["unit_id"]:
                    raise WorkflowConflict("root research object identifier reused")
                if row is None:
                    stamp = _stamp()
                    db.execute(
                        "INSERT INTO research_objects(object_id,source_id,parent_id,depth,status,revision,created_at,updated_at)"
                        " VALUES(?,?,NULL,0,'pending',1,?,?)",
                        (objid, u["unit_id"], stamp, stamp))
                    db.execute("INSERT INTO research_events(object_id,kind,payload,recorded_at) VALUES(?,?,?,?)",
                               (objid, "seed", _json({"unit_id":u["unit_id"]}), stamp))
                    created += 1
        return {"corpus_id":"daodejing-wangbi-81-v1","chapters":len(units),"new_research_objects":created}

    def _source(self, db, source_id):
        row = db.execute("SELECT payload FROM corpus_units WHERE unit_id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError("unknown chapter")
        return json.loads(row[0])

    def get(self, objid):
        with self._connection() as db:
            obj = self._one(db, objid)
            obj["source"] = self._source(db, obj["source_id"])
            return obj

    def next_object(self):
        """Return next active object. Keeps current task selected across restarts.

        Every original chapter is visited in order, including chapter texts that
        are wholly unrelated to finance. Children of a chapter are processed
        before the next chapter. The CLI does NOT itself claim multiworker leases.
        """
        with self._connection() as db:
            row = db.execute(
                "SELECT o.object_id FROM research_objects o JOIN corpus_units c ON c.unit_id=o.source_id "
                "WHERE o.status NOT LIKE 'terminal_%' "
                "ORDER BY c.chapter ASC, o.depth ASC, o.object_id ASC LIMIT 1").fetchone()
            if row is None:
                return None
            return self.get(row[0])

    def status(self):
        with self._connection() as db:
            counts = {r[0]:r[1] for r in db.execute(
                "SELECT status, COUNT(*) FROM research_objects GROUP BY status")}
            remaining = sum(v for k,v in counts.items() if k in ACTIVE)
            return {"states":counts,"open":remaining,
                    "total_objects":sum(counts.values()),
                    "total_events":db.execute("SELECT COUNT(*) FROM research_events").fetchone()[0]}

    def record_hypothesis(self, objid, doc, *, revision):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"pending","awaiting_hypothesis"})
            source = self._source(db, obj["source_id"])
            if obj["parent_id"] is None:
                contracts.hypothesis(doc, source["text"])
            else:
                raise WorkflowConflict("split child already contains its hypothesis; do not regenerate")
            return self._change(db,objid,obj["revision"],"awaiting_factor",
                                "hypothesis",{"hypothesis":doc},hypothesis_json=doc)

    def record_factor(self, objid, doc, *, revision):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"awaiting_factor"})
            hyp = obj["hypothesis"]
            if hyp is None:
                raise WorkflowConflict("no source-grounded hypothesis")
            contracts.factor_spec(doc, hyp["hypothesis"])
            return self._change(db,objid,obj["revision"],"awaiting_evaluation",
                                "factor_compiled",{"factor":doc},factor_json=doc)

    def record_evaluation(self, objid, report, *, revision):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"awaiting_evaluation","awaiting_confirmation"})
            contracts.evaluation(report, obj["factor"]["name"])
            if obj["status"] == "awaiting_confirmation" and report["data_split"] != "holdout_confirmation":
                raise WorkflowConflict("confirmation requires an untouched holdout assessment")
            if not report["fidelity"]["passed"] or not report["predictive"]["passed"]:
                next_status = "awaiting_split" if obj["depth"]<MAX_SPLIT_DEPTH else "terminal_exhausted"
            elif report["independence"]["decision"] == "inconclusive":
                next_status = "awaiting_evaluation"
            elif report["independence"]["decision"] == "redundant":
                next_status = "awaiting_fusion"
            elif report["data_split"] == "holdout_confirmation":
                next_status = "awaiting_admission"
            else:
                next_status = "awaiting_confirmation"
            return self._change(db,objid,obj["revision"],next_status,
                                "evaluation",{"status":next_status,"report":report},evaluation_json=report)

    def record_admission(self, objid, report, *, revision):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"awaiting_admission"})
            contracts.admission(report,obj["factor"]["name"])
            return self._change(db,objid,obj["revision"],"terminal_admitted",
                                "admitted",report,admission_json=report)

    def record_fusion(self, objid, report, *, revision):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"awaiting_fusion"})
            contracts.fusion(report,obj["factor"]["name"])
            if report["success"]:
                next_status = "terminal_fused"
            elif obj["depth"] < MAX_SPLIT_DEPTH:
                next_status = "awaiting_split"
            else:
                next_status = "terminal_exhausted"
            return self._change(db,objid,obj["revision"],next_status,
                                "fusion",{"status":next_status,"report":report},fusion_json=report)

    def record_split(self, objid, proposal, *, revision):
        """Failure -> exactly 2 distinct child hypotheses; never more than 2 edges deep."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            obj = self._check(db, objid, revision, {"awaiting_split"})
            if obj["depth"] >= MAX_SPLIT_DEPTH:
                raise WorkflowConflict("split depth reached limit")
            children = contracts.children(proposal,obj["hypothesis"]["hypothesis"])
            stamp = _stamp()
            for idx, child in enumerate(children, 1):
                child_id = f"{objid}-{idx}"
                # A split's child is a new research object with a concrete
                # hypothesis, not an undefined theme for freeform generation.
                doc = {"source_quote":obj["hypothesis"].get("source_quote",""),
                       "source_principle":obj["hypothesis"].get("source_principle",""),
                       "market_analogy":obj["hypothesis"].get("market_analogy",""),
                       "hypothesis":child["hypothesis"],
                       "observable_prediction":child["observable_prediction"],
                       "alternative_explanation":child["alternative_explanation"],
                       "required_data":child["required_data"],
                       "assumptions":[child["split_reason"]],
                       "causal_limit":obj["hypothesis"].get("causal_limit","仅为观察性假设"),
                       "split_mechanism":child["changed_mechanism"],
                       "parent_failure_ref":(obj["fusion"] or obj["evaluation"] or {}).get("evidence_ref",
                                              (obj["evaluation"] or {}).get("execution_ref",""))}
                db.execute(
                    "INSERT INTO research_objects(object_id,source_id,parent_id,depth,status,revision,"
                    "hypothesis_json,created_at,updated_at) VALUES(?,?,?,?, 'awaiting_factor',1,?,?,?)",
                    (child_id,obj["source_id"],objid,obj["depth"]+1,_json(doc),stamp,stamp))
                db.execute("INSERT INTO research_events(object_id,kind,payload,recorded_at) VALUES(?,?,?,?)",
                           (child_id,"split_child",_json({"parent_id":objid,"child":child}),stamp))
            return self._change(db,objid,obj["revision"],"terminal_split",
                                "split",proposal,split_json=proposal)

    def events(self, objid):
        with self._connection() as db:
            return [{"kind":r[0],"payload":json.loads(r[1]),"recorded_at":r[2]}
                    for r in db.execute("SELECT kind,payload,recorded_at FROM research_events "
                                        "WHERE object_id=? ORDER BY id", (objid,))]
