"""Persistent, explicit human-review queue for proposed hypothesis refinements.

All proposal records live in the separate TreEvo DB. Accepting a proposal inserts
its node, edge and human decision in ONE SQLite transaction.
"""
from __future__ import annotations

import json

from .contracts import ContractError, validate
from .refinement import _hash
from .store import TreEvoStore, TreeConflict, TreeInvariantError, _canonical, _now


class ReviewQueue:
    def __init__(self, store: TreEvoStore):
        self.store = store
        with store._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS refinement_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    tree_id TEXT NOT NULL,
                    parent_node_id TEXT NOT NULL,
                    base_revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected')),
                    reviewer TEXT,
                    decision_reason TEXT,
                    decision_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(tree_id, parent_node_id) REFERENCES nodes(tree_id, node_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS ix_refinement_proposals_tree "
                       "ON refinement_proposals(tree_id,status,created_at)")

    @staticmethod
    def _verified_proposal(proposal):
        if not isinstance(proposal, dict):
            raise ContractError("proposal must be a JSON object")
        body = {k: v for k, v in proposal.items() if k != "proposal_id"}
        if proposal.get("proposal_id") != "RP-" + _hash(body, 24):
            raise ContractError("proposal_id does not match content fingerprint")
        node, edge = proposal.get("node"), proposal.get("edge")
        validate("node", node)
        validate("edge", edge)
        if (proposal.get("tree_id") != node["tree_id"] or
            proposal.get("parent_node_id") != node["parent_id"] or
            edge["tree_id"] != node["tree_id"] or
            edge["parent_node_id"] != node["parent_id"] or
            edge["child_node_id"] != node["node_id"]):
            raise ContractError("proposal node/edge ownership mismatch")
        if type(proposal.get("base_revision")) is not int or proposal["base_revision"] < 1:
            raise ContractError("missing positive base_revision")
        critique = proposal.get("critique", {})
        if not isinstance(critique, dict) or critique.get("decision") not in ("pass", "revise", "reject"):
            raise ContractError("proposal missing critic decision")
        checks = critique.get("checks", {})
        for k in ("parent_fidelity", "information_gain", "mechanism_clarity",
                  "discriminating_prediction", "evidence_discipline"):
            if type(checks.get(k)) is not bool:
                raise ContractError(f"critic check {k} must be boolean")
        return proposal

    def enqueue(self, proposals: list[dict]) -> dict:
        for item in proposals:
            self._verified_proposal(item)
        inserted = []
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in proposals:
                pid = item["proposal_id"]
                row = db.execute("SELECT payload,status FROM refinement_proposals WHERE proposal_id=?",
                                 (pid,)).fetchone()
                content = _canonical(item)
                if row is not None:
                    if row[0] != content:
                        raise TreeConflict(f"proposal_id {pid} already used for different payload")
                    inserted.append({"proposal_id": pid, "created": False, "status": row[1]})
                    continue
                tree = db.execute("SELECT revision FROM trees WHERE tree_id=?",
                                  (item["tree_id"],)).fetchone()
                if tree is None:
                    raise TreeInvariantError("unknown proposal tree")
                if tree[0] != item["base_revision"]:
                    raise TreeConflict("tree revision changed before proposal was queued")
                parent = db.execute("SELECT 1 FROM nodes WHERE tree_id=? AND node_id=?",
                                    (item["tree_id"], item["parent_node_id"])).fetchone()
                if not parent:
                    raise TreeInvariantError("proposal parent does not exist")
                self.store._ensure_phenomena(db, item["node"]["source_phenomena"])
                db.execute(
                    "INSERT INTO refinement_proposals "
                    "(proposal_id,tree_id,parent_node_id,base_revision,payload,status,created_at) "
                    "VALUES (?,?,?,?,?,'pending',?)",
                    (pid, item["tree_id"], item["parent_node_id"],
                     item["base_revision"], content, _now()))
                inserted.append({"proposal_id": pid, "created": True, "status": "pending"})
        return {"count": len(inserted), "proposals": inserted}

    def get(self, proposal_id: str) -> dict:
        with self.store._connect() as db:
            row = db.execute(
                "SELECT payload,status,reviewer,decision_reason,decision_at "
                "FROM refinement_proposals WHERE proposal_id=?",
                (proposal_id,)).fetchone()
        if row is None:
            raise KeyError("unknown proposal_id")
        return {"proposal": json.loads(row[0]), "status": row[1],
                "reviewer": row[2], "decision_reason": row[3], "decision_at": row[4]}

    def list(self, *, tree_id: str | None = None, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        with self.store._connect() as db:
            if tree_id:
                rows = db.execute(
                    "SELECT proposal_id,parent_node_id,base_revision,status,created_at "
                    "FROM refinement_proposals WHERE tree_id=? ORDER BY created_at,proposal_id LIMIT ?",
                    (tree_id, limit)).fetchall()
            else:
                rows = db.execute(
                    "SELECT proposal_id,parent_node_id,base_revision,status,created_at "
                    "FROM refinement_proposals ORDER BY created_at,proposal_id LIMIT ?",
                    (limit,)).fetchall()
        return [dict(zip(("proposal_id","parent_node_id","base_revision","status","created_at"),row))
                for row in rows]

    @staticmethod
    def _check_decision_metadata(reviewer: str, reason: str):
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("explicit reviewer identifier is required")
        if not isinstance(reason, str) or len(reason.strip()) < 8:
            raise ValueError("decision reason must be at least 8 characters")

    def accept(self, proposal_id: str, *, reviewer: str, reason: str) -> dict:
        self._check_decision_metadata(reviewer, reason)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,status FROM refinement_proposals WHERE proposal_id=?",
                             (proposal_id,)).fetchone()
            if row is None:
                raise KeyError("unknown proposal_id")
            item, status = json.loads(row[0]), row[1]
            if status == "accepted":
                return {"proposal_id": proposal_id, "status": "accepted", "created": False}
            if status == "rejected":
                raise TreeConflict("rejected proposal cannot be accepted")
            critique = item["critique"]
            if critique["decision"] != "pass" or not all(critique["checks"].values()):
                raise TreeInvariantError("critic did not pass; revise and regenerate instead")
            output = self.store._add_refinement_tx(
                db, item["edge"], item["node"], item["base_revision"])
            db.execute(
                "UPDATE refinement_proposals SET status='accepted',reviewer=?,decision_reason=?,decision_at=? "
                "WHERE proposal_id=?", (reviewer, reason, _now(), proposal_id))
            return {"proposal_id": proposal_id, "status": "accepted", **output}

    def reject(self, proposal_id: str, *, reviewer: str, reason: str) -> dict:
        self._check_decision_metadata(reviewer, reason)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM refinement_proposals WHERE proposal_id=?",
                             (proposal_id,)).fetchone()
            if row is None:
                raise KeyError("unknown proposal_id")
            if row[0] == "accepted":
                raise TreeConflict("cannot reject accepted proposal; add new evidence instead")
            if row[0] == "rejected":
                return {"proposal_id": proposal_id, "status": "rejected", "created": False}
            db.execute(
                "UPDATE refinement_proposals SET status='rejected',reviewer=?,decision_reason=?,decision_at=? "
                "WHERE proposal_id=?", (reviewer, reason, _now(), proposal_id))
            return {"proposal_id": proposal_id, "status": "rejected", "created": True}
