"""schema 版本化迁移测试(core/db/migrations.py + db.py)。

验证:
  1. 全新库 init_db → schema_version 标到 CURRENT
  2. migrate 幂等(跑两次,版本/表结构/ideas 列不变)
  3. 史前库(无 schema_version) → migrate → 补齐到 CURRENT + 知识图表齐全
  4. ideas 必然假设字段迁移:老 ideas 表缺列 → migrate → 6 列补齐(py 端历史漂移修复)
  5. py CURRENT_VERSION == mjs CURRENT_SCHEMA_VERSION(双端防漂移)

用法: /home/lgao/quant-venv/bin/python core/tools/test_migrations.py
      (需 quant-venv:init_db 依赖 sqlite-vec)
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # 项目根
from core.db import db          # noqa: E402
from core.db import migrations  # noqa: E402
from core.db import init_db     # noqa: E402


def _table_names(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def _col_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_init_new_db_marks_current_version():
    """全新库 init_db(schema.sql 直建) → migrate 标到 CURRENT。"""
    tmp = tempfile.mktemp(suffix=".db")
    init_db.init_db(Path(tmp))
    with db.get_conn(tmp) as conn:
        assert db.current_schema_version(conn) == migrations.CURRENT_VERSION
    Path(tmp).unlink()
    print(f"✓ 全新库 init → schema_version={migrations.CURRENT_VERSION}")


def test_migrate_idempotent():
    """migrate 跑两次:版本不变,表结构(名 + ideas 列)不变。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        migrations.migrate(conn)
        v1 = db.current_schema_version(conn)
        names1, cols1 = _table_names(conn), _col_names(conn, "ideas")
        migrations.migrate(conn)  # 再跑
        v2 = db.current_schema_version(conn)
        names2, cols2 = _table_names(conn), _col_names(conn, "ideas")
        assert v1 == v2 == migrations.CURRENT_VERSION, f"版本漂移 {v1}->{v2}"
        assert names1 == names2, "表名集合变化(不幂等)"
        assert cols1 == cols2, "ideas 列变化(不幂等)"
    Path(tmp).unlink()
    print(f"✓ migrate 幂等(版本稳定在 {migrations.CURRENT_VERSION}, 结构不变)")


def test_prehistoric_db_migrated_to_current():
    """史前库(无 schema_version,version 0) → migrate → 补齐到 CURRENT + 知识图表齐全。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        assert db.current_schema_version(conn) == 0, "史前库应为 version 0"
        migrations.migrate(conn)
        assert db.current_schema_version(conn) == migrations.CURRENT_VERSION
        names = set(_table_names(conn))
        for t in ["axioms", "graph_edges",
                  "iteration_suggestions", "factor_lineage_edges",
                  "factor_lineage_paths", "factor_lineage_nodes", "schema_version"]:
            assert t in names, f"migrate 后缺表 {t}"
        assert "angle_ontology" not in names, "angle_ontology 未退役"
    Path(tmp).unlink()
    print("✓ 史前库 migrate → 补齐到 CURRENT + 知识图表齐全")


def test_ideas_necessity_fields_migrated():
    """老 ideas 表(裸,无必然假设列) → migrate → 6 列补齐。
    这是 py 端此前缺失、阶段2 补的迁移(对齐 mjs migrateIdeasSchema)。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        migrations.migrate(conn)
        cols = _col_names(conn, "ideas")
        for c in ["node_layer", "argument_chain", "support_score",
                  "evaluated_factor_count", "support_score_computed_at",
                  "necessity_grade"]:
            assert c in cols, f"ideas 缺列 {c}(ensure_ideas_necessity_fields 未补)"
    Path(tmp).unlink()
    print("✓ ideas 必然假设 6 列迁移补齐(py 端历史漂移修复)")


def test_current_version_valid():
    """node 端已删除(全量迁 python),CURRENT_VERSION 只需是正整数且迁移链完整。"""
    assert migrations.CURRENT_VERSION >= 15, "CURRENT_VERSION 应 ≥ 15(检索层)"
    assert len(migrations.MIGRATIONS) == migrations.CURRENT_VERSION, \
        f"迁移链 {len(migrations.MIGRATIONS)} 项 ≠ CURRENT_VERSION {migrations.CURRENT_VERSION}"
    print(f"✓ CURRENT_VERSION={migrations.CURRENT_VERSION},迁移链 {len(migrations.MIGRATIONS)} 项完整")


def test_verdict_field_migrated_and_backfilled():
    """v17 factors.verdict:老库按 status 回填(pass/fail),未评估保持 NULL,幂等。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT)")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("INSERT INTO factors VALUES ('PassedFactor', 'evaluated')")
        conn.execute("INSERT INTO factors VALUES ('DeadEndFactor', 'dead_end')")
        conn.execute("INSERT INTO factors VALUES ('DraftFactor', 'draft')")
        migrations.migrate(conn)
        rows = {
            r["xname"]: r["verdict"]
            for r in conn.execute("SELECT xname, verdict FROM factors")
        }
        assert rows == {
            "PassedFactor": "pass",
            "DeadEndFactor": "fail",
            "DraftFactor": None,
        }
        migrations.migrate(conn)
        rows2 = {
            r["xname"]: r["verdict"]
            for r in conn.execute("SELECT xname, verdict FROM factors")
        }
        assert rows2 == rows, "verdict 回填不幂等"
    Path(tmp).unlink()
    print("✓ verdict 字段迁移 + 老库回填(pass/fail)通过")


def test_angle_legacy_fields_dropped():
    """v21-v26: 老 angle 表/列应被删除,angle 层整层退役。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("""CREATE TABLE factors(
            xname TEXT PRIMARY KEY, class_name TEXT, status TEXT, latest_icir REAL,
            angle_code TEXT, last_updated_ts TIMESTAMP, deprecated_at TIMESTAMP
        )""")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("""CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, factor_xname TEXT,
            deprecated_at TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE angle_ontology (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, field_family TEXT NOT NULL,
            extraction TEXT NOT NULL, signal_target TEXT, theory_axiom TEXT, description TEXT
        )""")
        conn.execute("""CREATE TABLE angle_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            field_family TEXT, extraction TEXT, signal_target TEXT, theory_axiom TEXT,
            description TEXT, novelty_argument TEXT, trigger_angle TEXT,
            status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected')),
            reject_reason TEXT, nearest_existing TEXT,
            tried_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        migrations.migrate(conn)
        assert db.current_schema_version(conn) == migrations.CURRENT_VERSION
        names = set(_table_names(conn))
        assert "angle_candidates" not in names, "angle_candidates 表未退役"
        assert "angle_ontology" not in names, "angle_ontology 表未退役"
        for table in ("factors", "ideas"):
            assert "angle_code" not in _col_names(conn, table), f"{table} 仍含 angle_code"
        migrations.migrate(conn)  # 幂等
        names = set(_table_names(conn))
        assert "angle_candidates" not in names
        assert "angle_ontology" not in names
        for table in ("factors", "ideas"):
            assert "angle_code" not in _col_names(conn, table)
    Path(tmp).unlink()
    print("✓ v21-v26 angle 层整层退役通过")


def test_iteration_suggestion_audit_fields_dropped():
    """v27-v28: suggestion/edge/node 低价值字段应被删除。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("""CREATE TABLE factors(
            xname TEXT PRIMARY KEY, class_name TEXT, status TEXT, latest_icir REAL,
            last_updated_ts TIMESTAMP, deprecated_at TIMESTAMP
        )""")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("""CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, factor_xname TEXT,
            deprecated_at TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE iteration_suggestions (
            suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_xname TEXT NOT NULL, idea_id INTEGER, op_id INTEGER,
            change_note TEXT, reason TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            iterable INTEGER NOT NULL DEFAULT 1,
            opened_run_id TEXT, claimed_run_id TEXT, claimed_ts TIMESTAMP,
            legacy_iteration_id INTEGER UNIQUE,
            created_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        migrations.migrate(conn)
        assert db.current_schema_version(conn) == migrations.CURRENT_VERSION
        cols = _col_names(conn, "iteration_suggestions")
        for col in ("opened_run_id", "claimed_run_id", "claimed_ts", "legacy_iteration_id", "iterable"):
            assert col not in cols, f"iteration_suggestions 仍含 {col}"
        assert "run_id" not in _col_names(conn, "factor_lineage_edges")
        assert "realized_child_count" not in _col_names(conn, "factor_lineage_nodes")
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        )}
        assert "iterations" in views, "iterations 兼容视图缺失"
        assert "factor_lineage_branches" in views, "factor_lineage_branches 视图缺失"
        migrations.migrate(conn)  # 幂等
        cols = _col_names(conn, "iteration_suggestions")
        for col in ("opened_run_id", "claimed_run_id", "claimed_ts", "legacy_iteration_id", "iterable"):
            assert col not in cols
        assert "run_id" not in _col_names(conn, "factor_lineage_edges")
        assert "realized_child_count" not in _col_names(conn, "factor_lineage_nodes")
    Path(tmp).unlink()
    print("✓ v27-v28 lineage 低价值字段退役通过")


def test_operator_family_edge_unique_constraint():
    """v29: 旧 operator_family_edges(无 UNIQUE)迁移后应重建为唯一约束,数据保留最新。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        conn.execute("""CREATE TABLE factors(
            xname TEXT PRIMARY KEY, class_name TEXT, status TEXT, latest_icir REAL,
            last_updated_ts TIMESTAMP, deprecated_at TIMESTAMP
        )""")
        conn.execute("CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("""CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, factor_xname TEXT,
            deprecated_at TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE operators (
            op_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, definition TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE operator_family_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            base_type TEXT NOT NULL,
            family TEXT,
            pearson REAL,
            residual REAL,
            tested_on TEXT,
            verdict TEXT CHECK(verdict IN ('outside_closure','inside_closure','untested')),
            note TEXT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("INSERT INTO operators(op_id, name, definition) VALUES (1,'op','def')")
        conn.execute(
            """INSERT INTO operator_family_edges(op_id, base_type, family, verdict)
               VALUES (1,'flow','imbalance','inside_closure')"""
        )
        conn.execute(
            """INSERT INTO operator_family_edges(op_id, base_type, family, verdict)
               VALUES (1,'flow','cancel','inside_closure')"""
        )
        migrations.migrate(conn)
        assert db.current_schema_version(conn) == migrations.CURRENT_VERSION
        rows = conn.execute(
            "SELECT family FROM operator_family_edges WHERE op_id=1 AND base_type='flow'"
        ).fetchall()
        assert len(rows) == 1, "重建后同一 op_id×base_type 应只剩一行"
        assert rows[0][0] == "cancel", "应保留最新一次记录"
        indexes = conn.execute("PRAGMA index_list(operator_family_edges)").fetchall()
        assert any(str(idx[1]).startswith("sqlite_autoindex_") for idx in indexes), \
            "operator_family_edges 应带 UNIQUE(op_id, base_type)"
        migrations.migrate(conn)  # 幂等
        rows = conn.execute(
            "SELECT COUNT(*) FROM operator_family_edges WHERE op_id=1 AND base_type='flow'"
        ).fetchone()
        assert rows[0] == 1
    Path(tmp).unlink()
    print("✓ v29 operator_family_edges 唯一约束迁移通过")


TESTS = [
    test_init_new_db_marks_current_version,
    test_migrate_idempotent,
    test_prehistoric_db_migrated_to_current,
    test_ideas_necessity_fields_migrated,
    test_current_version_valid,
    test_verdict_field_migrated_and_backfilled,
    test_angle_legacy_fields_dropped,
    test_iteration_suggestion_audit_fields_dropped,
    test_operator_family_edge_unique_constraint,
]


def main():
    for t in TESTS:
        t()
    print(f"\n全部 {len(TESTS)} 项 schema 版本化测试通过。")


if __name__ == "__main__":
    main()
