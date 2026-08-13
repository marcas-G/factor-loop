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


def graph_angle_coverage() -> list:
    """信息角度覆盖度:每角度的因子数/dead_end/饱和度(unexplored/thin/partial/saturated)。explore_uncovered_angle 的输入——看哪些角度饱和该跳过、哪些未探索该开挖。不靠人喂角度,图自己看地图换方向。"""
    with db.get_conn() as conn:
        return db.query_angle_coverage(conn)


def graph_select_operation() -> dict:
    """动态优先级打分:按图状态(角度饱和度/聚簇位置/操作历史diversity)给 5 操作打分,推荐最高分+理由。替代 graph-engine G1 固定优先级表——角度饱和时强推 explore 换角度,防深度优先扎堆。graph-engine G1 调它选操作,不再用固定优先级表。"""
    with db.get_conn() as conn:
        return db.select_graph_operation(conn)


def angle_candidate_add(code: str, field_family: str = None, extraction: str = None,
                        signal_target: str = None, theory_axiom: str = None, description: str = None,
                        novelty_argument: str = None, trigger_angle: str = None, status: str = "proposed") -> dict:
    """写 angle 自发现候选(proposed)。hypothesize angle_discovery 分支:meta-angle-discoverer 产出后调。"""
    with db.get_conn() as conn:
        return {"id": db.add_angle_candidate(
            conn, code=code, field_family=field_family, extraction=extraction,
            signal_target=signal_target, theory_axiom=theory_axiom, description=description,
            novelty_argument=novelty_argument, trigger_angle=trigger_angle,
            status=status or "proposed",
        )}


def angle_candidate_update(candidate_id: int, status: str, reject_reason: str = None, nearest_existing: str = None) -> dict:
    """更新候选状态:reviewer accept→accepted(并 addAngle);reject→rejected+reason。"""
    with db.get_conn() as conn:
        db.update_angle_candidate(conn, candidate_id, status=status,
                                  reject_reason=reject_reason, nearest_existing=nearest_existing)
    return {"ok": True}


def angle_candidate_list(status: str = None) -> list:
    """列 angle 候选(可按 status)。meta-angle-discoverer 查 rejected 防循环用。"""
    with db.get_conn() as conn:
        return [dict(r) for r in db.list_angle_candidates(conn, status=status)]


def angle_add(code: str, name: str, field_family: str, extraction: str,
              signal_target: str = None, theory_axiom: str = None, description: str = None) -> dict:
    """写 angle_ontology(新角度入库,explore 能选)。hypothesize angle_discovery accept 后调。"""
    with db.get_conn() as conn:
        db.add_angle(conn, code, name, field_family, extraction,
                     signal_target=signal_target, theory_axiom=theory_axiom, description=description)
    return {"ok": True}


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
    ("graph_angle_coverage", graph_angle_coverage),
    ("graph_select_operation", graph_select_operation),
    ("angle_candidate_add", angle_candidate_add),
    ("angle_candidate_update", angle_candidate_update),
    ("angle_candidate_list", angle_candidate_list),
    ("angle_add", angle_add),
]
