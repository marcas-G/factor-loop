"""schema 版本化迁移测试(factor_db/migrations.py + db.py)。

验证:
  1. 全新库 init_db → schema_version 标到 CURRENT
  2. migrate 幂等(跑两次,版本/表结构/ideas 列不变)
  3. 史前库(无 schema_version) → migrate → 补齐到 CURRENT + 知识图表齐全
  4. ideas 必然假设字段迁移:老 ideas 表缺列 → migrate → 6 列补齐(py 端历史漂移修复)
  5. py CURRENT_VERSION == mjs CURRENT_SCHEMA_VERSION(双端防漂移)

用法: /home/lgao/quant-venv/bin/python factor_db/test_migrations.py
      (需 quant-venv:init_db 依赖 sqlite-vec)
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db          # noqa: E402
import migrations  # noqa: E402
import init_db     # noqa: E402


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
        for t in ["axioms", "graph_edges", "observe_outputs",
                  "angle_ontology", "schema_version"]:
            assert t in names, f"migrate 后缺表 {t}"
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


def test_py_mjs_version_in_sync():
    """py CURRENT_VERSION == mjs CURRENT_SCHEMA_VERSION(双端防漂移核心断言)。"""
    mjs = (Path(__file__).resolve().parent.parent /
           "pipeline-mcp" / "lib" / "factor-db.mjs").read_text(encoding="utf-8")
    m = re.search(r"CURRENT_SCHEMA_VERSION\s*=\s*(\d+)", mjs)
    assert m, "mjs 未找到 CURRENT_SCHEMA_VERSION 常量"
    mjs_ver = int(m.group(1))
    assert mjs_ver == migrations.CURRENT_VERSION, \
        f"双端版本漂移: py={migrations.CURRENT_VERSION} mjs={mjs_ver}"
    print(f"✓ 双端版本同步 py = mjs = {migrations.CURRENT_VERSION}")


TESTS = [
    test_init_new_db_marks_current_version,
    test_migrate_idempotent,
    test_prehistoric_db_migrated_to_current,
    test_ideas_necessity_fields_migrated,
    test_py_mjs_version_in_sync,
]


def main():
    for t in TESTS:
        t()
    print(f"\n全部 {len(TESTS)} 项 schema 版本化测试通过。")


if __name__ == "__main__":
    main()
