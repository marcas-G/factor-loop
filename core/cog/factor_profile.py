#!/usr/bin/env python3
"""Factor Research Object Adapter — Factor Profile 严格三视图分区。

Research Object = Factor。对象统一,但信息视图隔离(防 evidence leakage):
- construction_view: formula/operator_chain/bindings/params(客观构造)
- evidence_view:     horizon/feed/bucket/regime profile + siblings + lessons
- provenance:        字段来源 + isolation_guarantee 声明

A_F = g(Construction(F))。assumption agent 只收 construction_view;
adjudicator 才收 assumption + evidence_view。orchestrator 负责视图分派。

字段集不相交:construction_view ∩ evidence_view = ∅。
"""
import json
import sqlite3
from collections import defaultdict

DB = "/home/lgao/work/factor-autoloop/factors.db"


def _parse_json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def build_factor_profile(conn, xname):
    """返回 {identity, construction_view, evidence_view, provenance}。找不到返回 None。"""
    row = conn.execute("""
        SELECT xname, class_name, file_path, formula_text, operator_chain,
               field_bindings, params, angle_code, status, quality_grade,
               latest_ic, latest_icir, latest_sharpe, latest_rank_ic, intuition
        FROM factors WHERE xname=?
    """, (xname,)).fetchone()
    if not row:
        return None
    (xn, cls, fpath, formula, op_chain, bindings, params,
     angle, status, grade, lic, licir, lsharpe, lrank_ic, _intuition) = row

    # ── Construction View(assumption 唯一输入)──
    # 不含 intuition(解释侧)、不含 latest_ic/icir(evidence)。
    # 不预填 "preserved/discarded"(那是 assumption agent 的产物)。
    construction_view = {
        "formula_text": formula,
        "operator_chain": _parse_json(op_chain),
        "field_bindings": _parse_json(bindings),
        "params": _parse_json(params) or {},
    }

    # ── Evidence View(adjudicator 才用)──
    ic_rows = conn.execute("""
        SELECT freq, y_horizon, COUNT(*), AVG(ic), MIN(ic), MAX(ic)
        FROM factor_ic_daily
        WHERE factor_xname=? AND symbol='SHFE-AG'
        GROUP BY freq, y_horizon
        ORDER BY freq, y_horizon
    """, (xn,)).fetchall()
    horizon_profile = []
    feed_profile = defaultdict(dict)
    for freq, h, n, avg, mn, mx in ic_rows:
        if freq and "sub" in freq:
            feed = "sub"
        elif freq and "main" in freq:
            feed = "main"
        else:
            feed = freq or "default"
        rec = {
            "feed": feed, "horizon": h, "n_days": n,
            "avg_ic": round(avg, 4) if avg is not None else None,
            "min_ic": round(mn, 4) if mn is not None else None,
            "max_ic": round(mx, 4) if mx is not None else None,
        }
        horizon_profile.append(rec)
        feed_profile[feed][h] = rec["avg_ic"]

    lessons = conn.execute("""
        SELECT id, type, text, evidence FROM lessons
        WHERE factor_xname=? AND deprecated_at IS NULL
        ORDER BY id
    """, (xn,)).fetchall()
    lessons_ev = [{
        "id": l[0], "type": l[1],
        "text": (l[2] or "")[:200],
        "evidence": _parse_json(l[3]),
    } for l in lessons]

    siblings = []
    if angle:
        sib_rows = conn.execute("""
            SELECT xname, latest_icir, latest_ic, substr(formula_text,1,140)
            FROM factors
            WHERE angle_code=? AND xname!=? AND status='evaluated'
              AND deprecated_at IS NULL
            ORDER BY latest_icir DESC NULLS LAST LIMIT 8
        """, (angle, xn)).fetchall()
        for s in sib_rows:
            siblings.append({
                "xname": s[0],
                "icir": round(s[1], 2) if s[1] is not None else None,
                "ic": round(s[2], 4) if s[2] is not None else None,
                "formula_excerpt": s[3],
                # attribution_strength 由 adjudicator/orchestrator 判(看 changed_axes)
            })

    evidence_view = {
        "horizon_profile": horizon_profile,
        "feed_profile": {k: dict(v) for k, v in feed_profile.items()},
        "bucket_profile": None,      # 需 .xy 缓存,dry-run 先不聚合
        "regime_profile": None,
        "residual": None,
        "siblings": siblings,
        "iterations": [l for l in lessons_ev if l["type"] == "iteration"],
        "lessons": lessons_ev,
        "status": status,
        "latest_metrics": {
            "ic": lic, "icir": licir, "sharpe": lsharpe, "rank_ic": lrank_ic,
        },
    }

    return {
        "identity": {
            "xname": xn, "class_name": cls, "file_path": fpath,
            "angle_code": angle, "status": status, "quality_grade": grade,
        },
        "construction_view": construction_view,
        "evidence_view": evidence_view,
        "provenance": {
            "construction_sources": [
                "factors.formula_text", "factors.operator_chain",
                "factors.field_bindings", "factors.params",
            ],
            "evidence_sources": [
                "factor_ic_daily", "lessons", "siblings(angle_code)",
            ],
            "adapter_version": "factor_research_object_adapter_v0",
            "isolation_guarantee": (
                "construction_view ∩ evidence_view = ∅; "
                "A_F=g(Construction(F)) enforced by orchestrator view dispatch; "
                "assumption agent receives construction_view ONLY."
            ),
        },
    }


def slice_construction(profile):
    """orchestrator 用:只取 construction_view(喂 assumption agent)。"""
    return {
        "identity": profile["identity"],
        "construction_view": profile["construction_view"],
        "provenance_view_slice": "construction_only",
    }


def slice_evidence(profile):
    """orchestrator 用:只取 evidence_view(喂 adjudicator,与 assumption 配对)。"""
    return {
        "identity": profile["identity"],
        "evidence_view": profile["evidence_view"],
        "provenance_view_slice": "evidence_only",
    }


if __name__ == "__main__":
    import sys
    xn = sys.argv[1] if len(sys.argv) > 1 else "ImbalanceBase"
    conn = sqlite3.connect(DB)
    prof = build_factor_profile(conn, xn)
    conn.close()
    if prof is None:
        print(f"NOT FOUND: {xn}")
        sys.exit(1)
    print(json.dumps(prof, ensure_ascii=False, indent=1))
