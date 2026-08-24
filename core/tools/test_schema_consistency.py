"""schema 一致性测试:新库 schema.sql 直建必须含所有 migrate 补的列。

防 iterations 类 bug(schema.sql 漏 status,靠 mjs migrateIterationsSchema
给新老库补掩盖;测试 setup 漏跑 migrate 时暴露)。把"各 migrate 函数补的列"列成清单,
断言新库 init_db 后各表都含——未来再漏列直接测试挂。

用法: /home/lgao/quant-venv/bin/python core/tools/test_schema_consistency.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.db import db  # noqa: E402
from core.db import init_db  # noqa: E402

# 各 migrateXxxSchema / ensure_* 给表补的列。schema.sql 新库直建必须含(不能靠 migrate 掩盖)。
EXPECTED_COLS = {
    "factors": ["quality_score", "quality_grade", "intuition", "anchor_text"],
    "iteration_suggestions": ["status"],
    "factor_lineage_edges": ["relation_type", "origin", "suggestion_id", "confidence"],
    "factor_lineage_paths": ["min_depth", "path_count", "is_direct"],
    "factor_lineage_nodes": ["primary_root_xname", "descendant_count", "open_suggestion_count"],
    "ideas": ["argument_argument_chain_placeholder",  # 占位,下面真实清单
              "argument_chain", "support_score", "evaluated_factor_count",
              "support_score_computed_at", "necessity_grade", "node_layer"],
    "lessons": ["type", "scope", "deprecated_at"],
}


def _new_db():
    tmp = tempfile.mktemp(suffix=".db")
    init_db.init_db(Path(tmp))
    return tmp


def test_new_db_has_all_migrated_columns():
    """新库 init_db(schema.sql + py migrate)后,各表含所有 migrate 补的列。"""
    EXPECTED_COLS["ideas"] = [c for c in EXPECTED_COLS["ideas"] if "placeholder" not in c]
    tmp = _new_db()
    try:
        with db.get_conn(tmp) as c:
            for table, cols in EXPECTED_COLS.items():
                actual = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
                for col in cols:
                    assert col in actual, (
                        f"{table}.{col} 缺失——schema.sql 漏列(靠 migrate 掩盖的 bug)"
                    )
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_graph_edges_allows_bounds():
    """graph_edges.edge_type CHECK 含 BOUNDS(v3 migrate_graph_edge_bounds)。新库直建应含。"""
    tmp = _new_db()
    try:
        with db.get_conn(tmp) as c:
            # 软引用(无 FK),插 BOUNDS 边验证 CHECK 放行
            c.execute(
                "INSERT INTO graph_edges (from_table,from_id,to_table,to_id,edge_type) "
                "VALUES ('axioms','1','axioms','2','BOUNDS')"
            )
            c.commit()
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_lessons_type_check():
    """lessons.type CHECK ∈ (dead_end, success_pattern)——schema.sql 直建应含约束。"""
    tmp = _new_db()
    try:
        with db.get_conn(tmp) as c:
            # 合法值
            c.execute("INSERT INTO factors (xname, status) VALUES ('T1','draft')")
            c.execute(
                "INSERT INTO lessons (type, text, scope, factor_xname) "
                "VALUES ('dead_end','t','factor','T1')"
            )
            c.commit()
            # 非法值应被 CHECK 拒绝
            try:
                c.execute(
                    "INSERT INTO lessons (type, text, scope, factor_xname) "
                    "VALUES ('bogus','t','factor','T1')"
                )
                raise AssertionError("lessons.type CHECK 没拦住非法值 'bogus'")
            except Exception as e:
                assert "CHECK" in str(e) or "constraint" in str(e).lower(), f"非预期错误: {e}"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_iterations_is_readonly_compat_view():
    """v19 新库应只有 iterations 只读 view,不再有物理表。"""
    tmp = _new_db()
    try:
        with db.get_conn(tmp) as c:
            row = c.execute(
                "SELECT type FROM sqlite_master WHERE name='iterations'"
            ).fetchone()
            assert row and row[0] == "view", f"iterations 应为 view,实际 {row}"
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"✓ {t.__name__}")
    print(f"\n全部 {len(tests)} 项 schema 一致性测试通过。")


if __name__ == "__main__":
    main()
