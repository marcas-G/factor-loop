#!/usr/bin/env python3
"""回填 factor_structure 表 — 提取指定 .h 列表的结构指纹并写入。

用途:
  1. 把基底因子(ImbalanceBase/LogBookImbalanceRaw/OITailEnergyBase)入 factors 表(若不在)做 R3 查重锚点
  2. 提取它们的结构指纹写入 factor_structure 表

调用:
  python3 core/retrieval/backfill_factor_structure.py
  python3 core/retrieval/backfill_factor_structure.py --files factors/X.h factors/Y.h
  python3 core/retrieval/backfill_factor_structure.py --ensure-factors  # 同时入 factors 表
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db
from core.retrieval.factor_structure_extractor import extract_structure, upsert_structure, parse_frontmatter

DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "factors.db")

# 默认基底(第 1 步提取范围 — 用户确认)
DEFAULT_BASES = [
    "factors/ImbalanceBase.h",
    "factors/LogBookImbalanceRaw.h",
    "factors/OITailEnergyBase.h",
]


def ensure_factor_row(conn, xname: str, h_path: str, fm: dict) -> bool:
    """若 factors 表无此 xname,插一行(status=evaluated 做查重锚点)。返回是否新建。"""
    exists = conn.execute(
        "SELECT 1 FROM factors WHERE xname=?", (xname,)
    ).fetchone()
    if exists:
        return False
    conn.execute("""
        INSERT INTO factors (xname, class_name, file_path, formula_text, params, status)
        VALUES (?,?,?,?,?, 'evaluated')
    """, (
        xname,
        fm.get("class_name", xname),
        h_path,
        fm.get("formula", ""),
        fm.get("params", "{}"),
    ))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None,
                    help="指定 .h 文件列表(默认 3 个基底)")
    ap.add_argument("--ensure-factors", action="store_true", default=True,
                    help="同时把因子入 factors 表(若不在)")
    ap.add_argument("--no-ensure-factors", dest="ensure_factors", action="store_false")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    files = args.files or DEFAULT_BASES
    files = [Path(f) for f in files]
    for f in files:
        if not f.exists():
            print(f"MISSING: {f}", file=sys.stderr)
            sys.exit(1)

    ok = 0
    fail = 0
    with db.get_conn(args.db) as conn:
        for h in files:
            try:
                rec = extract_structure(h)
                if rec is None:
                    print(f"  SKIP (no frontmatter/formula): {h.name}")
                    fail += 1
                    continue
                # 入 factors 表(若需 + 若不在)
                if args.ensure_factors:
                    text = h.read_text(encoding="utf-8", errors="replace")
                    fm = parse_frontmatter(text)
                    if fm:
                        new = ensure_factor_row(conn, rec["xname"], str(h), fm)
                        flag = " (NEW in factors)" if new else ""
                    else:
                        flag = " (no frontmatter, skip factors insert)"
                else:
                    flag = ""
                upsert_structure(conn, rec)
                conn.commit()
                print(f"  OK: {rec['xname']:40} hash={rec['canonical_hash']} "
                      f"complexity={rec['complexity']:9} prims={list(rec['operator_primitives'])}{flag}")
                ok += 1
            except Exception as e:
                print(f"  FAIL: {h.name} — {e}", file=sys.stderr)
                fail += 1

    print(f"\n{'='*60}")
    print(f"extracted: {ok} ok, {fail} fail")
    # coverage 报告
    with db.get_conn(args.db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM factor_structure").fetchone()[0]
        factors_total = conn.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
        print(f"factor_structure rows: {total}")
        print(f"factors rows: {factors_total}")


if __name__ == "__main__":
    main()
