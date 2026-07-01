"""同步 run state 里 check_done 因子的 seven_dim 评估 → factors.db 评估字段。

填: latest_ic / latest_icir / latest_sharpe / latest_rank_ic / status
来源: state.factors[i].evidence.seven_dim_summary
  - latest_ic/icir ← seven_dim_best.screening(ic_mean / icir)
  - latest_sharpe  ← deepbest.conditional_sharpe
  - latest_rank_ic ← deepbest.daily_rank_ic(daily 分桶,优先);旧 run 回退 rank_ic_max(pooled)
  - status         ← factor_level.keep > 0 ? 'evaluated' : 'dead_end'

用法:
  python factor_db/sync_eval_to_db.py --run-id <run_id>            # 同步该 run 所有 check_done
  python factor_db/sync_eval_to_db.py --run-id <run_id> --xname Foo
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path.home() / ".quant-runs"
DEFAULT_DB = ROOT / "factors.db"


def sync_one(conn, fac) -> dict:
    xname = fac.get("name")
    if fac.get("failure_layer") != "check_done":
        return {"xname": xname, "skipped": fac.get("failure_layer") or "no-check_done"}
    ev = fac.get("evidence") or {}
    sd = ev.get("seven_dim_summary") or {}
    screening = (sd.get("seven_dim_best") or {}).get("screening") or {}
    deep = sd.get("deep_best") or sd.get("deepbest") or {}
    fl = sd.get("factor_level") or {}

    ic = screening.get("ic_mean")
    icir = screening.get("icir")
    sharpe = deep.get("conditional_sharpe")
    # rank_ic 优先取 daily 分桶口径(daily_rank_ic);旧 run 回退 pooled rank_ic_max
    rank_ic = deep.get("daily_rank_ic")
    if rank_ic is None:
        rank_ic = deep.get("rank_ic_max")
    keep = fl.get("keep", 0)
    status = "evaluated" if keep > 0 else "dead_end"

    cur = conn.execute(
        "UPDATE factors SET latest_ic=?, latest_icir=?, latest_sharpe=?, "
        "latest_rank_ic=?, status=?, last_updated_ts=CURRENT_TIMESTAMP WHERE xname=?",
        (ic, icir, sharpe, rank_ic, status, xname),
    )
    return {
        "xname": xname, "updated_rows": cur.rowcount,
        "latest_ic": ic, "latest_icir": icir, "latest_sharpe": sharpe,
        "latest_rank_ic": rank_ic, "keep": keep, "status": status,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="同步 run check_done 评估 → factors.db")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--xname", help="只同步指定因子")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()

    state_path = RUNS_DIR / args.run_id / "state.json"
    if not state_path.exists():
        raise SystemExit(f"[ERROR] state 不存在: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    factors = state.get("factors") or []
    if args.xname:
        factors = [f for f in factors if f.get("name") == args.xname]

    conn = sqlite3.connect(args.db)
    for fac in factors:
        print(sync_one(conn, fac))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
