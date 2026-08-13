"""图函数回归测试:幂等 / 状态机 / 查询 / 迁移 / 节点写入。

防改图函数引入回归(如判据集中、加 BOUNDS 那种改动),顺带抓双端漂移。
node 端(factor-db.mjs)共读 graph_constants.json + node --check,运行时由 MCP 间接验。

用法: python3 core/tools/test_graph.py
"""
from __future__ import annotations
import sys, os, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.db import db

_BASE_DDLS = [
    "CREATE TABLE ideas(id INTEGER PRIMARY KEY, text TEXT, parent_idea_id INTEGER, status TEXT, argument_chain TEXT, necessity_grade TEXT)",
    "CREATE TABLE factors(xname TEXT PRIMARY KEY, status TEXT, latest_icir REAL, deprecated_at TIMESTAMP)",
    "CREATE TABLE lessons(id INTEGER PRIMARY KEY, type TEXT, factor_xname TEXT, idea_id INTEGER, deprecated_at TIMESTAMP)",
]


_CMS = []  # 保持 contextmanager 引用,防 GC 触发 __exit__ 关库


def _setup():
    """临时库 + 基础表 + ensure_graph_schema/angle。"""
    tmp = tempfile.mktemp(suffix=".db")
    cm = db.get_conn(tmp)
    conn = cm.__enter__()
    _CMS.append(cm)  # 防 GC 关库
    for ddl in _BASE_DDLS:
        conn.execute(ddl)
    db.ensure_graph_schema(conn)
    db.ensure_angle_schema(conn)
    return tmp, conn


def _teardown(tmp, conn):
    cm = _CMS.pop()
    cm.__exit__(None, None, None)  # commit + close
    os.unlink(tmp)


def test_add_graph_edge_idempotent():
    tmp, c = _setup()
    aid = db.add_axiom(c, "ax", "micro", "s")
    e1 = db.add_graph_edge(c, "axioms", aid, "axioms", aid, "DERIVES_FROM")
    e2 = db.add_graph_edge(c, "axioms", aid, "axioms", aid, "DERIVES_FROM")  # 同四元组+类型
    assert e1 == e2, f"幂等应返回同 id: {e1} vs {e2}"
    e3 = db.add_graph_edge(c, "axioms", aid, "axioms", aid, "SUPPORTS")  # 不同类型不重复
    assert e3 != e1, "不同 edge_type 不该判重复"
    # factors 用 xname(字符串)作 id
    c.execute("INSERT INTO factors(xname,status) VALUES('FX','evaluated')")
    e4 = db.add_graph_edge(c, "factors", "FX", "axioms", aid, "INSTANTIATES")
    assert e4 > 0
    _teardown(tmp, c)
    print("✓ add_graph_edge 幂等(同四元组+类型→同id; factors 用 xname)")


def test_query_contradictions_resolved_states():
    """resolved_by 和 resolution=bounded 都算消解(三态判据)。"""
    tmp, c = _setup()
    aid = db.add_axiom(c, "ax", "micro", "s")
    iid = db.add_idea(c, "test idea")
    eid = db.add_graph_edge(c, "ideas", iid, "axioms", aid, "CONTRADICTS")
    assert len(db.query_contradictions(c)) == 1 and len(db.query_contradictions(c, resolved=True)) == 0
    db.mark_contradiction_resolved(c, eid, 99)  # resolved_by
    assert len(db.query_contradictions(c)) == 0 and len(db.query_contradictions(c, resolved=True)) == 1
    iid2 = db.add_idea(c, "test idea2")
    eid2 = db.add_graph_edge(c, "ideas", iid2, "axioms", aid, "CONTRADICTS")
    db.mark_contradiction_bounded(c, eid2, "regime", "或然")  # resolution=bounded
    assert len(db.query_contradictions(c)) == 0, "bounded 也应算消解(不算未解)"
    _teardown(tmp, c)
    print("✓ query_contradictions 三态:未解 / resolved_by / resolution=bounded 都判对")


def test_get_subgraph_bfs():
    tmp, c = _setup()
    a1 = db.add_axiom(c, "a1", "m", "s")
    a2 = db.add_axiom(c, "a2", "m", "s")
    a3 = db.add_axiom(c, "a3", "m", "s")
    db.add_graph_edge(c, "axioms", a1, "axioms", a2, "DERIVES_FROM")
    db.add_graph_edge(c, "axioms", a2, "axioms", a3, "DERIVES_FROM")
    sg = db.get_subgraph(c, "axioms", a1, depth=2, edge_types=["DERIVES_FROM"])
    ids = {n["id"] for n in sg["nodes"]}
    assert {str(a1), str(a2), str(a3)} <= ids, f"BFS depth2 应取到 a3, got {ids}"
    assert len(sg["edges"]) >= 2
    _teardown(tmp, c)
    print("✓ get_subgraph BFS depth2 取到 2跳邻居")


def test_neighborhood_direction():
    tmp, c = _setup()
    a1 = db.add_axiom(c, "a1", "m", "s")
    a2 = db.add_axiom(c, "a2", "m", "s")
    db.add_graph_edge(c, "axioms", a1, "axioms", a2, "DERIVES_FROM")
    out = db.neighborhood(c, "axioms", a1, direction="out")
    inn = db.neighborhood(c, "axioms", a2, direction="in")
    assert len(out) == 1 and out[0]["neighbor_id"] == str(a2) and out[0]["direction"] == "out"
    assert len(inn) == 1 and inn[0]["neighbor_id"] == str(a1) and inn[0]["direction"] == "in"
    _teardown(tmp, c)
    print("✓ neighborhood out/in 方向正确")


def test_add_graph_node_layers():
    tmp, c = _setup()
    aid = db.add_graph_node(c, "axioms", {"code": "na", "category": "m", "statement": "s"})
    assert aid > 0
    iid = db.add_graph_node(c, "ideas",
                            {"text": "hypo", "necessity_grade": "conditional", "node_layer": "HYPOTHESIS"})
    row = c.execute("SELECT node_layer, necessity_grade FROM ideas WHERE id=?", (iid,)).fetchone()
    assert row["node_layer"] == "HYPOTHESIS" and row["necessity_grade"] == "conditional"
    # argument_chain 透传
    iid2 = db.add_graph_node(c, "ideas", {"text": "d", "argument_chain": {"x": 1}, "node_layer": "DERIVED"})
    ch = c.execute("SELECT argument_chain FROM ideas WHERE id=?", (iid2,)).fetchone()
    assert '"x"' in (ch["argument_chain"] or "")
    _teardown(tmp, c)
    print("✓ add_graph_node: axioms/ideas + node_layer/necessity_grade/argument_chain 透传")


def test_migrate_graph_edge_bounds_allows_bounds():
    """ensure_graph_schema 跑过 migrate_graph_edge_bounds → BOUNDS 在 CHECK 里 → 可插。"""
    tmp, c = _setup()
    a1 = db.add_axiom(c, "a1", "m", "s")
    a2 = db.add_axiom(c, "a2", "m", "s")
    eid = db.add_graph_edge(c, "axioms", a1, "axioms", a2, "BOUNDS")  # 若 CHECK 不含 BOUNDS 会抛错
    assert eid > 0
    _teardown(tmp, c)
    print("✓ migrate_graph_edge_bounds: BOUNDS 边可插(CHECK 已含)")


if __name__ == "__main__":
    for t in [
        test_add_graph_edge_idempotent,
        test_query_contradictions_resolved_states,
        test_get_subgraph_bfs,
        test_neighborhood_direction,
        test_add_graph_node_layers,
        test_migrate_graph_edge_bounds_allows_bounds,
    ]:
        t()
    print("\n=== 图函数回归测试全部通过 ===")
