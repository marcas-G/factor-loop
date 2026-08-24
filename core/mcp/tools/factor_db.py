"""factor-db 工具(吸收 runtime/mcp/tools/factor-db.mjs)。转发 core.db + subprocess。"""
from __future__ import annotations

import json
from pathlib import Path

from core.db import db
from core.infra.run_py import run_py

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
IC_CORRELATE = str(_PROJECT_ROOT / "core" / "tools" / "ic_correlate.py")
REFRESH_IC = str(_PROJECT_ROOT / "core" / "tools" / "refresh_factor_ic_vectors.py")
EMBED_QUERY = str(_PROJECT_ROOT / "core" / "tools" / "embed_query.py")
RESIDUAL_IC = str(_PROJECT_ROOT / "core" / "tools" / "residual_ic_strength.py")


def _rows(lst):
    return [dict(r) for r in lst]


def _norm_k(k, d=10) -> int:
    return max(1, int(k if k is not None else d))


def _spawn_json(script, args, timeout=30):
    r = run_py(script, args, timeout_sec=timeout)
    if r["exit_code"] != 0:
        raise RuntimeError(f"{Path(script).name} exit={r['exit_code']}: {r['stderr'][:200]}")
    last = (r["stdout"] or "").strip().split("\n")[-1]
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        raise RuntimeError(f"{Path(script).name} 输出非 JSON: {last[:200]}")


def factor_search(query: str, k: int = 5) -> list:
    """全文检索 lessons(trigram 分词,中文/英文混合 OK)。返回 type/scope/text 等字段。用于找历史经验。"""
    q = (query or "").strip()
    with db.get_conn() as conn:
        if len(q) < 3:
            return _rows(db.recent_lessons(conn, _norm_k(k, 5)))
        match = db._trigram_match_query(q)
        if not match:
            return _rows(db.recent_lessons(conn, _norm_k(k, 5)))
        return _rows(db.search_lessons(conn, match, limit=_norm_k(k, 5)))


def factor_recent_lessons(k: int = 10) -> list:
    """最近 k 条 lesson(按时间倒序),看最近经验积累。"""
    with db.get_conn() as conn:
        return _rows(db.recent_lessons(conn, _norm_k(k, 10)))


def factor_list(k: int = 20) -> list:
    """列最近 k 个因子(含 status / latest_icir / formula_text),看最近研究方向。"""
    with db.get_conn() as conn:
        return _rows(db.recent_factors(conn, _norm_k(k, 20)))


def factor_detail(xname: str) -> dict:
    """单因子全貌:基本信息 + 评估历史 + 迭代链 + tags。看一个因子的完整演进。"""
    with db.get_conn() as conn:
        return db.get_factor_detail(conn, xname.strip())


def factor_similar(xname: str, k: int = 10) -> list:
    """向量查重:给定 xname,找库内最相似的 k 个因子(基于 formula 语义 embedding)。"""
    with db.get_conn() as conn:
        return _rows(db.get_similar_factors(conn, xname.strip(), _norm_k(k, 10)))


def factor_semantic_search(query_text: str, k: int = 10) -> list:
    """语义检索:给定任意文本(idea / 公式 / 自然语言),用 bge-small-zh-v1.5 算 embedding,向量检索库内最相似的 k 个因子。brainstorm 阶段查相似/查重方向用这个,不要再用 factor_search 抽关键词。"""
    parsed = _spawn_json(EMBED_QUERY, ["--text", (query_text or "").strip()], timeout=60)
    emb = parsed.get("embedding") if isinstance(parsed, dict) else None
    if not emb:
        raise RuntimeError("embed_query.py 返回空 embedding")
    with db.get_conn() as conn:
        return _rows(db.search_similar(conn, emb, _norm_k(k, 10)))


def factor_counts() -> dict:
    """库规模摸底:返回 {factors, lessons, evaluated} 三个总数。"""
    with db.get_conn() as conn:
        return {"factors": db.count_factors(conn), "lessons": db.count_lessons(conn), "evaluated": db.count_evaluated(conn)}


def factor_ic_correlate(target: str, symbol: str = None, freq: str = None, y_horizon: int = None,
                        k: int = 20, min_abs_pearson: float = 0.5) -> dict:
    """IC 行为冗余检索:找和 target 因子 IC 序列相似的库内因子(预测能力同涨同跌=真冗余,比 formula 文本语义更贴近业务)。需 target 已有 IC 向量(先 factor_ic_refresh)。只给 target 时遍历其所有 (symbol,freq,y_horizon) 场景并按 |pearson| 聚合。"""
    args = ["--target", str(target), "--k", str(_norm_k(k, 20)),
            "--min-abs-pearson", str(min_abs_pearson if min_abs_pearson is not None else 0.5),
            "--top", "15"]
    if symbol:
        args += ["--symbol", str(symbol)]
    if freq:
        args += ["--freq", str(freq)]
    if y_horizon is not None:
        args += ["--y-horizon", str(y_horizon)]
    return _spawn_json(IC_CORRELATE, args, timeout=30)


def factor_ic_refresh(xname: str, force: bool = False) -> dict:
    """刷新单因子 IC 向量(下载 dailyX + 算 IC 序列向量写入 factor_ic_vec)。evaluate 在 check_done 后调用,使新因子可被 factor_ic_correlate 检索。失败返回 ok:false,调用方应降级跳过冗余检查、不阻塞主 verdict。"""
    args = ["--xname", str(xname)]
    if force:
        args.append("--force")
    r = run_py(REFRESH_IC, args, timeout_sec=900)
    return {"ok": r["exit_code"] == 0, "exitCode": r["exit_code"],
            "stdout_tail": r["stdout"][-400:], "stderr_head": r["stderr"][:200]}


def iteration_open(from_xname: str, change_note: str, reason: str = None, idea_id: int = None) -> dict:
    """evaluate 阶段开一个迭代建议(open suggestion):把当前因子的 suggested_iteration(换 horizon/品种/窗口)登记成待接续建议。pass 精进 / dead_end 显式重试用这个;dead_end 无救方向不用这个(改走 dead_end lesson 避雷)。同 (from,change) 已 open 则幂等返回已有 id。"""
    with db.get_conn() as conn:
        return {"suggestion_id": db.open_iteration(
            conn, from_xname, idea_id=idea_id, change_note=change_note, reason=reason,
        )}


def iteration_realize(suggestion_id: int, to_xname: str, icir_delta: float = None) -> dict:
    """接续因子 B 的 evaluate 阶段归档(在 persist_factor 之后调用,B 已入库):建议 in_progress→realized,血缘边写入 factor_lineage_edges(to_xname=B、icir_delta、outcome)。outcome 由 icir_delta 自动推导;建议表只保留状态,不再重复存边事实。"""
    with db.get_conn() as conn:
        return db.realize_iteration(conn, suggestion_id, to_xname, icir_delta=icir_delta)


def iteration_reopen(suggestion_id: int) -> dict:
    """失败回滚(research-loop 兜底用):接续候选 B 最终 status=failed 时,建议 in_progress→open,允许下次再接续。只在 in_progress 状态有效。"""
    with db.get_conn() as conn:
        return db.reopen_iteration(conn, suggestion_id)


def iteration_list_open(top_k: int = 5, source_status: str = None) -> list:
    """brainstorm 检索待接续的迭代建议(open suggestions),按 priority 降序。priority=(evaluated?2.0:0.5) × exp(-age/14)——pass 精进优先、老建议降权。接续高 priority 建选作为本轮候选之一。"""
    with db.get_conn() as conn:
        return _rows(db.list_open_iterations(conn, top_k=_norm_k(top_k, 5), source_status=source_status))


def factor_lineage_branches(min_members: int = 2, limit: int = 20) -> list:
    """血缘分支画像:root/成员数/深度/evaluated/dead_end/open suggestion。再播种的 Anchor Branch 和 saturation 判断读这里,不手写 SQL。"""
    with db.get_conn() as conn:
        return _rows(db.list_lineage_branches(
            conn,
            min_members=int(min_members) if min_members is not None else 2,
            limit=_norm_k(limit, 20),
        ))


def factor_lineage_profile(xname: str) -> dict:
    """单因子血缘画像:直连父子边 + 派生节点统计 + 所在 branch + open suggestions。"""
    with db.get_conn() as conn:
        return db.get_lineage_profile(conn, xname)


def factor_saturation_status(xname: str) -> dict:
    """返回因子所在分支的深度与饱和判定(饱和 = branch max_depth > 5)。再播种触发入口。"""
    with db.get_conn() as conn:
        return db.get_branch_saturation(conn, xname)


def record_operator_family_edge(
    op_id: int,
    base_type: str,
    family: str = None,
    pearson: float = None,
    residual: float = None,
    tested_on: str = None,
    verdict: str = "untested",
    note: str = None,
) -> dict:
    """记录算子×基底撞族边界:平台评估/assess 得到 pearson/residual 后落库。"""
    with db.get_conn() as conn:
        edge_id = db.record_operator_family_edge(
            conn,
            int(op_id),
            str(base_type),
            family=family,
            pearson=pearson,
            residual=residual,
            tested_on=tested_on,
            verdict=verdict,
            note=note,
        )
        return {"id": edge_id, "ok": True}


def coverage_map(slice: dict = None, group_by: list = None, min_count: int = 0) -> list:
    """覆盖地图:按 symbol×y_horizon×status×necessity_grade 聚合已搜空间,每格标 gap_tags(thin/hot/stale/normal)。看哪片欠探索(thin)/高效热点(hot)/该复验(stale)。覆盖空白源、brainstorm 选方向参考。口径:只统计跑过 ic_refresh 的因子。"""
    with db.get_conn() as conn:
        return db.coverage_map(conn, slice_=slice or {}, group_by=group_by,
                               min_count=min_count if min_count is not None else 0)


def coverage_gaps(top_k: int = 5) -> dict:
    """覆盖空白/热点队列:unexplored(品种×频率×假设硬度 从无 evaluated)→ thin → hot → stale 各取 top_k。覆盖空白/热点队列(补 failed/open/dead_end 都是'已试边界'的盲区,这个是'从没试过的空白')。"""
    with db.get_conn() as conn:
        return db.coverage_gaps(conn, top_k=_norm_k(top_k, 5))


def factor_residual_ic_strength(target: str, symbol: str = None, freq: str = None, y_horizon: int = None,
                                ridge: float = 0.001, max_base: int = 30) -> dict:
    """残差 IC 强度:新因子日级 IC 序列在库内基底 IC 张成空间的残差比例(预测能力不被已有因子线性解释的程度)。高=真新颖,低=冗余。补 factor_ic_correlate(pairwise 查'和某个最像')——这个给'相对全库基底的新颖性标量'。evaluate 第三维正交增强。依赖 factor_ic_daily(refresh 入库);库空/无基底 → strength=1.0。"""
    args = ["--target", str(target), "--ridge", str(ridge if ridge is not None else 0.001),
            "--max-base", str(max_base if max_base is not None else 30)]
    if symbol:
        args += ["--symbol", str(symbol)]
    if freq:
        args += ["--freq", str(freq)]
    if y_horizon is not None:
        args += ["--y-horizon", str(y_horizon)]
    return _spawn_json(RESIDUAL_IC, args, timeout=30)


TOOLS = [
    ("factor_search", factor_search),
    ("factor_recent_lessons", factor_recent_lessons),
    ("factor_list", factor_list),
    ("factor_detail", factor_detail),
    ("factor_similar", factor_similar),
    ("factor_semantic_search", factor_semantic_search),
    ("factor_counts", factor_counts),
    ("factor_ic_correlate", factor_ic_correlate),
    ("factor_ic_refresh", factor_ic_refresh),
    ("iteration_open", iteration_open),
    ("iteration_realize", iteration_realize),
    ("iteration_reopen", iteration_reopen),
    ("iteration_list_open", iteration_list_open),
    ("factor_lineage_branches", factor_lineage_branches),
    ("factor_lineage_profile", factor_lineage_profile),
    ("factor_saturation_status", factor_saturation_status),
    ("record_operator_family_edge", record_operator_family_edge),
    ("coverage_map", coverage_map),
    ("coverage_gaps", coverage_gaps),
    ("factor_residual_ic_strength", factor_residual_ic_strength),
]
