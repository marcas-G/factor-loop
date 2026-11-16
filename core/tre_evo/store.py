"""Separate, append-only SQLite ledger for TreEvo research trees.

This database never touches the production factors.db. SQLite transactions,
unique constraints and a tree revision provide local idempotence and CAS.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ContractError, validate


class TreeConflict(ValueError):
    """A conflicting update, duplicate identifier, or outdated tree revision."""


class TreeInvariantError(ValueError):
    """A hypothesis or evidence relationship would violate the tree contract."""


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db() -> Path:
    return Path(os.getenv("TREEVO_DB_PATH", "~/.quant-tre-evo/trees.sqlite3")).expanduser()


class TreEvoStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path is not None else _default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trees (
                    tree_id TEXT PRIMARY KEY,
                    root_node_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    tree_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    parent_id TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tree_id, node_id),
                    FOREIGN KEY (tree_id) REFERENCES trees(tree_id),
                    FOREIGN KEY (tree_id, parent_id) REFERENCES nodes(tree_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    tree_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    parent_node_id TEXT NOT NULL,
                    child_node_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tree_id, edge_id),
                    UNIQUE (tree_id, child_node_id),
                    CHECK (parent_node_id <> child_node_id),
                    FOREIGN KEY (tree_id, parent_node_id) REFERENCES nodes(tree_id, node_id),
                    FOREIGN KEY (tree_id, child_node_id) REFERENCES nodes(tree_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS phenomena (
                    phenomenon_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS phenomenon_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source_ref TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    review_status TEXT NOT NULL CHECK (review_status = 'unverified'),
                    imported_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_nodes_tree_parent ON nodes(tree_id, parent_id);
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _json_row(cursor):
        row = cursor.fetchone()
        return json.loads(row[0]) if row is not None else None

    def record_phenomenon(self, record: dict) -> dict:
        validate("phenomenon", record)
        pid = record["phenomenon_id"]
        content = _canonical(record)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM phenomena WHERE phenomenon_id=?", (pid,)).fetchone()
            if old is not None:
                if old[0] != content:
                    raise TreeConflict(f"phenomenon_id {pid} already used for other content")
                return {"phenomenon_id": pid, "created": False}
            db.execute("INSERT INTO phenomena VALUES (?,?,?)", (pid, content, _now()))
            return {"phenomenon_id": pid, "created": True}

    def create_root(self, node: dict) -> dict:
        validate("node", node)
        if node["parent_id"] is not None or node["node_type"] != "research_theme":
            raise TreeInvariantError("root must be a research_theme with parent_id=null")
        tree_id, node_id = node["tree_id"], node["node_id"]
        content = _canonical(node)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT root_node_id,revision FROM trees WHERE tree_id=?", (tree_id,)).fetchone()
            if row is not None:
                prior = db.execute("SELECT payload FROM nodes WHERE tree_id=? AND node_id=?",
                                   (tree_id, row[0])).fetchone()
                if row[0] != node_id or prior is None or prior[0] != content:
                    raise TreeConflict(f"tree {tree_id} already exists with a different root")
                return {"tree_id": tree_id, "root_node_id": node_id, "revision": row[1], "created": False}
            self._ensure_phenomena(db, node["source_phenomena"])
            now = _now()
            db.execute("INSERT INTO trees VALUES (?,?,?,?)", (tree_id, node_id, 1, now))
            db.execute("INSERT INTO nodes VALUES (?,?,?,?,?)", (tree_id, node_id, None, content, now))
            return {"tree_id": tree_id, "root_node_id": node_id, "revision": 1, "created": True}

    @staticmethod
    def _ensure_phenomena(db, source_ids: list[str]):
        for source_id in source_ids:
            if not db.execute("SELECT 1 FROM phenomena WHERE phenomenon_id=?", (source_id,)).fetchone():
                raise TreeInvariantError(
                    f"unregistered phenomenon {source_id}: import candidates is NOT evidence; "
                    "record and review a full Phenomenon first"
                )

    def add_refinement(self, edge: dict, child: dict, *, expected_revision: int) -> dict:
        validate("edge", edge)
        validate("node", child)
        tree_id = edge["tree_id"]
        if child["tree_id"] != tree_id or child["node_id"] != edge["child_node_id"]:
            raise TreeInvariantError("edge and child tree_id/node_id mismatch")
        if child["parent_id"] != edge["parent_node_id"]:
            raise TreeInvariantError("child.parent_id must match edge.parent_node_id")
        if child["node_type"] == "research_theme":
            raise TreeInvariantError("only root nodes may be research_theme")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
            raise TreeInvariantError("expected_revision must be a positive integer")
        edge_json, child_json = _canonical(edge), _canonical(child)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            root = db.execute("SELECT revision FROM trees WHERE tree_id=?", (tree_id,)).fetchone()
            if root is None:
                raise TreeInvariantError(f"unknown tree {tree_id}")
            old_edge = db.execute("SELECT payload FROM edges WHERE tree_id=? AND edge_id=?",
                                  (tree_id, edge["edge_id"])).fetchone()
            old_child = db.execute("SELECT payload FROM nodes WHERE tree_id=? AND node_id=?",
                                   (tree_id, child["node_id"])).fetchone()
            if old_edge is not None and old_child is not None:
                if old_edge[0] == edge_json and old_child[0] == child_json:
                    return {"tree_id": tree_id, "node_id": child["node_id"],
                            "revision": root[0], "created": False}
            if old_edge is not None or old_child is not None:
                raise TreeConflict("edge_id or node_id already used for different content")
            if expected_revision != root[0]:
                raise TreeConflict(f"tree {tree_id} expected revision {expected_revision}, actual {root[0]}")
            parent = db.execute("SELECT payload FROM nodes WHERE tree_id=? AND node_id=?",
                                (tree_id, edge["parent_node_id"])).fetchone()
            if parent is None:
                raise TreeInvariantError("missing parent node")
            parent_doc = json.loads(parent[0])
            if parent_doc["node_status"] == "archived":
                raise TreeInvariantError("cannot refine archived parent")
            if " ".join(parent_doc["statement"].split()) == " ".join(child["statement"].split()):
                raise TreeInvariantError("child statement is a verbatim restatement of parent")
            self._ensure_phenomena(db, child["source_phenomena"])
            now = _now()
            # A new child with one existing parent guarantees acyclicity and single-parent ownership.
            db.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                       (tree_id, child["node_id"], child["parent_id"], child_json, now))
            db.execute("INSERT INTO edges VALUES (?,?,?,?,?,?)",
                       (tree_id, edge["edge_id"], edge["parent_node_id"], edge["child_node_id"], edge_json, now))
            db.execute("UPDATE trees SET revision=revision+1 WHERE tree_id=?", (tree_id,))
            return {"tree_id": tree_id, "node_id": child["node_id"],
                    "revision": root[0] + 1, "created": True}

    def tree(self, tree_id: str) -> dict:
        with self._connect() as db:
            header = db.execute("SELECT root_node_id,revision,created_at FROM trees WHERE tree_id=?",
                                (tree_id,)).fetchone()
            if header is None:
                raise KeyError(f"unknown tree {tree_id}")
            nodes = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM nodes WHERE tree_id=? ORDER BY created_at,node_id", (tree_id,))]
            edges = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM edges WHERE tree_id=? ORDER BY created_at,edge_id", (tree_id,))]
            ids = sorted({p for n in nodes for p in n["source_phenomena"]})
            observations = []
            for pid in ids:
                record = db.execute("SELECT payload FROM phenomena WHERE phenomenon_id=?", (pid,)).fetchone()
                if record:
                    observations.append(json.loads(record[0]))
            return {"tree_id": tree_id, "root_node_id": header[0], "revision": header[1],
                    "created_at": header[2], "nodes": nodes, "edges": edges,
                    "source_phenomena": observations}

    def import_candidates(self, candidates: list[dict], *, source_ref: str) -> dict:
        """Stage original miner output WITHOUT promoting it to verified Phenomenon."""
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise ValueError("source_ref required: dataset/snapshot/provenance identifier")
        if not isinstance(candidates, list):
            raise ValueError("candidates must be a JSON array")
        prepared = []
        for item in candidates:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(k), (str, dict))
                for k in ("source_type", "representations", "observed_deviation", "matched_conditions")
            ):
                raise ValueError("each raw candidate requires source_type, representations, observed_deviation and matched_conditions")
            # Legacy phenomenon_id is batch-order-dependent: exclude it from stable fingerprint.
            signature = {k: v for k, v in item.items() if k != "phenomenon_id"}
            digest = hashlib.sha256((source_ref + "\n" + _canonical(signature)).encode("utf-8")).hexdigest()[:24]
            prepared.append(("CAND-" + digest, source_ref, item["source_type"],
                             _canonical(item), "unverified", _now()))
        inserted = 0
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in prepared:
                cursor = db.execute("INSERT OR IGNORE INTO phenomenon_candidates VALUES (?,?,?,?,?,?)", row)
                inserted += cursor.rowcount
        return {"provided": len(prepared), "new": inserted,
                "already_seen": len(prepared) - inserted, "review_status": "unverified"}

    def candidates(self, limit: int = 50) -> list[dict]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as db:
            return [
                {"candidate_id": cid, "source_ref": src, "source_type": kind,
                 "review_status": status, "raw": json.loads(raw)}
                for cid, src, kind, status, raw in db.execute(
                    "SELECT candidate_id,source_ref,source_type,review_status,raw_payload "
                    "FROM phenomenon_candidates ORDER BY imported_at,candidate_id LIMIT ?", (limit,))]
