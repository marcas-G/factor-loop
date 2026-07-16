"""知识图自转循环调度器（外部骨架）。

graph-engine 的 LLM 推理在 Claude session 内执行（skill 直调 MCP + Task）。
本脚本是**外部调度器**：扫图的触发点 + 报告状态，供人 / cron / auto-loops.sh 决定
"下一轮该跑什么、要不要起 session 调 /graph-engine"。

不直接跑 LLM（run_one_round 留接口；真正推理靠 claude session 内的 graph-engine skill）。

用法:
  python factor_db/run_graph_loop.py             # 扫触发点 + 报告状态
  python factor_db/run_graph_loop.py --watch 60  # 每 60s 扫一次（cron 式，需外部起 session 跑 /graph-engine）
  python factor_db/run_graph_loop.py --quiet     # 只退出码（0=有触发点该跑，1=无触发点该停）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db


def scan_triggers(conn) -> list[dict]:
    """扫图结构特征，按优先级返回触发点队列（与 graph-engine G1 逻辑一致，纯 SQL）。

    优先级：1 未解矛盾 > 2 反例聚簇 > 3 链断点 > 4 正交缺口。
    """
    triggers: list[dict] = []

    # 优先级 1：未解矛盾（CONTRADICTS 无 resolved_by）
    for r in conn.execute(
        """SELECT ge.id AS edge_id, a.code AS axiom_code, a.statement,
                  ge.weight
           FROM graph_edges ge
           JOIN axioms a ON a.id = ge.to_id AND ge.to_table='axioms'
           WHERE ge.edge_type='CONTRADICTS'
             AND NOT ({db.graph_constants()['resolved_clause']})
           ORDER BY COALESCE(ge.weight,0) DESC LIMIT 5"""
    ).fetchall():
        triggers.append({
            "op": "resolve_contradiction", "priority": 1,
            "ref": {"edge_id": r["edge_id"], "axiom_code": r["axiom_code"]},
            "desc": f"矛盾 {r['axiom_code']}: {r['violation']}",
        })

    # 优先级 2：反例聚簇（REFUTES/SUPPORTS ≥3 指向同一 axioms/ideas）
    for r in conn.execute(
        """SELECT to_table, to_id, edge_type, COUNT(*) AS sz
           FROM graph_edges
           WHERE edge_type IN ('REFUTES','SUPPORTS') AND to_table IN ('axioms','ideas')
           GROUP BY to_table, to_id, edge_type HAVING sz >= 3
           ORDER BY sz DESC LIMIT 5"""
    ).fetchall():
        triggers.append({
            "op": "generalize_from_refutation", "priority": 2,
            "ref": {"target_table": r["to_table"], "target_id": r["to_id"], "edge_type": r["edge_type"]},
            "desc": f"反例聚簇 {r['to_table']}#{r['to_id']} ({r['edge_type']} ×{r['sz']})",
        })

    # 优先级 3/4（chain_gap / orthogonal）需遍历 ideas 判 argument_chain/INSTANTIATES 度数，
    # 较重，此处只做轻量提示（实际由 graph-engine G1 在 session 内用 get_subgraph/neighborhood 定位）
    derived_gaps = conn.execute(
        "SELECT COUNT(*) AS c FROM ideas WHERE node_layer='DERIVED' AND argument_chain IS NULL"
    ).fetchone()["c"]
    if derived_gaps:
        triggers.append({
            "op": "fill_chain_gap", "priority": 3,
            "ref": {"n_derived_without_chain": derived_gaps},
            "desc": f"{derived_gaps} 个 DERIVED 节点缺 argument_chain",
        })

    triggers.sort(key=lambda t: t["priority"])
    return triggers


def should_stop(conn, round_num: int, max_rounds: int, consecutive_fails: int) -> tuple[bool, str]:
    """停止条件（与 graph-engine/外部调度约定一致）。"""
    stats = db.graph_stats(conn)
    if round_num >= max_rounds:
        return True, f"达最大轮次 {max_rounds}"
    if consecutive_fails >= 5:
        return True, f"连续 {consecutive_fails} 次 reviewer fail"
    if stats["unresolved_contradictions"] == 0 and not scan_triggers(conn):
        return True, "无未解矛盾且无触发点——图推理链暂穷尽"
    return False, ""


def report(conn) -> dict:
    """图状态 + 触发点队列（打印/退出码用）。"""
    stats = db.graph_stats(conn)
    triggers = scan_triggers(conn)
    return {"stats": stats, "triggers": triggers,
            "n_triggers": len(triggers), "has_work": len(triggers) > 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", type=int, default=0,
                    help="循环扫描间隔秒（0=单次）。需外部起 claude session 跑 /graph-engine 才会真推进")
    ap.add_argument("--max-rounds", type=int, default=50)
    ap.add_argument("--quiet", action="store_true", help="只输出退出码：0=有触发点该跑，1=无该停")
    args = ap.parse_args()

    round_num = 0
    while True:
        with db.get_conn() as conn:
            db.ensure_graph_schema(conn)
            rep = report(conn)
        if args.quiet:
            sys.exit(0 if rep["has_work"] else 1)
        print(f"=== round {round_num} ===")
        print(f"stats: {json.dumps(rep['stats'], ensure_ascii=False)}")
        if rep["triggers"]:
            print(f"下一轮触发点（{rep['n_triggers']} 个，按优先级）:")
            for t in rep["triggers"]:
                print(f"  [P{t['priority']}] {t['op']}: {t['desc']}  ref={t['ref']}")
            print("\n→ 起 claude session 调 /graph-engine 推进（每轮解 1 个触发点）。")
        else:
            print("无触发点：图推理链暂穷尽。")
            if args.watch:
                break
            sys.exit(1)

        if not args.watch:
            break
        # watch 模式：定时扫 + 报告。真停止（连续 fail / 轮次上限）由 session 内 graph-engine 产出驱动；
        # 外部调度器看 has_work（无触发点即报告"该停/补燃料"）。
        round_num += 1
        if round_num >= args.max_rounds:
            print(f"达最大轮次 {args.max_rounds}，退出。")
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
