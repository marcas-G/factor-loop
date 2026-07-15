"""归纳引擎任务生成器:状态(覆盖空白 + archived 变异)→ 扫描任务。

纵向核心:让搜索状态驱动任务(不靠人决定扫什么)。三个任务源:
  1. 覆盖空白:pattern_dims 的 S 词表 - pattern_coverage 已扫 = 没扫的 S 结构 → 该加 detector(横向)
  2. 变异候选:archived 卡 → 邻域(换 H/换 S)→ 待验证任务(验证需 detector 定向,后续)
  3. feed 队列:archived 高优先 → hypothesis-generator 解释(衔接①)

输出任务报告,驱动下一轮扫描方向。这是状态→任务的确定性映射(蓝图 task_generator 的骨架)。

用法:python factor_db/gen_tasks.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db

HORIZONS = [1, 5, 10, 60, 300]


def coverage_gaps(conn):
    all_s = [r[0] for r in conn.execute("SELECT value FROM pattern_dims WHERE dim='S' ORDER BY value").fetchall()]
    scanned_s = [r[0] for r in conn.execute("SELECT DISTINCT s_structure FROM pattern_coverage").fetchall()]
    return all_s, scanned_s, [s for s in all_s if s not in scanned_s]


def mutation_candidates(conn, top_n=5):
    """archived 卡 → 变异候选(换 H / 换 S 结构)。变体验证需 detector 定向(后续)。"""
    archived = [dict(r) for r in conn.execute(
        "SELECT id,f_feature,s_structure,h_horizon FROM pattern_cards WHERE status='archived' ORDER BY priority DESC LIMIT ?",
        (top_n,),
    ).fetchall()]
    all_s = [r[0] for r in conn.execute("SELECT value FROM pattern_dims WHERE dim='S'").fetchall()]
    cands = []
    for c in archived:
        for h in HORIZONS:
            if h != c["h_horizon"]:
                cands.append({"from": c["id"], "f": c["f_feature"], "change": f"h {c['h_horizon']}→{h}", "s": c["s_structure"], "h": h})
        for s in all_s:
            if s != c["s_structure"]:
                cands.append({"from": c["id"], "f": c["f_feature"], "change": f"S {c['s_structure']}→{s}", "s": s, "h": c["h_horizon"]})
    return cands[:20]


def main():
    ap = argparse.ArgumentParser(description="任务生成器(状态→任务)")
    ap.add_argument("--db", default=str(db.DB_PATH))
    args = ap.parse_args()
    with db.get_conn(args.db) as conn:
        all_s, scanned_s, unscanned = coverage_gaps(conn)
        muts = mutation_candidates(conn)
        feed = [dict(r) for r in conn.execute(
            "SELECT id,f_feature,s_structure,h_horizon,priority FROM pattern_cards "
            "WHERE status='archived' AND idea_id IS NULL ORDER BY priority DESC LIMIT 3"
        ).fetchall()]
        archived_n = conn.execute("SELECT COUNT(*) FROM pattern_cards WHERE status='archived'").fetchone()[0]
        deprecated_n = conn.execute("SELECT COUNT(*) FROM pattern_cards WHERE status='deprecated'").fetchone()[0]
    print("=== 任务生成器(状态 → 任务)===")
    print(f"模式库: archived {archived_n} / deprecated {deprecated_n}")
    print(f"\n[任务源1 · 覆盖空白] S 结构已扫({len(scanned_s)}): {scanned_s}")
    print(f"[任务源1 · 覆盖空白] S 结构未扫({len(unscanned)}): {unscanned}")
    print("  → 驱动:加未扫 S 的 detector(横向扩 S)或换数据源扫这些结构")
    print(f"\n[任务源2 · 变异候选] archived→邻域(前 {len(muts)}):")
    for m in muts[:10]:
        print(f"  from id={m['from']}  {m['f']:24}  {m['change']}")
    print("  → 验证需 detector 定向(当前全扫,变体多已覆盖;定向验证=后续)")
    print(f"\n[任务源3 · feed 队列] 待 hypothesis-generator 解释(衔接①):")
    for f in feed:
        print(f"  id={f['id']}  {f['f_feature']:24}  {f['s_structure']:22}  h={f['h_horizon']}s  priority={f['priority']:.3f}")


if __name__ == "__main__":
    main()
