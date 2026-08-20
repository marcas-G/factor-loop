"""discover 工具(吸收 runtime/mcp/tools/discover.mjs)。扫库源 top-down。"""
from core.db import db


def _rows(lst):
    return [dict(r) for r in lst]


def discover_failed_hypotheses(max_score: float = 0.4, min_evaluated: int = 2, limit: int = 10) -> dict:
    """扫库源 top-down 源:扫失效假设(support_score 低 + 已有因子验证过)。这些'为什么假设错了'是下一轮反常的原料(失效回喂)。返回按 support_score 升序。"""
    with db.get_conn() as conn:
        failed = _rows(db.discover_failed_hypotheses(
            conn, max_score=max_score if max_score is not None else 0.4,
            min_evaluated=min_evaluated if min_evaluated is not None else 2,
            limit=limit if limit is not None else 10,
        ))
    return {"count": len(failed), "failed": failed}


def discover_recent_dead_ends(limit: int = 10) -> dict:
    """扫库源 top-down 源:最近 dead_end lessons(方向失效信号)。用于避雷 + 失效回喂(失效方向暴露的矛盾是反常)。"""
    with db.get_conn() as conn:
        dead_ends = _rows(db.discover_recent_dead_ends(conn, limit=limit if limit is not None else 10))
    return {"count": len(dead_ends), "dead_ends": dead_ends}


TOOLS = [
    ("discover_failed_hypotheses", discover_failed_hypotheses),
    ("discover_recent_dead_ends", discover_recent_dead_ends),
]
