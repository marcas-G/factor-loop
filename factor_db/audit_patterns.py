"""归纳引擎审计器:raw 模式卡 → audited / deprecated。

适配 lens_predictive 的定位(快速预览,默认 5 天 daily IC):
  - 否决项:样本量不足 / 多重检验后 |spearman| 不显著(扫 N 组合挑出的要更强)
  - n_days 不否决,而是 confidence 标注:verified(>=20天)/ preview(1-19)/ weak(0)
    lens_predictive 5 天 → confidence=preview(效应存在,长期稳健性待后续跨样本复验)
  - 可交易性/泄漏:模式卡层证据不足,标"待因子层"(不在此否决)

通过 → status='audited' + confidence;不通过 → status='deprecated'。

用法:python factor_db/audit_patterns.py
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

MIN_N = 1000
MIN_ABS_SPEARMAN = 0.05       # 多重检验近似:扫 230 组合挑出的要 |spearman| 够强
MIN_DAYS_VERIFIED = 20        # confidence=verified 阈值(不否决,只标注)


def audit_card(card: dict) -> dict:
    ev = json.loads(card.get("evidence") or "{}")
    reasons = []
    n_samples = card.get("n_samples")
    if n_samples is not None and n_samples < MIN_N:
        reasons.append(f"样本不足 n={n_samples}<{MIN_N}")
    abs_sp = abs(card.get("strength") or 0)            # strength = spearman
    if abs_sp < MIN_ABS_SPEARMAN:
        reasons.append(f"多重检验后 |spearman|={abs_sp:.3f}<{MIN_ABS_SPEARMAN}")
    n_days = ev.get("n_days", 0)
    confidence = "verified" if n_days >= MIN_DAYS_VERIFIED else ("preview" if n_days > 0 else "weak")
    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "confidence": confidence,
        "checks": {
            "n_samples": card.get("n_samples"), "n_days": n_days,
            "abs_spearman": round(abs_sp, 4), "abs_icir": round(abs(card.get("significance") or 0), 3),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="审计 raw 模式卡")
    ap.add_argument("--db", default=str(db.DB_PATH))
    args = ap.parse_args()
    with db.get_conn(args.db) as conn:
        raws = [dict(r) for r in conn.execute("SELECT * FROM pattern_cards WHERE status='raw'").fetchall()]
        audited_n = deprecated_n = 0
        for c in raws:
            res = audit_card(c)
            new_status = "audited" if res["passed"] else "deprecated"
            conn.execute(
                "UPDATE pattern_cards SET status=?, audit_result=? WHERE id=?",
                (new_status, json.dumps(res, ensure_ascii=False), c["id"]),
            )
            if res["passed"]:
                audited_n += 1
            else:
                deprecated_n += 1
        dist = conn.execute("SELECT status, COUNT(*) FROM pattern_cards GROUP BY status").fetchall()
    print(f"审计 {len(raws)} raw 卡 → audited {audited_n} / deprecated {deprecated_n}")
    for r in dist:
        print(f"  {r[0]}: {r[1]}")
    with db.get_conn(args.db) as conn:
        au = [dict(r) for r in conn.execute(
            "SELECT f_feature,h_horizon,strength,audit_result FROM pattern_cards "
            "WHERE status='audited' ORDER BY ABS(strength) DESC LIMIT 5"
        ).fetchall()]
        confs = {}
        for c in au:
            cf = json.loads(c["audit_result"]).get("confidence")
            confs[cf] = confs.get(cf, 0) + 1
        print(f"  audited confidence 分布: {confs}")
        for c in au:
            ar = json.loads(c["audit_result"])
            print(f"  ✓ {c['f_feature']:28} h={c['h_horizon']:>3}s "
                  f"spearman={c['strength']:+.4f} confidence={ar['confidence']}")


if __name__ == "__main__":
    main()
