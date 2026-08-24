#!/usr/bin/env python3
"""One research-round driver: persist candidate -> platform submit -> check -> restest.

Usage:
    /home/lgao/quant-venv/bin/python core/tools/run_round_driver.py \
        --run-id <id> --factor-index <i> --xname <X> --file <factors/X.h> \
        --categories AG --params '{"Win": 200}' \
        [--restest] [--no-restest]

It only drives the mechanical platform part of a research round; assess verdict
and persist are left to the caller (AI step).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.mcp import run_store
from core.mcp.tools.persist import persist_candidates
from core.mcp.tools.platform import (
    platform_check_factor,
    platform_restest_factor,
    platform_submit_factor,
)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--factor-index", type=int, default=0)
    ap.add_argument("--xname", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--idea", required=True)
    ap.add_argument("--formula", required=True)
    ap.add_argument("--intuition", required=True)
    ap.add_argument("--hypothesis", default="")
    ap.add_argument("--categories", default="AG")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--tags", default="")
    ap.add_argument("--reseed-from", default=None)
    ap.add_argument("--measurement-object", default=None)
    ap.add_argument("--operation", default=None)
    ap.add_argument("--distinction", default=None)
    ap.add_argument("--suggestion-id", type=int, default=None)
    ap.add_argument("--iterates-from", default=None)
    ap.add_argument("--no-restest", action="store_true")
    args = ap.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    params = json.loads(args.params)
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    factor = {
        "name": args.xname,
        "formula": args.formula,
        "intuition": args.intuition,
        "hypothesis": args.hypothesis,
        "tags": tags,
        "params": params,
        "categories": categories,
        "reseed_from": args.reseed_from,
        "measurement_object": args.measurement_object,
        "operation": args.operation,
        "distinction": args.distinction,
        "suggestion_id": args.suggestion_id,
        "iterates_from": args.iterates_from,
    }
    persist = persist_candidates(args.run_id, args.idea, [factor])
    print("persist:", json.dumps(persist, ensure_ascii=False))
    if not persist.get("idea_id"):
        raise SystemExit(1)

    run_store.run_save(args.run_id, {
        f"factors.{args.factor_index}.factor_file": args.file,
        f"factors.{args.factor_index}.status": "submitting",
    })

    submit = platform_submit_factor(args.xname, args.file, categories, params)
    print("submit:", json.dumps(
        {k: v for k, v in submit.items() if k != "raw"}, ensure_ascii=False))
    if not submit.get("ok"):
        raise SystemExit(1)

    check_output = str(ROOT / ".tmp" / "check" / args.run_id / f"{args.xname}_check")
    check = platform_check_factor(
        args.xname, submit, check_output, args.run_id, args.factor_index)
    print("check:", json.dumps(check, ensure_ascii=False))
    if check.get("failureLayer") != "check_done":
        raise SystemExit(1)

    if not args.no_restest:
        restest = platform_restest_factor(
            args.xname, args.file, args.run_id, args.factor_index)
        print("restest:", json.dumps(restest, ensure_ascii=False))


if __name__ == "__main__":
    main()
