"""机器友好 CLI：查 target 因子的 IC 行为冗余因子，输出 JSON。

供 MCP `factor_ic_correlate` 工具调用（evaluate skill 用它查新因子与库内因子的行为冗余）。

语义：两个因子 IC 序列 Pearson 高 = 预测能力同涨同跌 = 真冗余（比 formula 文本语义更贴近业务）。

用法：
  # 只给 target：遍历该因子所有 (symbol, freq, y_horizon) 场景，按 |pearson| 聚合对方因子
  python ic_correlate.py --target KyleLambdaVolatility
  # 指定单场景
  python ic_correlate.py --target X --symbol SHFE-AG --freq f1 --y-horizon 60
"""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db
from core.tools.factor_ic_vec_query import find_correlated_factors


def main() -> None:
    ap = argparse.ArgumentParser(description="查 target 因子的 IC 行为冗余因子（JSON 输出）")
    ap.add_argument("--target", required=True, help="目标因子 xname")
    ap.add_argument("--symbol", default=None, help="限定 symbol；不给则遍历 target 所有场景")
    ap.add_argument("--freq", default=None, help="限定 freq")
    ap.add_argument("--y-horizon", type=int, default=None, help="限定 y_horizon")
    ap.add_argument("--k", type=int, default=20, help="ANN 粗筛数（每场景）")
    ap.add_argument("--min-abs-pearson", type=float, default=0.5, help="冗余阈值 |pearson|")
    ap.add_argument("--top", type=int, default=15, help="返回 top N 冗余因子")
    args = ap.parse_args()

    with db.get_conn() as conn:
        if args.symbol and args.freq and args.y_horizon is not None:
            scenes = [(args.symbol, args.freq, args.y_horizon)]
        else:
            scenes = [
                (r[0], r[1], r[2])
                for r in conn.execute(
                    "SELECT DISTINCT symbol, freq, y_horizon FROM factor_ic_vec "
                    "WHERE factor_xname = ?",
                    (args.target,),
                ).fetchall()
            ]

        if not scenes:
            print(json.dumps(
                {"target": args.target, "error": "无 IC 向量（先 factor_ic_refresh）",
                 "n_scenes": 0, "n_redundant": 0, "results": []},
                ensure_ascii=False,
            ))
            return

        # 按"对方因子"聚合，取最大 |pearson|（跨场景）
        best: dict[str, dict] = {}
        for sym, frq, yh in scenes:
            rows = find_correlated_factors(
                conn, args.target, sym, frq, yh,
                top_k=args.k, min_abs_pearson=args.min_abs_pearson,
                same_symbol_only=True, same_horizon_only=True,
            )
            for r in rows:
                key = r["factor"]
                cur = best.get(key)
                if cur is None or abs(r["pearson_approx"]) > abs(cur["pearson_approx"]):
                    best[key] = {**r, "vs_scene": f"{sym}@{frq}@h{yh}"}

        results = sorted(best.values(), key=lambda x: -abs(x["pearson_approx"]))[: args.top]
        print(json.dumps(
            {"target": args.target, "n_scenes": len(scenes),
             "n_redundant": len(results), "results": results},
            ensure_ascii=False,
        ))


if __name__ == "__main__":
    main()
