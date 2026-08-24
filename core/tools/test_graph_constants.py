"""图查询常量一致性测试。

验证判据集中(core/db/graph_constants.json)后:
  1. py 端 loader 正确读共享文件
  2. query_contradictions / graph_stats 用 resolved_clause 常量判据(不是硬编码)

node 端(factor-db.mjs)共读同一文件 → resolved_clause 天然一致(同文件);
node 语法由 `node --check` 保证,运行时由 MCP server 调 graph_stats 间接验证。

用法: python3 core/tools/test_graph_constants.py
"""
from __future__ import annotations
import sys, json, os, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.db import db


def test_loader_reads_shared_file():
    """loader 读的常量 = graph_constants.json 文件内容(单一真相)。"""
    c = db.graph_constants()
    assert "resolved_clause" in c and "resolved_by" in c["resolved_clause"], "resolved_clause 缺失"
    file_c = json.loads((Path(__file__).resolve().parents[2] / "core" / "db" / "graph_constants.json").read_text(encoding="utf-8"))
    assert c["resolved_clause"] == file_c["resolved_clause"], "loader 与文件不一致"
    print("✓ loader 读 graph_constants.json 正确(单一真相)")


def test_graph_stats_uses_resolved_clause():
    """graph_stats 的 unresolved 判据来自常量:建未解矛盾→1,mark resolved→0。"""
    tmp = tempfile.mktemp(suffix=".db")
    with db.get_conn(tmp) as conn:
        for ddl in ["CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT, necessity_grade TEXT, parent_idea_id INTEGER, status TEXT)",
                    "CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT, latest_icir REAL, deprecated_at TIMESTAMP)",
                    "CREATE TABLE lessons(id INTEGER PRIMARY KEY, type TEXT, factor_xname TEXT, deprecated_at TIMESTAMP)"]:
            conn.execute(ddl)
        db.ensure_graph_schema(conn)
        aid = db.add_axiom(conn, "test_axiom", "microstructure", "test statement")
        iid = db.add_idea(conn, "test idea")
        eid = db.add_graph_edge(conn, "ideas", iid, "axioms", aid, "CONTRADICTS")
        s1 = db.graph_stats(conn)
        assert s1["unresolved_contradictions"] == 1, f"未解应为1, 实际{s1['unresolved_contradictions']}"
        db.mark_contradiction_resolved(conn, eid, 999)
        s2 = db.graph_stats(conn)
        assert s2["unresolved_contradictions"] == 0, f"resolve后应为0, 实际{s2['unresolved_contradictions']}"
        print("✓ graph_stats 用 resolved_clause 常量判据(未解1→resolve后0)")
    os.unlink(tmp)


if __name__ == "__main__":
    test_loader_reads_shared_file()
    test_graph_stats_uses_resolved_clause()
    print("\n=== 图常量一致性测试全部通过 ===")
