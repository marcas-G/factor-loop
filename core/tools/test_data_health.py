"""数据健康检查:rank_ic 域 + 孤儿 + deepbest 完整性。防数据漂移。

对真实 factors.db 跑(数据健康,非 schema 结构):
  python core/tools/test_data_health.py

校验:
- rank_ic 域:abs(latest_rank_ic)>1 = 0(防 metrics 命名错配 rank_ic_max→rank_ic)
- 孤儿:graph_edges 白名单 + factor_evals/lessons/iterations/factor_tags + vec 引用完整(防删因子不级联)
- deepbest 完整性:近期 eval_metrics deepbest 全 None 比例(>50% 报警,factor_check deep 没产出)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.db import db  # noqa: E402

_NODE = ("axioms", "ideas", "factors", "lessons")


def test_rank_ic_domain():
    """latest_rank_ic 必在 [-1,1](Spearman 范围)。>1 是 metrics 命名错配。"""
    with db.get_conn() as c:
        rows = c.execute(
            "select xname, latest_rank_ic from factors where latest_rank_ic is not null and abs(latest_rank_ic)>1"
        ).fetchall()
        assert not rows, f"{len(rows)} 个因子 latest_rank_ic 超出 [-1,1]: {[r[0] for r in rows[:3]]}"


def test_no_orphans():
    """关键表引用完整性(防删因子不级联清)。"""
    with db.get_conn() as c:
        n = c.execute(
            f"select count(*) from graph_edges where from_table not in (?,?,?,?) or to_table not in (?,?,?,?)",
            _NODE * 2,
        ).fetchone()[0]
        assert n == 0, f"graph_edges {n} 条白名单外(from/to_table 不在 {_NODE})"
        checks = [
            ("factor_evals", "factor_xname not in (select xname from factors)"),
            ("lessons", "factor_xname not in (select xname from factors)"),
            ("factor_tags", "factor_xname not in (select xname from factors)"),
            ("iterations", "from_xname not in (select xname from factors) or to_xname not in (select xname from factors)"),
            ("factors_vec", "xname not in (select xname from factors)"),
            ("factor_ic_vec", "factor_xname not in (select xname from factors)"),
            ("factor_ic_vec_meta", "factor_xname not in (select xname from factors)"),
        ]
        for t, cond in checks:
            n = c.execute(f"select count(*) from {t} where {cond}").fetchone()[0]
            assert n == 0, f"{t} {n} 个孤儿(引用不存在的因子)"


def test_deepbest_completeness():
    """近期 eval_metrics deepbest 全 None 比例 <50%(防 factor_check deep 没产出)。"""
    with db.get_conn() as c:
        rows = c.execute(
            "select eval_metrics from factor_evals where ts > datetime('now','-7 days') and eval_metrics is not null"
        ).fetchall()
        if not rows:
            return  # 近期无评估,跳
        none_count = sum(
            1 for r in rows
            if not any(v is not None for v in (json.loads(r[0]).get("deep_best", {}) or {}).values())
        )
        ratio = none_count / len(rows)
        assert ratio < 0.5, (
            f"近期 deepbest 全 None 比例 {ratio:.0%}(>50%,factor_check deep 分析可能没产出)"
        )


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"✓ {t.__name__}")
    print(f"\n全部 {len(tests)} 项数据健康检查通过。")


if __name__ == "__main__":
    main()
