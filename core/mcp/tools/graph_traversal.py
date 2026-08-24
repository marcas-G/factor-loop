"""知识图遍历/读写工具(吸收 runtime/mcp/tools/graph-traversal.mjs)。转发 core.db graph 函数。"""
from core.db import db

EDGE_TYPES = ["CONTRADICTS", "DERIVES_FROM", "INSTANTIATES", "SPECIALIZES",
              "ORTHOGONAL_TO", "SUPPORTS", "REFUTES", "BOUNDS"]
NODE_TABLES = ["axioms", "ideas", "factors", "lessons"]


def graph_query_contradictions(resolved: bool = False, axiom_code: str = None, limit: int = 5) -> list:
    """查 CONTRADICTS 边(推理燃料)。resolved=false(默认)返回未解矛盾。resolve_contradiction 操作的输入。"""
    with db.get_conn() as conn:
        return db.query_contradictions(
            conn, resolved=resolved if resolved is not None else False,
            axiom_code=axiom_code, limit=limit if limit is not None else 5,
        )


def graph_get_subgraph(table: str, node_id: str, depth: int = 2, edge_types: list = None, limit: int = 200) -> dict:
    """取以某节点为中心、depth 跳内的子图(节点+边,BFS)。fill_chain_gap / orthogonal_branch 的输入。返回跨表 join 的节点全字段。"""
    with db.get_conn() as conn:
        return db.get_subgraph(conn, table, node_id, depth=depth if depth is not None else 2,
                               edge_types=edge_types, limit=limit if limit is not None else 200)


def graph_neighborhood(table: str, node_id: str, edge_types: list = None, direction: str = "both", limit: int = 10) -> list:
    """取某节点 1 跳邻居(比 graph_get_subgraph 轻)。orthogonal_branch 先用它看因子实现群。direction: out/in/both。"""
    with db.get_conn() as conn:
        return db.neighborhood(conn, table, node_id, edge_types=edge_types,
                               direction=direction or "both", limit=limit if limit is not None else 10)


def graph_find_refutation_clusters(target_table: str = None, target_id: str = None, min_size: int = 3, limit: int = 5) -> list:
    """找 REFUTES/SUPPORTS 边指向同一目标的聚簇(3+ 反例指向同一 axiom/idea)。generalize_from_refutation 操作的输入。"""
    with db.get_conn() as conn:
        return db.find_refutation_clusters(conn, target_table=target_table, target_id=target_id,
                                           min_size=min_size if min_size is not None else 3,
                                           limit=limit if limit is not None else 5)


def graph_stats() -> dict:
    """图统计:各层节点数、各边类型数、未解矛盾数。graph-engine 选操作优先级 / 自转循环停止条件用。"""
    with db.get_conn() as conn:
        return db.graph_stats(conn)


def graph_add_node(table: str, data: dict) -> dict:
    """写新节点到图。table='axioms'→公理;table='ideas'→带 argument_chain/necessity_grade/node_layer 的假设。返回新 id。"""
    if not data or (table == "axioms" and not data.get("code")) or (table == "ideas" and not data.get("text")):
        return {"ok": False, "error": "data 必填(axioms.code / ideas.text)"}
    with db.get_conn() as conn:
        return {"id": db.add_graph_node(conn, table, data)}


def graph_add_edges(edges: list) -> dict:
    """批量写图边(幂等)。graph-reasoner 产出新边后调用。每条 {from_table,from_id,to_table,to_id,edge_type,weight?,properties?}。"""
    if not isinstance(edges, list) or not edges:
        return {"ok": False, "error": "edges 不能为空"}
    ids = []
    with db.get_conn() as conn:
        for e in edges:
            ids.append(db.add_graph_edge(
                conn, e["from_table"], e["from_id"], e["to_table"], e["to_id"], e["edge_type"],
                weight=e.get("weight"), properties=e.get("properties"),
            ))
    return {"edge_ids": ids}


def graph_mark_contradiction_resolved(edge_id: int, idea_id: int) -> dict:
    """标记某 CONTRADICTS 边已由某 idea 解决(properties 加 resolved_by)。resolve_contradiction 产 idea 过 reviewer 后调用。"""
    with db.get_conn() as conn:
        db.mark_contradiction_resolved(conn, edge_id, idea_id)
    return {"ok": True}


def graph_mark_contradiction_bounded(edge_id: int, regime: str, reason: str) -> dict:
    """标记 CONTRADICTS 边为「axiom 边界限定」(否定性结论:axiom 在此 regime 不完备,产不出必然正命题)。与 graph_mark_contradiction_resolved 对称:resolved=肯定解决(产 idea),bounded=否定解决(axiom 证伪)。bounded 后该矛盾不再算 unresolved。graph-reasoner 判定矛盾为或然(axiom 证伪而非数据不足)时调用。"""
    with db.get_conn() as conn:
        db.mark_contradiction_bounded(conn, edge_id, regime, reason)
    return {"ok": True}


def graph_select_operation() -> dict:
    """动态优先级打分:按图状态(聚簇位置/操作历史diversity)给操作打分,推荐最高分+理由。graph-engine G1 调它选操作。"""
    with db.get_conn() as conn:
        return db.select_graph_operation(conn)


TOOLS = [
    ("graph_query_contradictions", graph_query_contradictions),
    ("graph_get_subgraph", graph_get_subgraph),
    ("graph_neighborhood", graph_neighborhood),
    ("graph_find_refutation_clusters", graph_find_refutation_clusters),
    ("graph_stats", graph_stats),
    ("graph_add_node", graph_add_node),
    ("graph_add_edges", graph_add_edges),
    ("graph_mark_contradiction_resolved", graph_mark_contradiction_resolved),
    ("graph_mark_contradiction_bounded", graph_mark_contradiction_bounded),
    ("graph_select_operation", graph_select_operation),
]
