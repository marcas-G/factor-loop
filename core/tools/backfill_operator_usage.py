#!/usr/bin/env python3
"""存量算子绑定回填(算子回写链路·层3)。

从已入库因子的 formula_text / tags / .h 注释里提取 opXX 引用,
写 factors.operator_chain + factor_operator_usage(confidence=inferred)。
与入库时自动落的 declared 绑定区分——inferred 是文本推断, declared 是源头声明。

用法:
  python3 core/tools/backfill_operator_usage.py --dry-run   # 只看将写什么
  python3 core/tools/backfill_operator_usage.py             # 实际写库
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DB_PATH
from core.db import db

OP_REF_RE = re.compile(r"\bop(\d{1,3})\b")

# 语义签名(兜底: formula 实现了算子语义但文本没标 opXX 的族)
# 只收形态唯一、误报率低的; 拿不准的不收(inferred 宁缺勿滥)
SEMANTIC_SIGNATURES = [
    # (op_id, 编译到 SQL LIKE 的 formula 签名, 说明)
    # op21: 索引加权矩 sum(i*(b_i-a_i)) 形态
    (21, ["sum(i * (b_i - a_i))", "i * (b_i - a_i)", "i*(b_i-a_i)"], "位置矩(索引加权带符号矩)"),
]


def _extract_declared(conn) -> dict[str, list[int]]:
    """从 formula_text + tags 提取显式 opXX 引用。"""
    out: dict[str, list[int]] = {}
    rows = conn.execute("SELECT xname, formula_text FROM factors WHERE formula_text IS NOT NULL").fetchall()
    for xname, formula in rows:
        ids = {int(m.group(1)) for m in OP_REF_RE.finditer(formula or "")}
        if ids:
            out.setdefault(xname, set()).update(ids) if isinstance(out.get(xname), set) else out.update(
                {xname: out.get(xname, set()) | ids})
    return {k: sorted(v) for k, v in out.items()}


def _extract_semantic(conn, declared: dict[str, list[int]]) -> dict[str, list[int]]:
    """从 formula 语义签名提取(文本未标 opXX 但实现了算子形态)。"""
    inferred: dict[str, set] = {}
    rows = conn.execute("SELECT xname, formula_text FROM factors WHERE formula_text IS NOT NULL").fetchall()
    for xname, formula in rows:
        f = formula or ""
        already = set(declared.get(xname, []))
        for op_id, sigs, _note in SEMANTIC_SIGNATURES:
            if op_id in already:
                continue
            if any(sig in f for sig in sigs):
                inferred.setdefault(xname, set()).add(op_id)
    return {k: sorted(v) for k, v in inferred.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with db.get_conn() as conn:
        valid_ops = {r[0] for r in conn.execute("SELECT op_id FROM operators")}
        declared = _extract_declared(conn)
        inferred = _extract_semantic(conn, declared)

        # 已有 declared 绑定的因子不覆盖
        existing = {
            (r[0], r[1]) for r in conn.execute(
                "SELECT xname, op_id FROM factor_operator_usage WHERE note LIKE '%declared%'")
        }

        writes = []
        for xname, ids in declared.items():
            for op_id in ids:
                if op_id in valid_ops and (xname, op_id) not in existing:
                    writes.append((xname, op_id, "declared", "backfill:formula_text显式引用"))
        for xname, ids in inferred.items():
            for op_id in ids:
                if op_id in valid_ops and (xname, op_id) not in existing:
                    writes.append((xname, op_id, "inferred", "backfill:语义签名匹配"))

        print(f"declared 提取: {sum(len(v) for v in declared.values())} 条, 语义 inferred: {sum(len(v) for v in inferred.values())} 条")
        print(f"将写入(去重后): {len(writes)} 条")
        for xname, op_id, conf, note in writes:
            print(f"  {xname} -> op{op_id} ({conf}, {note})")

        if args.dry_run:
            print("(dry-run, 未写库)")
            return

        for xname, op_id, conf, note in writes:
            conn.execute("""
                INSERT INTO factor_operator_usage (xname, op_id, op_role, use_count, note)
                VALUES (?, ?, 'operator_application', 1, ?)
                ON CONFLICT(xname, op_id, op_role) DO UPDATE SET use_count = use_count + 1
            """, (xname, op_id, f"confidence={conf};{note}"))
            # operator_chain 同步
            row = conn.execute("SELECT operator_chain FROM factors WHERE xname=?", (xname,)).fetchone()
            try:
                chain = json.loads(row[0]) if row and row[0] else []
            except (TypeError, json.JSONDecodeError):
                chain = []
            if op_id not in chain:
                chain = sorted(set(chain) | {op_id})
                conn.execute("UPDATE factors SET operator_chain=? WHERE xname=?",
                             (json.dumps(chain), xname))
        print(f"已写入 {len(writes)} 条绑定")


if __name__ == "__main__":
    main()
