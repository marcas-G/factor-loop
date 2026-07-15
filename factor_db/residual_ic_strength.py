"""残差 IC 强度：新因子日级 IC 序列在库内基底 IC 张成空间的残差比例。

业务语义：
  residual_ic_strength = mean|resid| / mean|t|
    高（接近 1）= target 的预测能力不被库内因子线性解释 = 真新颖
    低（接近 0）= target IC 大部分被基底线性解释 = 冗余

与 factor_ic_correlate（pairwise 查"和某个最像"）互补：
  correlate 给"和单个因子的最高 |pearson|"；本脚本给"相对整个基底的新颖性标量"。
  两者都进 evaluate 第三维正交判定。

数学：
  对每个场景 (symbol, freq, y_horizon)，取 target 日级 IC 序列 t [T]，
  基底 = 同场景其他 evaluated 因子的日级 IC，按与 target 的 |pearson| 取 top-K 最相关代表
  （最能解释 target 的，残差才有意义；K 上限防共线爆炸），岭回归 t = B·w + resid。

用法:
    python factor_db/residual_ic_strength.py --target Foo
    python factor_db/residual_ic_strength.py --target Foo --symbol SHFE-AG --freq ... --y-horizon 1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db


def load_series(conn, xname, symbol, freq, y_horizon):
    rows = conn.execute(
        "SELECT date, ic FROM factor_ic_daily "
        "WHERE factor_xname=? AND symbol=? AND freq=? AND y_horizon=? ORDER BY date",
        (xname, symbol, freq, y_horizon),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="残差 IC 强度（相对全库基底的新颖性）")
    ap.add_argument("--target", required=True, help="目标因子 xname")
    ap.add_argument("--symbol")
    ap.add_argument("--freq")
    ap.add_argument("--y-horizon", type=int, dest="y_horizon")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--ridge", type=float, default=1e-3, help="岭回归正则(防基底共线);IC 幅度小,默认 1e-3")
    ap.add_argument("--max-base", type=int, default=30, dest="max_base",
                    help="基底因子数上限(按 |pearson| 选最能解释 target 的代表)")
    args = ap.parse_args()

    with db.get_conn(args.db) as conn:
        if args.symbol and args.freq and args.y_horizon is not None:
            scenes = [(args.symbol, args.freq, args.y_horizon)]
        else:
            rows = conn.execute(
                "SELECT DISTINCT symbol, freq, y_horizon FROM factor_ic_daily WHERE factor_xname=?",
                (args.target,),
            ).fetchall()
            scenes = [(r[0], r[1], r[2]) for r in rows]

        results = []
        for symbol, freq, yh in scenes:
            tgt = load_series(conn, args.target, symbol, freq, yh)
            if len(tgt) < 10:
                results.append({"symbol": symbol, "freq": freq, "y_horizon": yh,
                                "n_dates": len(tgt), "residual_ic_strength": None,
                                "reason": f"target 日级 IC 不足({len(tgt)}<10)"})
                continue

            base_rows = conn.execute(
                """SELECT d.factor_xname, d.date, AVG(d.ic) AS ic
                   FROM factor_ic_daily d
                   JOIN factors f ON f.xname = d.factor_xname
                   WHERE d.symbol=? AND d.y_horizon=?
                     AND d.factor_xname != ? AND f.status='evaluated'
                   GROUP BY d.factor_xname, d.date
                   ORDER BY d.factor_xname, d.date""",
                (symbol, yh, args.target),
            ).fetchall()
            base = defaultdict(dict)
            for fn, dt, ic in base_rows:
                base[fn][dt] = ic

            dates = sorted(tgt.keys())
            t = np.array([tgt[d] for d in dates], dtype=np.float64)

            if not base:
                results.append({"symbol": symbol, "freq": freq, "y_horizon": yh,
                                "n_dates": len(tgt), "n_base": 0,
                                "residual_ic_strength": 1.0,
                                "reason": "无基底因子(库空/该场景无其他 evaluated),残差=target 自身"})
                continue

            # 每个 base 因子与 target 的 |pearson|，取 top-K 最相关代表
            cors = []
            for fn, series in base.items():
                b = np.array([series.get(d, np.nan) for d in dates], dtype=np.float64)
                mask = ~(np.isnan(b) | np.isnan(t))
                c = abs(np.corrcoef(t[mask], b[mask])[0, 1]) if mask.sum() >= 10 else 0.0
                if np.isnan(c):
                    c = 0.0
                cors.append((c, fn, b))
            cors.sort(key=lambda x: x[0], reverse=True)
            cors = cors[: args.max_base]

            cols, used = [], []
            for _, fn, b in cors:
                col = b.copy()
                nan_mask = np.isnan(col)
                if nan_mask.all():
                    continue
                col[nan_mask] = np.nanmean(col)
                cols.append(col)
                used.append(fn)
            if not cols:
                results.append({"symbol": symbol, "freq": freq, "y_horizon": yh,
                                "n_dates": len(tgt), "n_base": 0,
                                "residual_ic_strength": 1.0, "reason": "基底全空"})
                continue

            B = np.column_stack(cols)
            K = B.shape[1]
            A = B.T @ B + args.ridge * np.eye(K)
            w = np.linalg.solve(A, B.T @ t)
            resid = t - B @ w

            mean_abs_t = float(np.mean(np.abs(t)))
            mean_abs_resid = float(np.mean(np.abs(resid)))
            strength = mean_abs_resid / mean_abs_t if mean_abs_t > 1e-12 else 0.0

            results.append({
                "symbol": symbol, "freq": freq, "y_horizon": yh,
                "n_dates": len(dates), "n_base": K, "base_factors": used,
                "target_mean_abs_ic": round(mean_abs_t, 6),
                "resid_mean_abs_ic": round(mean_abs_resid, 6),
                "residual_ic_strength": round(strength, 4),
            })

    print(json.dumps({"target": args.target, "scenes": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
