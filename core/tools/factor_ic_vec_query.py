"""因子 IC 序列向量查询接口。

查询语义：
  - "找冗余因子" = 找 IC 序列相似的因子 = 预测能力同涨同跌
  - 两个因子 IC 序列 Pearson 高 = 它们的"有效时间"重合 = 真冗余
  - 标准化向量的 cos ≡ Pearson（z-score 后严格成立）
  - sqlite-vec L2 距离 → cos：cos = 1 - d²/2（L2 归一化后严格成立）

核心 API:
  find_correlated_factors(target, symbol, freq, y_horizon)
  find_redundancy_clusters(symbol, y_horizon)
  precise_corr(factor_a, factor_b, symbol, freq, y_horizon)
  top_ic_factors(symbol, y_horizon)               # 业务用：找强信号因子
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db


def _get_vector(conn, factor_xname: str, symbol: str, freq: str, y_horizon: int) -> bytes | None:
    row = conn.execute(
        """
        SELECT embedding FROM factor_ic_vec
        WHERE factor_xname = ? AND symbol = ? AND freq = ? AND y_horizon = ?
        LIMIT 1
        """,
        (factor_xname, symbol, freq, y_horizon),
    ).fetchone()
    return row[0] if row else None


def _l2_to_pearson(distance: float) -> float:
    """L2 归一化后：cos = 1 - d²/2，z-score 后 cos ≡ Pearson"""
    return 1.0 - (distance ** 2) / 2.0


def find_correlated_factors(
    conn,
    target_factor: str,
    symbol: str,
    freq: str,
    y_horizon: int,
    top_k: int = 20,
    min_abs_pearson: float = 0.5,
    same_symbol_only: bool = True,
    same_horizon_only: bool = True,
    status_filter: str | None = "evaluated",
) -> list[dict]:
    """找和 target IC 行为相似的因子。

    Args:
        target_factor: 目标因子 xname
        symbol, freq, y_horizon: 定位 target 向量
        top_k: ANN 粗筛数
        min_abs_pearson: Pearson 绝对值阈值
        same_symbol_only: 限定同 symbol（推荐）
        same_horizon_only: 限定同 y_horizon（推荐，跨 horizon 比较业务意义弱）
        status_filter: 基底只对照该 status 的因子(默认 'evaluated')。
            dead_end 是冗余/失败毙的废品,不该进冗余比对基底——否则每轮 dead_end 累积,
            新因子越来越易撞废品被判冗余(越挖越难)。传 None 关闭(看全 status)。

    Returns:
        [{"factor", "symbol", "freq", "y_horizon", "distance", "pearson_approx"}, ...]
    """
    target_blob = _get_vector(conn, target_factor, symbol, freq, y_horizon)
    if target_blob is None:
        return []

    # status 过滤会筛掉 dead_end,扩大搜索 k 补偿(否则过滤后结果不足 top_k)
    search_k = top_k * 3 if status_filter else top_k

    sql = """
        SELECT factor_xname, symbol, freq, y_horizon, distance
        FROM factor_ic_vec
        WHERE embedding MATCH ? AND k = ?
    """
    params: list = [target_blob, search_k]
    if same_symbol_only:
        sql += " AND symbol = ?"
        params.append(symbol)
    if same_horizon_only:
        sql += " AND y_horizon = ?"
        params.append(y_horizon)

    sql += " ORDER BY distance"

    # status 过滤集合(基底只留 evaluated,排除 dead_end 污染)
    valid_xnames = None
    if status_filter:
        valid_xnames = {
            r[0] for r in conn.execute(
                "SELECT xname FROM factors WHERE status = ?", (status_filter,)
            ).fetchall()
        }

    results = []
    for factor, sym, frq, yh, dist in conn.execute(sql, params).fetchall():
        if (factor == target_factor and sym == symbol
                and frq == freq and yh == y_horizon):
            continue
        if valid_xnames is not None and factor not in valid_xnames:
            continue  # dead_end/其他 status 不进冗余基底
        approx = _l2_to_pearson(dist)
        if abs(approx) >= min_abs_pearson:
            results.append({
                "factor": factor,
                "symbol": sym,
                "freq": frq,
                "y_horizon": yh,
                "distance": dist,
                "pearson_approx": approx,
            })
    return results


def find_redundancy_clusters(
    conn,
    symbol: str,
    y_horizon: int,
    threshold: float = 0.85,
) -> list[list[str]]:
    """找冗余簇（并查集聚类）。"""
    factors = [
        (r[0], r[1]) for r in conn.execute(
            "SELECT DISTINCT factor_xname, freq FROM factor_ic_vec "
            "WHERE symbol = ? AND y_horizon = ?",
            (symbol, y_horizon),
        ).fetchall()
    ]

    parent = {f: f for f, _ in factors}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for f, freq in factors:
        neighbors = find_correlated_factors(
            conn, f, symbol, freq, y_horizon,
            top_k=5, min_abs_pearson=threshold,
            same_symbol_only=True, same_horizon_only=True,
        )
        for n in neighbors:
            union(f, n["factor"])

    clusters: dict[str, list[str]] = {}
    for f, _ in factors:
        clusters.setdefault(find(f), []).append(f)
    return [sorted(c) for c in clusters.values() if len(c) > 1]


def precise_corr(
    conn,
    factor_a: str,
    factor_b: str,
    symbol: str,
    y_horizon: int,
) -> dict | None:
    """精算两因子 IC 序列的真实 Pearson / Spearman。

    直接从 /tmp/factor-vec-cache 下的 xy 缓存重算 IC 序列。
    freq_a / freq_b 各自从因子本身取（不同因子 freq 标识不同）。
    """
    from scipy.stats import spearmanr
    from core.tools.refresh_factor_ic_vectors import (
        CACHE_DIR, download_factor, load_ic_series,
    )

    def _ic_series(factor):
        dailyx = CACHE_DIR / factor / "dailyX"
        if not dailyx.exists():
            dailyx = download_factor(factor, CACHE_DIR)
        if not dailyx:
            return {}
        return load_ic_series(dailyx)

    a_map = _ic_series(factor_a)
    b_map = _ic_series(factor_b)

    # 在指定 symbol 上找各自的 IC 序列（取该 symbol 的任意 freq，因为 freq 不同）
    a_series = None
    b_series = None
    a_freq = None
    b_freq = None
    for (sym, freq, yh), s in a_map.items():
        if sym == symbol and yh == y_horizon:
            a_series = s
            a_freq = freq
            break
    for (sym, freq, yh), s in b_map.items():
        if sym == symbol and yh == y_horizon:
            b_series = s
            b_freq = freq
            break
    if a_series is None or b_series is None:
        return None

    import pandas as pd
    df = pd.concat([a_series.rename("A"), b_series.rename("B")], axis=1).dropna()
    if len(df) < 5:
        return None

    a_vals = df["A"].to_numpy(dtype=np.float64)
    b_vals = df["B"].to_numpy(dtype=np.float64)
    pearson = float(np.corrcoef(a_vals, b_vals)[0, 1])
    rho, _ = spearmanr(a_vals, b_vals)
    return {
        "n_samples": int(len(df)),
        "pearson": pearson,
        "spearman": float(rho),
        "overlap_start": str(df.index[0]),
        "overlap_end": str(df.index[-1]),
        "freq_a": a_freq,
        "freq_b": b_freq,
    }


def top_ic_factors(
    conn,
    symbol: str,
    y_horizon: int,
    top_n: int = 20,
) -> list[dict]:
    """业务用：找指定 (symbol, horizon) 上 IC / ICIR 最强的因子。

    不是 ANN 查询，直接扫 meta 表排序。
    """
    rows = conn.execute(
        """
        SELECT factor_xname, freq, mean_ic, std_ic, icir, n_samples,
               start_date, end_date
        FROM factor_ic_vec_meta
        WHERE symbol = ? AND y_horizon = ?
        ORDER BY ABS(icir) DESC
        LIMIT ?
        """,
        (symbol, y_horizon, top_n),
    ).fetchall()
    return [dict(r) for r in rows]


def list_available_scenes(conn) -> list[tuple[str, int, int]]:
    """列出 (symbol, y_horizon) 场景，每个场景下有多少因子。"""
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT symbol, y_horizon, COUNT(DISTINCT factor_xname) "
            "FROM factor_ic_vec GROUP BY symbol, y_horizon "
            "ORDER BY symbol, y_horizon"
        ).fetchall()
    ]


# ============ CLI ============

def _cli():
    import argparse, json
    ap = argparse.ArgumentParser(description="因子 IC 序列向量查询")
    ap.add_argument("--db", default=str(db.DB_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scenes", help="列出所有 (symbol, y_horizon) 场景")

    p_top = sub.add_parser("top", help="找指定场景下 ICIR 最强的因子")
    p_top.add_argument("--symbol", required=True)
    p_top.add_argument("--y-horizon", type=int, required=True)
    p_top.add_argument("--top-n", type=int, default=10)

    p_find = sub.add_parser("find", help="找 IC 行为相似的因子")
    p_find.add_argument("--target", required=True)
    p_find.add_argument("--symbol", required=True)
    p_find.add_argument("--freq", required=True)
    p_find.add_argument("--y-horizon", type=int, required=True)
    p_find.add_argument("--top-k", type=int, default=20)
    p_find.add_argument("--threshold", type=float, default=0.5)

    p_cluster = sub.add_parser("clusters", help="找冗余簇")
    p_cluster.add_argument("--symbol", required=True)
    p_cluster.add_argument("--y-horizon", type=int, required=True)
    p_cluster.add_argument("--threshold", type=float, default=0.85)

    p_precise = sub.add_parser("precise", help="精算两因子 IC 序列真实相关")
    p_precise.add_argument("--a", required=True)
    p_precise.add_argument("--b", required=True)
    p_precise.add_argument("--symbol", required=True)
    p_precise.add_argument("--y-horizon", type=int, required=True)

    p_meta = sub.add_parser("meta", help="查单因子的 factor_ic_vec_meta(所有场景 daily ICIR/mean_ic/n)")
    p_meta.add_argument("--xname", required=True)

    args = ap.parse_args()

    with db.get_conn(args.db) as conn:
        if args.cmd == "meta":
            rows = conn.execute(
                "SELECT symbol, freq, y_horizon, icir, mean_ic, std_ic, n_samples "
                "FROM factor_ic_vec_meta WHERE factor_xname LIKE ? ORDER BY y_horizon",
                (args.xname + "%",),
            ).fetchall()
            if not rows:
                print("无数据(该因子未 refresh vec)")
            else:
                print(json.dumps(
                    [{"symbol": r[0], "freq": r[1], "y_horizon": r[2],
                      "icir": r[3], "mean_ic": r[4], "std_ic": r[5], "n_samples": r[6]}
                     for r in rows],
                    ensure_ascii=False, indent=1))

        elif args.cmd == "scenes":
            print(f"{'symbol':14} {'horizon':>8} {'#factors':>8}")
            print("-" * 32)
            for sym, yh, n in list_available_scenes(conn):
                print(f"{sym:14} {yh:>8} {n:>8}")

        elif args.cmd == "top":
            rows = top_ic_factors(conn, args.symbol, args.y_horizon, args.top_n)
            if not rows:
                print("无数据")
            print(f"{'factor':30} {'mean_ic':>10} {'icir':>8} {'n':>4}")
            print("-" * 56)
            for r in rows:
                print(f"{r['factor_xname']:30} {r['mean_ic']:>+10.4f} "
                      f"{r['icir']:>+8.3f} {r['n_samples']:>4}")

        elif args.cmd == "find":
            results = find_correlated_factors(
                conn, args.target, args.symbol, args.freq, args.y_horizon,
                top_k=args.top_k, min_abs_pearson=args.threshold,
            )
            if not results:
                print("无匹配")
            print(f"{'factor':30} {'pearson':>10} {'distance':>10}")
            print("-" * 54)
            for r in results:
                print(f"{r['factor']:30} {r['pearson_approx']:>+10.4f} "
                      f"{r['distance']:>10.4f}")

        elif args.cmd == "clusters":
            clusters = find_redundancy_clusters(
                conn, args.symbol, args.y_horizon, args.threshold,
            )
            if not clusters:
                print("未发现冗余簇")
            for i, c in enumerate(clusters, 1):
                print(f"簇 #{i}: {', '.join(c)}")

        elif args.cmd == "precise":
            r = precise_corr(conn, args.a, args.b, args.symbol, args.y_horizon)
            if r is None:
                print("无法精算")
            else:
                print(json.dumps(r, indent=2))


if __name__ == "__main__":
    _cli()
