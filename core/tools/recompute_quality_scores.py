"""重新计算 evaluated 因子的 quality_score/grade(多指标聚合分)。

方案1(加权线性) + 固定阈值归一 + 方案4(等级):
  independence = residual_ic_strength(vs 库内基底残差,调 CLI 算 mean scenes)
  stability    = monthly_icir + signal_instability(deep_best,固定阈值归一)
  quality_score = 0.5×independence + 0.5×stability
  grade = A(≥0.7)/B(0.4-0.7)/C(<0.4)

ICIR 只作 Gate 门槛(evaluated=ICIR≥1.5 强信号),不进 score(边际递减)。

用法: /home/lgao/quant-venv/bin/python core/tools/recompute_quality_scores.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.db import db  # noqa: E402
from core.config import DB_PATH  # noqa: E402

PY = sys.executable  # 复用当前解释器(需 venv:residual_ic_strength 依赖 numpy)


def residual_mean(xname: str) -> float | None:
    """调 residual_ic_strength.py CLI 算 mean residual across scenes。"""
    r = subprocess.run(
        [PY, str(ROOT / "core" / "tools" / "residual_ic_strength.py"), "--target", xname],
        capture_output=True, text=True,
    )
    try:
        scenes = [s for s in json.loads(r.stdout).get("scenes", [])
                  if s.get("residual_ic_strength") is not None]
        return sum(s["residual_ic_strength"] for s in scenes) / len(scenes) if scenes else None
    except Exception:
        return None


def main() -> None:
    db_path = str(DB_PATH)
    with db.get_conn(db_path) as c:
        evaluated = [r[0] for r in c.execute(
            "SELECT xname FROM factors WHERE status='evaluated' AND deprecated_at IS NULL"
        ).fetchall()]
        print(f"重算 {len(evaluated)} 个 evaluated 因子的 quality_score...")
        dist = {"A": 0, "B": 0, "C": 0}
        no_resid = 0
        for i, xname in enumerate(evaluated, 1):
            ind = residual_mean(xname)
            if ind is None:
                no_resid += 1
            em_row = c.execute(
                "SELECT eval_metrics FROM factor_evals WHERE factor_xname=? ORDER BY ts DESC LIMIT 1",
                (xname,),
            ).fetchone()
            em = json.loads(em_row[0]) if em_row and em_row[0] else {}
            core = em.get("core_metrics", {})
            deep = em.get("deep_best", {})
            score, grade = db.quality_score_from_parts(
                ind,
                core.get("train_test"),                          # 样本稳定(防过拟合核心)
                deep.get("monthly_icir"),                        # 月度一致
                deep.get("signal_instability_pct"),              # 信号稳定
                (core.get("session_ic") or {}).get("std"),       # 跨时段 IC std
                (core.get("vol_regime") or {}).get("sign_consistent"),  # regime 鲁棒
            )
            c.execute(
                "UPDATE factors SET quality_score=?, quality_grade=? WHERE xname=?",
                (score, grade, xname),
            )
            dist[grade] += 1
            if i % 10 == 0:
                print(f"  ...{i}/{len(evaluated)}")
        print(f"\n完成。等级分布: A={dist['A']}  B={dist['B']}  C={dist['C']}  (residual算失败={no_resid})")


if __name__ == "__main__":
    main()
