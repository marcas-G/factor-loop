#!/usr/bin/env python3
"""派生表写入/聚合 — R1/R2/R3/R4 检索 Contract 的数据填充路径。

4 张派生表的维护:
  1. factor_evidence_rollup      factor_ic_daily → 场景聚合(FULL/RECENT)
  2. factor_research_state       ideas/iterations/lessons → 因子研究态聚合 + 增量更新
  3. factor_operator_usage       factor_structure.primitives → operator 映射(operators 有数据时)
  4. operator_capability_index   operators → capability 字段(需外部填, 提供骨架)

调用时机:
  - rebuild_all(conn)     全量重建(库初始化后 / 定期)
  - record_cognitive_attempt(conn, xname, outcome)  认知协议每次产出后增量更新 research_state
  - record_factor_evaluated(conn, xname)            assess 入库后增量更新 evidence_rollup
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db


# ═══════════════════════════════════════════════════════════════════════
# 1. factor_evidence_rollup — factor_ic_daily → 场景聚合
# ═══════════════════════════════════════════════════════════════════════
def _rollup_scene(rows: list, slice_type: str, slice_key: str | None) -> dict | None:
    """把一组逐日 IC 聚合成一条 rollup。"""
    ics = [r["ic"] for r in rows if r["ic"] is not None]
    if not ics:
        return None
    n = len(ics)
    mean = sum(ics) / n
    var = sum((x - mean) ** 2 for x in ics) / n if n > 1 else 0.0
    std = var ** 0.5
    icir = mean / std if std > 1e-9 else None
    srt = sorted(ics)
    pos = sum(1 for x in ics if x > 0) / n
    median = srt[n // 2]
    q10 = srt[max(0, int(n * 0.1) - 1)]
    q90 = srt[min(n - 1, int(n * 0.9))]
    dates = sorted(r["date"] for r in rows if r["date"])
    return {
        "n": n, "ic_mean": round(mean, 6), "ic_std": round(std, 6),
        "icir": round(icir, 4) if icir is not None else None,
        "positive_ratio": round(pos, 4), "ic_median": round(median, 6),
        "ic_q10": round(q10, 6), "ic_q90": round(q90, 6),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "slice_type": slice_type, "slice_key": slice_key,
    }


def rebuild_evidence_rollup(conn) -> int:
    """全量重建 factor_evidence_rollup(从 factor_ic_daily)。
    每个 (factor_xname, symbol, freq, y_horizon) 产一条 FULL。返回写入条数。"""
    scenes = conn.execute("""
        SELECT DISTINCT factor_xname, symbol, freq, y_horizon
        FROM factor_ic_daily
    """).fetchall()
    # 清空重建(幂等)
    conn.execute("DELETE FROM factor_evidence_rollup")
    written = 0
    for sc in scenes:
        xn, sym, freq, hz = sc
        rows = conn.execute("""
            SELECT date, ic FROM factor_ic_daily
            WHERE factor_xname=? AND symbol=? AND freq=? AND y_horizon=?
            ORDER BY date
        """, (xn, sym, freq, hz)).fetchall()
        if not rows:
            continue
        # FULL slice
        r = _rollup_scene(rows, "FULL", None)
        if r:
            conn.execute("""
                INSERT INTO factor_evidence_rollup
                (factor_xname, symbol, freq, y_horizon, slice_type, slice_key,
                 n, ic_mean, ic_std, icir, positive_ratio, ic_median, ic_q10, ic_q90,
                 start_date, end_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (xn, sym, freq, hz, r["slice_type"], r["slice_key"], r["n"],
                  r["ic_mean"], r["ic_std"], r["icir"], r["positive_ratio"],
                  r["ic_median"], r["ic_q10"], r["ic_q90"],
                  r["start_date"], r["end_date"]))
            written += 1
    return written


# ═══════════════════════════════════════════════════════════════════════
# 2. factor_research_state — ideas/iterations/lessons → 研究态聚合
# ═══════════════════════════════════════════════════════════════════════
# 认知协议 outcome → research_state 计数列映射
_OUTCOME_TO_COL = {
    "NEW_OPERATOR": ("operator_gap_count", "new_operator_count"),
    "FACTOR_ITERATION": ("factor_iteration_count", None),
    "INSUFFICIENT": ("insufficient_count", None),
    "CONSISTENT": ("consistent_count", None),
    "OOD": ("out_of_domain_count", None),
    "CONTRADICTS": ("contradicticts_count", None),
}

# exhaustion_score 计算:基于研究次数 + dead_end 比例的启发式
def _exhaustion_score(times_selected, cognitive_attempts,
                      dead_end_children, total_children) -> float:
    """研究耗尽度启发(0-1):被选多 + 子代 dead_end 多 → 高耗尽。"""
    sel_factor = min(1.0, times_selected / 10.0)  # 10 次选满 → 1.0
    child_factor = 0.0
    if total_children > 0:
        child_factor = dead_end_children / total_children
    attempt_factor = min(1.0, cognitive_attempts / 20.0)  # 20 次认知尝试 → 1.0
    # 加权:子代 dead_end 占比最重(真耗尽信号),其次次数
    score = 0.4 * child_factor + 0.35 * sel_factor + 0.25 * attempt_factor
    return round(min(1.0, score), 4)


def rebuild_research_state(conn) -> int:
    """全量重建 factor_research_state(从 ideas/iterations/lessons 聚合)。
    每个因子一行。返回写入条数。"""
    factors = conn.execute(
        "SELECT xname FROM factors WHERE deprecated_at IS NULL"
    ).fetchall()
    # 保留已有 times_selected/last_selected_ts(rebuild 不清这两个,只重算聚合)
    written = 0
    for (xn,) in factors:
        _upsert_research_state(conn, xn, recompute_exhaustion=True)
        written += 1
    return written


def _upsert_research_state(conn, xname: str, recompute_exhaustion: bool = True):
    """更新单因子 research_state(从源表重算聚合列,保留 times_selected)。"""
    # 读已有
    existing = conn.execute(
        "SELECT times_selected, last_selected_ts FROM factor_research_state WHERE xname=?",
        (xname,)
    ).fetchone()
    times_sel = existing[0] if existing else 0
    last_sel = existing[1] if existing else None

    # 聚合:作为 from 的迭代(success/declined)
    iter_rows = conn.execute("""
        SELECT outcome, status FROM iterations WHERE from_xname=?
    """, (xname,)).fetchall()
    successful_child = sum(1 for r in iter_rows if r[0] == "improved")
    dead_end_child = sum(1 for r in iter_rows if r[0] == "declined")
    total_child = len(iter_rows)
    factor_iter = sum(1 for r in iter_rows if r[1] == "realized")

    # dead_end lessons
    de_lessons = conn.execute(
        "SELECT COUNT(*) FROM lessons WHERE factor_xname=? AND type='dead_end' AND deprecated_at IS NULL",
        (xname,)
    ).fetchone()[0]

    # open ideas(挂在该因子)
    try:
        open_ideas = conn.execute("""
            SELECT COUNT(*) FROM idea_factor_links ifl
            JOIN ideas i ON i.id=ifl.idea_id
            WHERE ifl.factor_xname=? AND i.status='open'
        """, (xname,)).fetchone()[0]
    except Exception:
        open_ideas = 0

    exhaustion = _exhaustion_score(times_sel, 0, dead_end_child, total_child) if recompute_exhaustion else 0.0
    # 注:cognitive_attempts/outcome 由 record_cognitive_attempt 增量维护,rebuild 不覆盖

    conn.execute("""
        INSERT INTO factor_research_state
        (xname, times_selected, last_selected_ts,
         successful_child_count, dead_end_child_count, open_idea_count,
         factor_iteration_count, research_exhaustion_score)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(xname) DO UPDATE SET
            times_selected=excluded.times_selected,
            last_selected_ts=excluded.last_selected_ts,
            successful_child_count=excluded.successful_child_count,
            dead_end_child_count=excluded.dead_end_child_count,
            open_idea_count=excluded.open_idea_count,
            factor_iteration_count=excluded.factor_iteration_count,
            research_exhaustion_score=excluded.research_exhaustion_score,
            last_updated_ts=CURRENT_TIMESTAMP
    """, (xname, times_sel, last_sel, successful_child, dead_end_child,
          open_ideas, factor_iter, exhaustion))


def record_cognitive_attempt(conn, xname: str, outcome: str):
    """认知协议每次产出后增量更新 research_state。

    outcome: NEW_OPERATOR / FACTOR_ITERATION / INSUFFICIENT / CONSISTENT / OOD / CONTRADICTS
    """
    # 确保有行
    _upsert_research_state(conn, xname, recompute_exhaustion=False)
    # 更新 attempts + 对应 outcome 列
    conn.execute("""
        UPDATE factor_research_state SET
            cognitive_attempts = cognitive_attempts + 1,
            last_outcome = ?,
            last_updated_ts = CURRENT_TIMESTAMP
        WHERE xname=?
    """, (outcome, xname))
    cols = _OUTCOME_TO_COL.get(outcome)
    if cols:
        for col in cols:
            if col:
                conn.execute(
                    f"UPDATE factor_research_state SET {col}={col}+1 WHERE xname=?",
                    (xname,)
                )
    # 重算 exhaustion(用新 cognitive_attempts)
    row = conn.execute("""
        SELECT times_selected, cognitive_attempts, dead_end_child_count,
               (successful_child_count + dead_end_child_count) AS total
        FROM factor_research_state WHERE xname=?
    """, (xname,)).fetchone()
    if row:
        exh = _exhaustion_score(row[0], row[1], row[2], row[3])
        conn.execute(
            "UPDATE factor_research_state SET research_exhaustion_score=? WHERE xname=?",
            (exh, xname)
        )


def mark_research_object_selected(conn, xname: str):
    """R1 选中某因子后调用:times_selected++ + last_selected_ts=now。"""
    _upsert_research_state(conn, xname, recompute_exhaustion=False)
    conn.execute("""
        UPDATE factor_research_state SET
            times_selected = times_selected + 1,
            last_selected_ts = CURRENT_TIMESTAMP,
            last_updated_ts = CURRENT_TIMESTAMP
        WHERE xname=?
    """, (xname,))


# ═══════════════════════════════════════════════════════════════════════
# 3. factor_operator_usage — factor_structure.primitives → operator 映射
# ═══════════════════════════════════════════════════════════════════════
def rebuild_operator_usage(conn) -> int:
    """从 factor_structure.operator_primitives 反推因子用到的算子。
    operators 表空 → 无法映射(跳过)。有算子时,按 primitives 名模糊匹配 operators.name。
    返回写入条数(粗映射,后续 agent 可精修)。"""
    op_count = conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0]
    if op_count == 0:
        return 0  # 无算子,无法映射
    # 读所有算子名
    ops = {row[1]: row[0] for row in conn.execute("SELECT op_id, name FROM operators").fetchall()}
    written = 0
    conn.execute("DELETE FROM factor_operator_usage")
    for fs in conn.execute("SELECT xname, operator_primitives FROM factor_structure").fetchall():
        xn = fs[0]
        try:
            prims = json.loads(fs[1]) if fs[1] else {}
        except Exception:
            continue
        for prim_name, count in prims.items():
            # 模糊匹配:primitive 名 ∈ operator 名(或反之)
            matched_op_id = None
            for op_name, op_id in ops.items():
                if prim_name in op_name or op_name in prim_name:
                    matched_op_id = op_id
                    break
            if matched_op_id:
                conn.execute("""
                    INSERT OR IGNORE INTO factor_operator_usage (xname, op_id, op_role, use_count)
                    VALUES (?,?,?,?)
                """, (xn, matched_op_id, "primitive:" + prim_name, count))
                written += 1
    return written


# ═══════════════════════════════════════════════════════════════════════
# 4. operator_capability_index — operators → capability(骨架)
# ═══════════════════════════════════════════════════════════════════════
def update_operator_capability(conn, op_id: int, capability: dict):
    """手动/agent 填某算子的 capability 字段(operators 表有算子后调)。

    capability dict keys: carrier_type, measurement_object, measurement_property,
    input_role_signature(list), output_role, temporal_requirement,
    observable_requirements(list), invariance(dict), embedding(list[768])
    """
    op_name = conn.execute("SELECT name FROM operators WHERE op_id=?", (op_id,)).fetchone()
    if not op_name:
        raise ValueError(f"op_id={op_id} 不在 operators 表")
    conn.execute("""
        INSERT INTO operator_capability_index
        (op_id, op_name, carrier_type, measurement_object, measurement_property,
         input_role_signature, output_role, temporal_requirement,
         cross_section_requirement, pair_requirement, observable_requirements, invariance)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(op_id) DO UPDATE SET
            op_name=excluded.op_name, carrier_type=excluded.carrier_type,
            measurement_object=excluded.measurement_object,
            measurement_property=excluded.measurement_property,
            input_role_signature=excluded.input_role_signature,
            output_role=excluded.output_role,
            temporal_requirement=excluded.temporal_requirement,
            cross_section_requirement=excluded.cross_section_requirement,
            pair_requirement=excluded.pair_requirement,
            observable_requirements=excluded.observable_requirements,
            invariance=excluded.invariance,
            updated_ts=CURRENT_TIMESTAMP
    """, (
        op_id, op_name[0],
        capability.get("carrier_type"),
        capability.get("measurement_object"),
        capability.get("measurement_property"),
        json.dumps(capability.get("input_role_signature"), ensure_ascii=False) if capability.get("input_role_signature") else None,
        capability.get("output_role"),
        capability.get("temporal_requirement"),
        capability.get("cross_section_requirement"),
        capability.get("pair_requirement"),
        json.dumps(capability.get("observable_requirements"), ensure_ascii=False) if capability.get("observable_requirements") else None,
        json.dumps(capability.get("invariance"), ensure_ascii=False) if capability.get("invariance") else None,
    ))
    # 写 vec(若有 embedding)
    emb = capability.get("embedding")
    if emb:
        try:
            conn.execute("DELETE FROM operator_capability_vec WHERE op_id=?", (op_id,))
            conn.execute(
                "INSERT INTO operator_capability_vec (op_id, embedding) VALUES (?,?)",
                (op_id, json.dumps(emb))
            )
        except sqlite3.OperationalError:
            pass  # vec 表不可用


# ═══════════════════════════════════════════════════════════════════════
# 全量重建
# ═══════════════════════════════════════════════════════════════════════
def rebuild_all(conn) -> dict:
    """全量重建所有派生表(库初始化后 / 定期维护)。返回各表写入数。"""
    return {
        "evidence_rollup": rebuild_evidence_rollup(conn),
        "research_state": rebuild_research_state(conn),
        "operator_usage": rebuild_operator_usage(conn),
        # operator_capability_index 不自动重建(需 agent 填)
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="派生表维护")
    ap.add_argument("--rebuild", action="store_true", help="全量重建")
    ap.add_argument("--record-attempt", nargs=2, metavar=("XNAME", "OUTCOME"),
                    help="记录一次认知协议产出")
    ap.add_argument("--mark-selected", metavar="XNAME", help="标记因子被 R1 选中")
    args = ap.parse_args()

    with db.get_conn() as conn:
        if args.rebuild:
            r = rebuild_all(conn)
            print("rebuild:", r)
        if args.record_attempt:
            record_cognitive_attempt(conn, args.record_attempt[0], args.record_attempt[1])
            print(f"recorded: {args.record_attempt}")
        if args.mark_selected:
            mark_research_object_selected(conn, args.mark_selected)
            print(f"marked selected: {args.mark_selected}")
