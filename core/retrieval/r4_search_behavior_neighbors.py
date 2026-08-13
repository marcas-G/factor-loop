#!/usr/bin/env python3
"""R4 · search_behavior_neighbors — 新 Factor 在经验 IC 空间撞到了谁?

被 Step 4 assess 调用。Empirical factor-space location:
  - 场景对齐(symbol,freq,horizon,date_range)— 必须对齐才能比
  - factor_ic_vec ANN 召回 top_k(粗筛)
  - 精确 pearson(对齐 IC 序列)
  - residual IC(新因子正交化挤掉邻居基底后剩余)
  - pearson>0.7 → COLLIDES

库无该场景 IC(factor_ic_vec 空 / 无对齐邻居)→ scene_sparse=true,撞族判定置信度降。

输入: xname + symbol + freq + horizon + date_range + top_k
返回 Contract Schema:
  neighbors[], collision_verdict, strongest_neighbor, residual_after_orthogonalization, scene
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db

from core.config import DB_PATH  # noqa: E402  单一真相路径
COLLIDES_THRESHOLD = 0.7   # |pearson| > 此 = COLLIDES
WEAK_THRESHOLD = 0.4       # |pearson| > 此 = 弱相关(标注但不撞)


def _load_ic_series(conn, xname: str, symbol: str, freq: str | None,
                    horizon: int, date_start: str | None, date_end: str | None):
    """加载某因子在某场景的逐日 IC 序列(对齐用)。返回 dict{date: ic}。"""
    sql = ("SELECT date, ic FROM factor_ic_daily "
           "WHERE factor_xname=? AND symbol=? AND y_horizon=?")
    params = [xname, symbol, horizon]
    if freq:
        sql += " AND freq=?"
        params.append(freq)
    if date_start:
        sql += " AND date>=?"
        params.append(date_start)
    if date_end:
        sql += " AND date<=?"
        params.append(date_end)
    rows = conn.execute(sql, params).fetchall()
    return {r[0]: r[1] for r in rows if r[1] is not None}


def _align_pearson(a: dict, b: dict):
    """两 IC 序列按 date 对齐算 pearson。返回 (pearson, n_overlap) 或 None。"""
    common = sorted(set(a) & set(b))
    if len(common) < 10:  # 至少 10 天重叠才有意义
        return None
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    n = len(common)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    denom = (vx * vy) ** 0.5
    if denom < 1e-12:
        return None
    return (cov / denom, n)


def _residual_ic(target: dict, bases: list[dict]):
    """target IC 正交化挤掉 bases 后的平均剩余 |IC|。
    粗实现:target 减去 bases 线性回归预测(最小二乘)。
    bases 空 → 返回 target 原始平均 |IC|。"""
    if not target:
        return None
    common = set(target)
    for b in bases:
        common &= set(b)
    common = sorted(common)
    if len(common) < 10:
        return abs(sum(target.values()) / len(target)) if target else 0.0
    y = [target[d] for d in common]
    if not bases:
        return abs(sum(y) / len(y))
    # 设计矩阵 [1, b1, b2, ...]
    X = [[1.0] + [b.get(d, 0.0) for b in bases] for d in common]
    # 最小二乘解 (X^T X)^-1 X^T y(小规模直接算)
    import numpy as np  # assess 已依赖 numpy
    A = np.array(X)
    bvec = np.array(y)
    try:
        coef, *_ = np.linalg.lstsq(A, bvec, rcond=None)
        resid = bvec - A @ coef
        return abs(float(resid.mean()))
    except Exception:
        return abs(sum(y) / len(y))


def search_behavior_neighbors(
    xname: str,
    *,
    symbol: str = "SHFE-AG",
    freq: str | None = None,
    horizon: int = 10,
    date_start: str | None = None,
    date_end: str | None = None,
    top_k: int = 30,
    vec_schema_version: str = "v1",
    conn=None,
) -> dict:
    """R4 主入口。返回 neighbors + collision_verdict + scene。"""
    import sqlite3
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            import sqlite_vec
            sqlite_vec.load(conn)
        except ImportError:
            pass

    try:
        # ── 1. 加载 target IC ────────────────────────────────────
        target_ic = _load_ic_series(conn, xname, symbol, freq, horizon, date_start, date_end)
        if not target_ic:
            return {
                "neighbors": [],
                "collision_verdict": "NO_TARGET_IC",
                "strongest_neighbor": None,
                "residual_after_orthogonalization": None,
                "scene": {
                    "symbol": symbol, "freq": freq, "horizon": horizon,
                    "date_range": [date_start, date_end],
                    "vec_schema_version": vec_schema_version,
                    "date_aligned": False, "scene_sparse": True,
                },
                "warning": f"{xname} 在该场景无 factor_ic_daily 数据(先跑 factor_ic_refresh)",
            }

        # ── 2. ANN 召回候选(factor_ic_vec)──────────────────────
        # 取 target 的 IC vec(若已 refresh 入库)
        target_vec_row = conn.execute(
            "SELECT embedding FROM factor_ic_vec "
            "WHERE factor_xname=? AND symbol=? AND y_horizon=?",
            (xname, symbol, horizon)
        ).fetchone()
        candidates = []
        if target_vec_row:
            try:
                vec_json = target_vec_row[0] if isinstance(target_vec_row[0], str) else json.dumps(list(target_vec_row[0]))
                rows = conn.execute("""
                    SELECT factor_xname, vec_distance_cosine(embedding, ?) AS dist
                    FROM factor_ic_vec
                    WHERE symbol=? AND y_horizon=? AND factor_xname != ?
                    ORDER BY dist LIMIT ?
                """, (vec_json, symbol, horizon, xname, top_k)).fetchall()
                candidates = [r[0] for r in rows]
            except Exception:
                pass
        if not candidates:
            # fallback:取同场景所有其他因子
            candidates = [r[0] for r in conn.execute(
                "SELECT DISTINCT factor_xname FROM factor_ic_daily "
                "WHERE symbol=? AND y_horizon=? AND factor_xname != ? LIMIT ?",
                (symbol, horizon, xname, top_k)
            ).fetchall()]

        # ── 3. 精确 pearson(对齐 IC 序列)──────────────────────
        neighbors = []
        for cand in candidates:
            cand_ic = _load_ic_series(conn, cand, symbol, freq, horizon, date_start, date_end)
            if not cand_ic:
                continue
            res = _align_pearson(target_ic, cand_ic)
            if res is None:
                continue
            pearson, n = res
            # operator overlap(可选,从 factor_operator_usage)
            op_overlap = None
            try:
                t_ops = set(r[0] for r in conn.execute(
                    "SELECT op_id FROM factor_operator_usage WHERE xname=?", (xname,)).fetchall())
                c_ops = set(r[0] for r in conn.execute(
                    "SELECT op_id FROM factor_operator_usage WHERE xname=?", (cand,)).fetchall())
                if t_ops and c_ops:
                    op_overlap = len(t_ops & c_ops) / len(t_ops | c_ops)
            except Exception:
                pass
            neighbors.append({
                "xname": cand,
                "pearson": round(pearson, 4),
                "n_overlap": n,
                "same_family": abs(pearson) > COLLIDES_THRESHOLD,
                "operator_overlap": round(op_overlap, 4) if op_overlap is not None else None,
            })
        neighbors.sort(key=lambda x: -abs(x["pearson"]))

        # ── 4. residual IC(正交化挤 top-N 邻居)──────────────────
        top_bases = []
        for nb in neighbors[:5]:
            if abs(nb["pearson"]) > WEAK_THRESHOLD:
                top_bases.append(_load_ic_series(
                    conn, nb["xname"], symbol, freq, horizon, date_start, date_end))
        residual = _residual_ic(target_ic, top_bases) if top_bases else abs(sum(target_ic.values()) / len(target_ic))

        # ── 5. collision_verdict ─────────────────────────────────
        strongest = neighbors[0] if neighbors else None
        if strongest and abs(strongest["pearson"]) > COLLIDES_THRESHOLD:
            collision = "COLLIDES"
        elif neighbors and any(abs(n["pearson"]) > WEAK_THRESHOLD for n in neighbors):
            collision = "WEAK_CORRELATION"
        else:
            collision = "INDEPENDENT"

        # scene_sparse:同场景其他因子少
        scene_pool = conn.execute(
            "SELECT COUNT(DISTINCT factor_xname) FROM factor_ic_daily "
            "WHERE symbol=? AND y_horizon=?", (symbol, horizon)
        ).fetchone()[0]
        scene_sparse = scene_pool < 5

        return {
            "neighbors": neighbors,
            "collision_verdict": collision,
            "strongest_neighbor": strongest["xname"] if strongest else None,
            "strongest_pearson": strongest["pearson"] if strongest else None,
            "residual_after_orthogonalization": round(residual, 4) if residual is not None else None,
            "scene": {
                "symbol": symbol, "freq": freq, "horizon": horizon,
                "date_range": [date_start, date_end],
                "vec_schema_version": vec_schema_version,
                "date_aligned": True, "scene_sparse": scene_sparse,
                "scene_pool": scene_pool,
            },
        }
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="R4 search_behavior_neighbors")
    ap.add_argument("--xname", required=True)
    ap.add_argument("--symbol", default="SHFE-AG")
    ap.add_argument("--horizon", type=int, default=10)
    args = ap.parse_args()
    r = search_behavior_neighbors(args.xname, symbol=args.symbol, horizon=args.horizon)
    print(json.dumps(r, ensure_ascii=False, indent=2))
