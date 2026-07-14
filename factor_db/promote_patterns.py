"""归纳引擎:audited 模式卡 → archived(promote + 算 priority + 自动喂队列)。

promote:status audited→archived,算 priority = |strength| × confidence 权重
  (verified×1.0 / preview×0.5 / weak×0.2)—— 强效应 + 高置信 优先喂 hypothesis-generator。
去重:同 7 维坐标已 archived 则跳过(detect 幂等已保证坐标唯一);同结构不同特征的深层冗余待因子层。

feed_queue:拉 archived 且 idea_id IS NULL 的高优先模式卡,供 hypothesis-generator 解释(衔接① 归纳→演绎)。
hypothesis-generator 拉队列 → 解释模式卡的机制(F 为何在 S 结构下预测 Y)→ 产 idea → 回写 idea_id + status='explained'。

用法:python factor_db/promote_patterns.py [--feed-n 3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_db import db

CONF_WEIGHT = {"verified": 1.0, "preview": 0.5, "weak": 0.2}


def promote(conn) -> int:
    audited = [dict(r) for r in conn.execute("SELECT * FROM pattern_cards WHERE status='audited'").fetchall()]
    n = 0
    for c in audited:
        ar = json.loads(c["audit_result"]) if c["audit_result"] else {}
        conf = ar.get("confidence", "preview")
        priority = abs(c["strength"] or 0) * CONF_WEIGHT.get(conf, 0.5)
        conn.execute(
            "UPDATE pattern_cards SET status='archived', priority=? WHERE id=?",
            (priority, c["id"]),
        )
        n += 1
    return n


def feed_queue(conn, top_n: int = 3) -> list[dict]:
    """拉 archived 高优先 + 未解释的模式卡,供 hypothesis-generator 解释。"""
    return [dict(r) for r in conn.execute(
        """SELECT id,f_feature,t_transform,c_condition,s_structure,y_target,h_horizon,r_reference,
                  strength,priority
           FROM pattern_cards
           WHERE status='archived' AND idea_id IS NULL
           ORDER BY priority DESC LIMIT ?""",
        (top_n,),
    ).fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="audited→archived promote + 自动喂队列")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--feed-n", type=int, default=3, help="打印 feed 队列前 N 个")
    args = ap.parse_args()
    with db.get_conn(args.db) as conn:
        n = promote(conn)
        dist = conn.execute("SELECT status, COUNT(*) FROM pattern_cards GROUP BY status").fetchall()
        feed = feed_queue(conn, args.feed_n)
    print(f"promote {n} audited → archived")
    for r in dist:
        print(f"  {r[0]}: {r[1]}")
    print(f"\n自动喂队列(archived 高优先,待 hypothesis-generator 解释)前 {len(feed)}:")
    for c in feed:
        cond = json.loads(c["c_condition"]) if c["c_condition"] else None
        print(f"  [id={c['id']}] {c['f_feature']:26} {c['t_transform']:12} {c['s_structure']:14} "
              f"h={c['h_horizon']:>3}s Y={c['y_target']:12} priority={c['priority']:.3f} cond={cond}")


if __name__ == "__main__":
    main()
