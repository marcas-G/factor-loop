#!/usr/bin/env python3
"""Backfill missing factors Ridge-SVD fields from history or the platform."""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db
from core.platform.restest import aggregate_ridge_svd, run_restest


def missing_factors(conn, statuses: list[str]) -> list[dict]:
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT xname, class_name, file_path, status
        FROM factors
        WHERE status IN ({placeholders})
          AND (latest_dloocv_pct IS NULL
               OR latest_r2_x IS NULL
               OR latest_res_ic IS NULL)
        ORDER BY CASE status WHEN 'evaluated' THEN 0 ELSE 1 END, xname
        """,
        statuses,
    ).fetchall()
    return [dict(row) for row in rows]


def historical_results(runs_root: Path) -> dict[str, dict]:
    results: dict[str, dict] = {}
    if not runs_root.exists():
        return results

    for state_path in sorted(runs_root.glob("*/state.json"), key=lambda p: p.stat().st_mtime):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for factor in state.get("factors") or []:
            evidence = factor.get("evidence") or {}
            metrics = evidence.get("ridge_svd")
            xname = factor.get("name") or factor.get("xname")
            if isinstance(metrics, dict):
                metrics = [metrics]
            if not xname or not isinstance(metrics, list) or not metrics:
                continue
            agg = evidence.get("ridge_svd_agg")
            if not agg and isinstance(metrics[0], dict) and "max_dLOOCV_pct" in metrics[0]:
                agg = metrics[0]
            agg = agg or aggregate_ridge_svd(metrics)
            results[xname] = {
                "metrics": metrics,
                "agg": agg,
                "source": str(state_path.parent),
            }
    return results


def save_result(
    conn,
    xname: str,
    metrics: list[dict],
    agg: dict,
    source: str,
) -> None:
    values = (agg.get("max_dLOOCV_pct"), agg.get("R2_X"), agg.get("res_IC"))
    if any(value is None for value in values):
        raise ValueError(f"{xname}: incomplete aggregate {agg}")

    db.update_factor_ridge_svd(conn, xname, *values)
    eval_row = conn.execute(
        """
        SELECT id, eval_metrics FROM factor_evals
        WHERE factor_xname=?
        ORDER BY ts DESC, id DESC LIMIT 1
        """,
        (xname,),
    ).fetchone()
    if eval_row:
        try:
            eval_metrics = json.loads(eval_row["eval_metrics"] or "{}")
        except json.JSONDecodeError:
            eval_metrics = {}
        if not isinstance(eval_metrics, dict):
            eval_metrics = {}
        eval_metrics["ridge_svd"] = metrics
        eval_metrics["ridge_svd_agg"] = agg
        eval_metrics["ridge_svd_source"] = source
        conn.execute(
            "UPDATE factor_evals SET eval_metrics=? WHERE id=?",
            (json.dumps(eval_metrics, ensure_ascii=False), eval_row["id"]),
        )
    conn.commit()


def run_batch(rows: list[dict], batch_size: int) -> dict[str, dict]:
    output: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {
            executor.submit(run_restest, ROOT / row["file_path"], row["class_name"] or row["xname"]): row
            for row in rows
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            output[row["xname"]] = result
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill factors.latest_* Ridge-SVD fields")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--runs-root", default=os.environ.get("QUANT_MCP_RUNS_ROOT", "/home/lgao/.quant-runs"))
    parser.add_argument("--statuses", nargs="+", default=["evaluated", "dead_end"])
    parser.add_argument("--xname", action="append", help="Limit to one xname; repeatable")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--harvest-only", action="store_true")
    parser.add_argument("--report", default=str(ROOT / ".tmp" / "ridge_backfill_report.json"))
    args = parser.parse_args()

    report = {"harvested": {}, "platform": {}, "remaining": []}
    with db.get_conn(args.db) as conn:
        rows = missing_factors(conn, args.statuses)
        if args.xname:
            wanted = set(args.xname)
            rows = [row for row in rows if row["xname"] in wanted]
        if args.limit:
            rows = rows[: args.limit]

        print(f"[ridge-backfill] missing={len(rows)} statuses={args.statuses}", flush=True)
        for row in rows:
            print(f"  {row['status']:9s} {row['xname']}", flush=True)
        if args.dry_run:
            return

        history = historical_results(Path(args.runs_root))
        remaining = []
        for row in rows:
            xname = row["xname"]
            hit = history.get(xname)
            if not hit:
                remaining.append(row)
                continue
            try:
                save_result(conn, xname, hit["metrics"], hit["agg"], hit["source"])
                report["harvested"][xname] = hit["agg"]
                print(f"[harvest] {xname}: {hit['agg']}", flush=True)
            except Exception as exc:
                remaining.append(row)
                report["harvested"][xname] = {"error": str(exc)}
                print(f"[harvest-error] {xname}: {exc}", flush=True)

        if args.harvest_only:
            report["remaining"] = [row["xname"] for row in remaining]
        else:
            for offset in range(0, len(remaining), args.batch_size):
                batch = remaining[offset : offset + args.batch_size]
                names = ", ".join(row["xname"] for row in batch)
                print(f"[platform-batch] {offset + 1}-{offset + len(batch)}/{len(remaining)}: {names}", flush=True)
                results = run_batch(batch, args.batch_size)
                for row in batch:
                    xname = row["xname"]
                    result = results.get(xname, {"ok": False, "error": "no result"})
                    if result.get("ok") and result.get("metrics"):
                        agg = aggregate_ridge_svd(result["metrics"])
                        try:
                            save_result(conn, xname, result["metrics"], agg, result.get("feature", "platform"))
                            report["platform"][xname] = agg
                            print(f"[platform] {xname}: {agg}", flush=True)
                        except Exception as exc:
                            report["platform"][xname] = {"error": str(exc)}
                            print(f"[save-error] {xname}: {exc}", flush=True)
                    else:
                        report["platform"][xname] = {"error": result.get("error")}
                        print(f"[platform-error] {xname}: {result.get('error')}", flush=True)

        report["remaining"] = [
            dict(row)
            for row in missing_factors(conn, args.statuses)
            if not args.xname or row["xname"] in set(args.xname)
        ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ridge-backfill] harvested={len(report['harvested'])} platform={len(report['platform'])} remaining={len(report['remaining'])}", flush=True)
    print(f"[ridge-backfill] report={report_path}", flush=True)


if __name__ == "__main__":
    main()
