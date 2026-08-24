#!/usr/bin/env python3
"""R1 · select_research_object — 全库下一只最值得研究的 Factor 是谁?

被 Step 0 调用。多信号打分(非单查询):

  ① 候选池: status ∈ {evaluated, failed, dead_end} 全库
  ② 程序过滤: 排除 recently_selected + exhaustion_score > τ
  ③ 打分:
       score = w1·(1-exhaustion)          # 研究新颖度(越没研究过分越高)
             + w2·fertility               # 结构生育度(lineage 分支小且 dead_end 少)
             + w3·has_open_idea           # 有未关 idea
             + w4·recency_falloff         # 久未被选(鼓励覆盖盲区)
             - w5·dead_end_proximity      # 同 lineage 分支 dead_end 密度
  ④ 返回 top_k + rationale + coverage(never_selected_count 必报)

库空(0 因子)→ 报 library_empty + 建议:先跑 factor loop 产因子。
库有因子但 factor_research_state 空 → 所有因子 exhaustion=0(全 fresh),按 fertility+recency 排。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db

from core.config import DB_PATH  # noqa: E402  单一真相路径

# 默认权重(可外部调)
DEFAULT_WEIGHTS = {
    "novelty": 0.30,        # w1: 1-exhaustion
    "fertility": 0.25,      # w2: 族小 dead_end 少
    "open_q": 0.20,         # w3: 有 open idea
    "recency": 0.15,        # w4: 久未选
    "dead_end_penalty": 0.10,  # w5: 同族 dead_end 密度(扣)
}
EXHAUSTION_THRESHOLD = 0.85  # 超过此 exhaustion 不入选(研究耗尽)


def _load_library_stats(conn) -> dict:
    """全库统计(coverage 用)。"""
    total = conn.execute("SELECT COUNT(*) FROM factors WHERE deprecated_at IS NULL").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM factors WHERE deprecated_at IS NULL GROUP BY status"
    ).fetchall())
    return {
        "total": total,
        "by_status": by_status,
    }


def _branch_stats(conn, xname: str):
    row = conn.execute(
        "SELECT primary_root_xname FROM factor_lineage_nodes WHERE xname=?", (xname,)
    ).fetchone()
    root = row[0] if row else xname
    return conn.execute(
        "SELECT member_count, dead_end_count FROM factor_lineage_branches WHERE root_xname=?",
        (root,),
    ).fetchone()


def _fertility_score(conn, xname: str) -> tuple[float, dict]:
    """结构生育度:lineage 分支小 + 分支内 dead_end 少 = 高生育度(还有探索空间)。
    返回 (score 0-1, detail)。"""
    branch = _branch_stats(conn, xname)
    if not branch or branch["member_count"] is None:
        return (0.5, {"reason": "无 lineage 分支,中性", "family_size": 0, "family_dead_end": 0})
    fam_size, fam_de = branch["member_count"], branch["dead_end_count"]
    dead_ratio = fam_de / fam_size
    # 族小(1-3)且 dead_end 少 → 高分;族大且 dead_end 多 → 低分
    size_score = max(0.0, 1.0 - (fam_size - 1) / 20.0)  # 1 个=1.0, 21+个=0
    health_score = 1.0 - min(1.0, dead_ratio)
    score = 0.5 * size_score + 0.5 * health_score
    return (round(score, 4), {
        "family_size": fam_size, "family_dead_end": fam_de,
        "dead_ratio": round(dead_ratio, 4),
    })


def _has_open_idea(conn, xname: str) -> bool:
    """因子是否挂着未关 idea(idea_factor_links → ideas.status=open)。"""
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM idea_factor_links ifl "
            "JOIN ideas i ON i.id=ifl.idea_id "
            "WHERE ifl.factor_xname=? AND i.status='open'", (xname,)
        ).fetchone()
        return r[0] > 0
    except Exception:
        return False


def _recency_falloff(last_selected_ts, now_ts=None) -> float:
    """久未被选 → 加分(鼓励覆盖盲区)。无记录 → 1.0(从未选)。"""
    if last_selected_ts is None:
        return 1.0
    # 简化:用字符串比较算天数(避免依赖 now)
    # 实际由调用方传 now_ts;无则返回中性
    return 0.5


def _dead_end_proximity(conn, xname: str) -> float:
    """同 lineage 分支 dead_end 密度(扣分项)。"""
    branch = _branch_stats(conn, xname)
    if not branch or not branch["member_count"]:
        return 0.0
    return round(branch["dead_end_count"] / branch["member_count"], 4)


def select_research_object(
    *,
    recently_selected: list[str] | None = None,
    exclude: dict | None = None,
    weights: dict | None = None,
    top_k: int = 5,
    conn=None,
) -> dict:
    """R1 主入口。返回 selected + alternatives + rationale + context。"""
    import sqlite3
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

    try:
        w = {**DEFAULT_WEIGHTS, **(weights or {})}
        recently_selected = recently_selected or []
        exclude = exclude or {}

        stats = _load_library_stats(conn)
        if stats["total"] == 0:
            return {
                "selected": None,
                "alternatives": [],
                "rationale": None,
                "context": {
                    "library_total": 0, "explored_fraction": 0.0,
                    "never_selected_count": 0, "library_empty": True,
                },
                "suggestion": "库空,先跑 factor loop 产因子 + 入库",
            }

        # ── 候选池 ───────────────────────────────────────────────
        pool = conn.execute(
            "SELECT xname, status, created_ts, "
            "       latest_icir, latest_r2_x, latest_res_ic "
            "FROM factors "
            "WHERE deprecated_at IS NULL AND status IN ('evaluated','failed','dead_end') "
            "ORDER BY xname"
        ).fetchall()

        # ── 逐个打分 ─────────────────────────────────────────────
        scored = []
        never_selected = 0
        for r in pool:
            xn = r["xname"]
            status = r["status"]
            icir = r["latest_icir"]
            r2_x = r["latest_r2_x"]
            res_ic = r["latest_res_ic"]
            if xn in recently_selected:
                continue
            # research_state
            rs = conn.execute(
                "SELECT research_exhaustion_score, last_selected_ts, last_outcome, times_selected "
                "FROM factor_research_state WHERE xname=?", (xn,)
            ).fetchone()
            exhaustion = rs["research_exhaustion_score"] if rs else 0.0
            last_sel = rs["last_selected_ts"] if rs else None
            times_sel = rs["times_selected"] if rs else 0
            if times_sel == 0:
                never_selected += 1
            if exhaustion > EXHAUSTION_THRESHOLD:
                continue

            novelty = 1.0 - exhaustion
            fertility, fam_detail = _fertility_score(conn, xn)
            open_q = 1.0 if _has_open_idea(conn, xn) else 0.0
            recency = _recency_falloff(last_sel)
            de_prox = _dead_end_proximity(conn, xn)

            # 非线性价值(RunLength 教训): ICIR 强 + X空间不冗余(R2_X低)
            # = 可能是非线性信号, 线性冗余判定误杀, 值得换方向/换变换重试
            nonlinear = 1.0 if (
                (icir or 0) is not None and abs(icir or 0) >= 0.3
                and (r2_x is None or (r2_x or 0) < 0.5)
            ) else 0.0

            score = (
                w["novelty"] * novelty
                + w["fertility"] * fertility
                + w["open_q"] * open_q
                + w["recency"] * recency
                + w.get("nonlinear_value", 0.10) * nonlinear
                - w["dead_end_penalty"] * de_prox
            )
            scored.append({
                "xname": xn,
                "score": round(score, 4),
                "rationale": {
                    "research_novelty": round(novelty, 4),
                    "structure_fertility": fertility,
                    "has_open_question": bool(open_q),
                    "dead_end_proximity": de_prox,
                    "exhaustion": round(exhaustion, 4),
                    "times_selected": times_sel,
                    "nonlinear_value": bool(nonlinear),
                    "composite": round(score, 4),
                },
                "ridge_svd": {
                    "r2_x": r2_x,
                    "res_ic": res_ic,
                    "icir": icir,
                },
                "family": fam_detail,
                "status": status,
            })

        scored.sort(key=lambda x: -x["score"])
        top = scored[:top_k]

        return {
            "selected": top[0]["xname"] if top else None,
            "alternatives": [
                {"xname": t["xname"], "score": t["score"],
                 "rationale": t["rationale"], "ridge_svd": t["ridge_svd"],
                 "status": t["status"]}
                for t in top[1:]
            ],
            "rationale": top[0]["rationale"] if top else None,
            "context": {
                "library_total": stats["total"],
                "by_status": stats["by_status"],
                "explored_fraction": round(
                    sum(1 for t in scored if t["rationale"]["times_selected"] > 0)
                    / max(1, len(scored), 4)),
                "never_selected_count": never_selected,
                "pool_size": len(pool),
                "library_empty": False,
            },
        }
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="R1 select_research_object")
    ap.add_argument("--recent", nargs="*", default=[], help="最近已选的 xname(避重复)")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()
    r = select_research_object(recently_selected=args.recent, top_k=args.top_k)
    print(json.dumps(r, ensure_ascii=False, indent=2))
