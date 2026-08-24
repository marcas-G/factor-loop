"""Tests for the v18 factor suggestion / lineage data model."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.db import db  # noqa: E402
from core.db import init_db  # noqa: E402


def _new_conn():
    path = Path(tempfile.mktemp(suffix=".db"))
    init_db.init_db(path)
    return path, db.get_conn(path)


def _add_factor(conn, xname: str, status: str = "draft") -> None:
    conn.execute(
        "INSERT INTO factors(xname, status, formula_text) VALUES (?,?,?)",
        (xname, status, f"formula({xname})"),
    )


def test_lineage_dag_closure_and_profiles():
    path, conn_ctx = _new_conn()
    try:
        with conn_ctx as conn:
            for xname in ("A", "B", "C"):
                _add_factor(conn, xname)
            db.add_lineage_edge(
                conn, "A", "B", relation_type="iteration", origin="manual_backfill"
            )
            db.add_lineage_edge(
                conn, "B", "C", relation_type="repair", origin="retry"
            )

            edge_count = conn.execute(
                "SELECT COUNT(*) FROM factor_lineage_edges"
            ).fetchone()[0]
            assert edge_count == 2

            ancestors = db.get_ancestors(conn, "C")
            descendants = db.get_descendants(conn, "A")
            assert [(r[0], r[1]) for r in ancestors] == [("B", 1), ("A", 2)]
            assert [(r[0], r[1]) for r in descendants] == [("B", 1), ("C", 2)]

            a_profile = conn.execute(
                "SELECT * FROM factor_lineage_nodes WHERE xname='A'"
            ).fetchone()
            c_profile = conn.execute(
                "SELECT * FROM factor_lineage_nodes WHERE xname='C'"
            ).fetchone()
            assert a_profile["descendant_count"] == 2
            assert a_profile["max_descendant_depth"] == 2
            assert c_profile["parent_count"] == 1
            assert c_profile["depth_from_primary_root"] == 2

            branch = conn.execute(
                "SELECT * FROM factor_lineage_branches WHERE root_xname='A'"
            ).fetchone()
            assert branch["member_count"] == 3
            assert branch["max_depth"] == 2

            try:
                db.add_lineage_edge(conn, "C", "A", origin="manual_backfill")
                raise AssertionError("cycle was not rejected")
            except ValueError as exc:
                assert "cycle" in str(exc) or "环" in str(exc)
    finally:
        path.unlink(missing_ok=True)


def test_suggestion_lifecycle_and_legacy_id_migration():
    path, conn_ctx = _new_conn()
    try:
        with conn_ctx as conn:
            _add_factor(conn, "Source", "evaluated")
            _add_factor(conn, "Target", "evaluated")

            # Baseline v19 exposes a compatibility view. Recreate a physical legacy
            # table to exercise the v18 import + v19 retirement path.
            conn.execute("DROP VIEW IF EXISTS iterations")
            conn.execute(
                """CREATE TABLE iterations (
                       id INTEGER PRIMARY KEY,
                       from_xname TEXT NOT NULL,
                       to_xname TEXT NOT NULL,
                       idea_id INTEGER,
                       change_note TEXT,
                       reason TEXT,
                       outcome TEXT,
                       icir_delta REAL,
                       ts TEXT,
                       status TEXT,
                       iterable INTEGER,
                       op_id INTEGER
                   )"""
            )
            conn.execute(
                """INSERT INTO iterations
                   (id, from_xname, to_xname, change_note, reason, status, iterable)
                   VALUES (77, 'Source', 'Source', 'change target', 'why', 'open', 1)"""
            )
            conn.execute("DELETE FROM factor_lineage_edges")
            conn.execute("DELETE FROM iteration_suggestions")
            conn.execute("DELETE FROM factor_lineage_paths")
            conn.execute("DELETE FROM factor_lineage_nodes")
            db.ensure_factor_lineage_schema(conn)
            db.retire_iterations_table(conn)
            assert conn.execute(
                "SELECT type FROM sqlite_master WHERE name='iterations'"
            ).fetchone()[0] == "view"
            assert conn.execute("SELECT id FROM iterations").fetchone()[0] == 77

            assert db.claim_iteration(conn, 77)["ok"] is True
            assert db.realize_iteration(conn, 77, "Target", icir_delta=0.1)["ok"] is True
            suggestion = conn.execute(
                "SELECT status FROM iteration_suggestions WHERE suggestion_id=77"
            ).fetchone()
            assert suggestion["status"] == "realized"
            edge = conn.execute(
                """SELECT child_xname, outcome FROM factor_lineage_edges
                   WHERE suggestion_id=77"""
            ).fetchone()
            assert edge["child_xname"] == "Target"
            assert edge["outcome"] == "improved"
            suggestion_cols = {
                r[1] for r in conn.execute("PRAGMA table_info(iteration_suggestions)")
            }
            assert not (suggestion_cols & {"realized_to_xname", "outcome", "icir_delta"})

            new_id = db.open_iteration(
                conn, "Source", change_note="next change", reason="next reason"
            )
            repeat_id = db.open_iteration(
                conn, "Source", change_note="next change", reason="next reason"
            )
            assert new_id == repeat_id
            assert conn.execute(
                """SELECT COUNT(*) FROM iteration_suggestions
                   WHERE from_xname='Source' AND status='open'"""
            ).fetchone()[0] == 1
            assert conn.execute(
                """SELECT open_suggestion_count FROM factor_lineage_nodes
                   WHERE xname='Source'"""
            ).fetchone()[0] == 1
    finally:
        path.unlink(missing_ok=True)


def test_v20_folds_realized_suggestion_into_edge():
    path, conn_ctx = _new_conn()
    try:
        with conn_ctx as conn:
            _add_factor(conn, "Source", "evaluated")
            _add_factor(conn, "Target", "evaluated")
            conn.execute("DROP VIEW IF EXISTS iterations")
            for col, ddl in (
                ("realized_to_xname", "TEXT"),
                ("realized_ts", "TIMESTAMP"),
                ("realized_run_id", "TEXT"),
                ("outcome", "TEXT"),
                ("icir_delta", "REAL"),
            ):
                conn.execute(
                    f"ALTER TABLE iteration_suggestions ADD COLUMN {col} {ddl}"
                )
            conn.execute(
                """INSERT INTO iteration_suggestions
                   (suggestion_id, from_xname, status, realized_to_xname, outcome,
                    icir_delta, created_ts, updated_ts)
                   VALUES (200, 'Source', 'realized', 'Target', 'improved',
                           0.1, '2026-08-20', '2026-08-20')"""
            )
            db.normalize_suggestion_node_schema(conn)

            cols = {r[1] for r in conn.execute("PRAGMA table_info(iteration_suggestions)")}
            assert not (cols & {"realized_to_xname", "outcome", "icir_delta"})
            edge = conn.execute(
                """SELECT child_xname, outcome, icir_delta, suggestion_id
                   FROM factor_lineage_edges WHERE suggestion_id=200"""
            ).fetchone()
            assert edge["child_xname"] == "Target"
            assert edge["outcome"] == "improved"
            assert edge["icir_delta"] == 0.1
            compat = conn.execute(
                "SELECT id, to_xname, outcome FROM iterations WHERE id=200"
            ).fetchone()
            assert compat["to_xname"] == "Target"
            assert compat["outcome"] == "improved"
    finally:
        path.unlink(missing_ok=True)


def test_operator_usage_backfill_from_lineage():
    path, conn_ctx = _new_conn()
    try:
        with conn_ctx as conn:
            _add_factor(conn, "Source", "evaluated")
            _add_factor(conn, "Target", "evaluated")
            conn.execute(
                "INSERT INTO operators (op_id, name, definition) VALUES (?,?,?)",
                (1, "TestOperator", "abstract test operator"),
            )
            db.add_lineage_edge(
                conn,
                "Source",
                "Target",
                relation_type="operator_application",
                origin="operator_contract",
                op_id=1,
            )
            from core.retrieval.derived_tables import rebuild_operator_usage
            written = rebuild_operator_usage(conn)
            row = conn.execute(
                """SELECT op_role, use_count FROM factor_operator_usage
                   WHERE xname='Target' AND op_id=1"""
            ).fetchone()
            assert written >= 1
            assert row and row["op_role"] == "operator_application"
            assert row["use_count"] == 1
    finally:
        path.unlink(missing_ok=True)


def test_record_operator_family_edge_upsert():
    path, conn_ctx = _new_conn()
    try:
        with conn_ctx as conn:
            _add_factor(conn, "Tested", "evaluated")
            conn.execute(
                "INSERT INTO operators (op_id, name, definition) VALUES (?,?,?)",
                (1, "TestOperator", "abstract test operator"),
            )
            edge_id = db.record_operator_family_edge(
                conn, 1, "flow", family="imbalance", pearson=0.72,
                residual=0.11, tested_on="Tested", verdict="inside_closure",
                note="synthetic collision test",
            )
            row = conn.execute(
                "SELECT family, pearson, residual, verdict, tested_on FROM operator_family_edges WHERE id=?",
                (edge_id,),
            ).fetchone()
            assert row["family"] == "imbalance"
            assert row["verdict"] == "inside_closure"
            assert row["tested_on"] == "Tested"

            db.record_operator_family_edge(
                conn, 1, "flow", family=None, pearson=0.1,
                residual=0.9, tested_on="Tested", verdict="outside_closure",
                note="updated",
            )
            rows = conn.execute(
                "SELECT COUNT(*) FROM operator_family_edges WHERE op_id=1 AND base_type='flow'"
            ).fetchone()[0]
            row = conn.execute(
                "SELECT family, verdict, note FROM operator_family_edges WHERE op_id=1 AND base_type='flow'"
            ).fetchone()
            assert rows == 1
            assert row["family"] is None
            assert row["verdict"] == "outside_closure"
            assert row["note"] == "updated"
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    test_lineage_dag_closure_and_profiles()
    test_suggestion_lifecycle_and_legacy_id_migration()
    test_v20_folds_realized_suggestion_into_edge()
    test_operator_usage_backfill_from_lineage()
    test_record_operator_family_edge_upsert()
    print("lineage model tests passed")


if __name__ == "__main__":
    main()
