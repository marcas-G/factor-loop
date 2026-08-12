#!/usr/bin/env python3
"""R3 · search_factor_realizations — 新算子/新测量是否已被因子库实际实现过?(换皮检测)

被 S3.4 reduction-critic 调用。6 通道并行,合并去重,多通道加权判 disguise。

通道:
  semantic   measurement_question → factors_vec ANN(bge-small-zh 语义)
  structural template_hash 精确撞 + primitives 集合 Jaccard 相似度
  field      field_signature 交集(factor_structure)
  operator   factor_operator_usage(待建,先 stub)
  lineage    iterations 链(待库有数据)
  dead_end   lessons_fts(待库有数据)

判据:
  - 任一通道命中 dead_end → 警告(可能重蹈覆辙)
  - 多通道一致指向同一因子 + 语义近 → DISGUISE
  - 仅语义近但结构不同 → REDUCIBLE_TO_EXISTING(同族)
  - 全通道无强命中 → NOVEL

输入灵活(支持三种入口):
  query_text:  measurement_question 或新因子 formula(必填,语义查询锚)
  xname:       已有因子 xname(若查"这个因子撞了谁",用它当锚)
  params_text: 预期 formula(可选,structural 通道用)

返回 Contract Schema(见设计文档 R3):
  realization_verdict, channels{}, nearest_existing, cross_channel_agreement, disguise_check
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# 离线模式(与 gen_embeddings.py 一致,避免 HF hub 检查)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db

DB_PATH = str(Path(__file__).resolve().parents[2] / "factors.db")
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

# 通道权重(多通道聚合时,加权得分)
CHANNEL_WEIGHTS = {
    "semantic": 1.0,    # 语义近 = 最强换皮信号
    "structural": 0.8,  # template_hash 撞 = 强
    "field": 0.4,       # field 交集 = 弱(同字段族常见)
    "operator": 0.6,    # operator 共用 = 中
    "lineage": 0.9,     # lineage 链 = 强(已知迭代)
    "dead_end": 1.0,    # dead_end 命中 = 最强警告
}

# 阈值
SEMANTIC_NEAR = 0.15    # cosine dist < 此 = 语义近(同族候选)
SEMANTIC_VERY = 0.08    # < 此 = 极近(疑似换皮)
JACCARD_NEAR = 0.6      # primitives Jaccard > 此 = 结构近


def _embed(text: str):
    """文本 → 512 维归一化向量。延迟加载模型。"""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(DEFAULT_MODEL, device="cpu")
    return model.encode(text, normalize_embeddings=True).tolist()


def _primitives_jaccard(a: dict, b: dict) -> float:
    """两因子 operator_primitives 的 Jaccard 相似度(集合交/并)。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _field_overlap(a: dict, b: dict) -> float:
    """两因子 field_signature 的交集比例(相对小的)。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _channel_semantic(conn, query_vec, top_k=8) -> list:
    """semantic 通道:factors_vec ANN(cosine distance)。"""
    vec_json = json.dumps(query_vec)
    rows = conn.execute("""
        SELECT xname, vec_distance_cosine(embedding, ?) AS dist
        FROM factors_vec
        ORDER BY dist
        LIMIT ?
    """, (vec_json, top_k)).fetchall()
    return [{"xname": r[0], "score": round(1.0 - r[1], 4), "dist": round(r[1], 4)} for r in rows]


def _channel_structural(conn, candidate_primitives: dict | None,
                        candidate_template_hash: str | None, top_k=8) -> list:
    """structural 通道:template_hash 精确撞 + primitives Jaccard。"""
    results = []
    # 1) template_hash 精确撞(若给了候选 hash)
    if candidate_template_hash:
        rows = conn.execute("""
            SELECT xname, template_hash FROM factor_structure
            WHERE template_hash = ? AND xname != ?
        """, (candidate_template_hash, "")).fetchall()
        for r in rows:
            results.append({"xname": r[0], "score": 1.0, "match_type": "template_hash_exact"})
    # 2) primitives Jaccard(若给了候选 primitives)
    if candidate_primitives is not None:
        all_fs = conn.execute(
            "SELECT xname, operator_primitives FROM factor_structure"
        ).fetchall()
        scored = []
        for r in all_fs:
            xn, prims_json = r[0], r[1]
            try:
                prims = json.loads(prims_json) if prims_json else {}
            except Exception:
                prims = {}
            j = _primitives_jaccard(candidate_primitives, prims)
            if j > 0:
                scored.append((xn, j))
        scored.sort(key=lambda x: -x[1])
        for xn, j in scored[:top_k]:
            results.append({"xname": xn, "score": round(j, 4), "match_type": "primitives_jaccard"})
    return results


def _channel_field(conn, candidate_fields: dict | None, top_k=8) -> list:
    """field 通道:field_signature 交集比例。"""
    if candidate_fields is None:
        return []
    results = []
    all_fs = conn.execute("SELECT xname, field_signature FROM factor_structure").fetchall()
    scored = []
    for r in all_fs:
        try:
            fs = json.loads(r[1]) if r[1] else {}
        except Exception:
            fs = {}
        ov = _field_overlap(candidate_fields, fs)
        if ov > 0:
            scored.append((r[0], ov))
    scored.sort(key=lambda x: -x[1])
    for xn, ov in scored[:top_k]:
        results.append({"xname": xn, "score": round(ov, 4)})
    return results


def _channel_dead_end(conn, query_text: str, top_k=5) -> list:
    """dead_end 通道:lessons_fts 搜失败方向。"""
    if not query_text or len(query_text) < 3:
        return []
    # trigram FTS,取关键词
    results = []
    try:
        rows = conn.execute("""
            SELECT l.id, l.text, l.factor_xname, bm25(lessons_fts) AS rank
            FROM lessons_fts
            JOIN lessons l ON l.rowid = lessons_fts.rowid
            WHERE lessons_fts MATCH ? AND l.type='dead_end'
            ORDER BY rank LIMIT ?
        """, (query_text[:100], top_k)).fetchall()
        for r in rows:
            results.append({"lesson_id": r[0], "text": r[1][:120], "factor_xname": r[2]})
    except Exception:
        pass  # FTS 异常静默(无 dead_end 数据时正常)
    return results


def _channel_lineage(conn, candidate_xname: str | None, top_k=5) -> list:
    """lineage 通道:iterations 链(若给了候选 xname,看它的迭代亲缘)。"""
    if not candidate_xname:
        return []
    results = []
    try:
        rows = conn.execute("""
            SELECT from_xname, to_xname, change_note, icir_delta
            FROM iterations
            WHERE from_xname=? OR to_xname=?
            LIMIT ?
        """, (candidate_xname, candidate_xname, top_k)).fetchall()
        for r in rows:
            other = r[1] if r[0] == candidate_xname else r[0]
            results.append({"xname": other, "change_note": r[2], "icir_delta": r[3]})
    except Exception:
        pass
    return results


def search_factor_realizations(
    query_text: str | None = None,
    *,
    xname: str | None = None,
    candidate_formula: str | None = None,
    top_k: int = 8,
    conn=None,
) -> dict:
    """R3 主入口。返回 Contract Schema。

    三种入口:
      - query_text: measurement_question 或新因子 formula(语义查询锚)
      - xname: 已入库因子(用它自己的 anchor 当锚,查"撞了谁")
      - candidate_formula: 预期 formula(structural/field 通道候选)
    """
    import sqlite3
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            import sqlite_vec
            sqlite_vec.load(conn)
        except ImportError:
            pass

    try:
        # ── 确定语义锚 ──────────────────────────────────────────
        if xname:
            anchor = conn.execute(
                "SELECT anchor_text FROM factors WHERE xname=?", (xname,)
            ).fetchone()
            if not anchor or not anchor[0]:
                return {"error": f"xname={xname} 无 anchor_text"}
            query_vec = _embed(anchor[0])
            query_text_used = anchor[0]
        elif query_text:
            query_vec = _embed(query_text)
            query_text_used = query_text
        else:
            return {"error": "需提供 query_text 或 xname"}

        # ── 候选 structural/field 特征(若有 candidate_formula)──
        from core.retrieval.factor_structure_extractor import formula_hashes, scan_field_signature
        cand_prims = None
        cand_fields = None
        cand_template_hash = None
        if candidate_formula:
            _, _, cand_template_hash = formula_hashes(candidate_formula)
            cand_fields = scan_field_signature(candidate_formula)
        elif xname:
            # 用 xname 自己的 structure 当候选
            fs = conn.execute(
                "SELECT operator_primitives, field_signature, template_hash FROM factor_structure WHERE xname=?",
                (xname,)
            ).fetchone()
            if fs:
                try:
                    cand_prims = json.loads(fs[0]) if fs[0] else {}
                except Exception:
                    pass
                try:
                    cand_fields = json.loads(fs[1]) if fs[1] else {}
                except Exception:
                    pass
                cand_template_hash = fs[2]

        # ── 6 通道并行(已实现的 4 + 2 stub)────────────────────
        channels = {}
        channels["semantic"] = _channel_semantic(conn, query_vec, top_k)
        channels["structural"] = _channel_structural(conn, cand_prims, cand_template_hash, top_k)
        channels["field"] = _channel_field(conn, cand_fields, top_k)
        channels["operator"] = []  # 待 factor_operator_usage 建表
        channels["lineage"] = _channel_lineage(conn, xname)
        channels["dead_end"] = _channel_dead_end(conn, query_text_used)

        # ── 跨通道聚合:每个因子被几个通道指向 ─────────────────
        xname_channels = defaultdict(list)  # xname -> [(channel, score)]
        for ch, hits in channels.items():
            for h in hits:
                xn = h.get("xname")
                if xn and xn != xname:  # 排除自己
                    xname_channels[xn].append((ch, h["score"]))

        # 加权综合分
        agg = []
        for xn, chs in xname_channels.items():
            total = sum(CHANNEL_WEIGHTS.get(c, 0.3) * s for c, s in chs)
            n_channels = len(chs)
            agg.append({
                "xname": xn,
                "weighted_score": round(total, 4),
                "n_channels": n_channels,
                "channels": [{"channel": c, "score": s} for c, s in chs],
            })
        agg.sort(key=lambda x: (-x["n_channels"], -x["weighted_score"]))

        # ── 判决 ────────────────────────────────────────────────
        nearest = agg[0] if agg else None
        semantic_nearest = channels["semantic"][0] if channels["semantic"] else None
        # 排除自己后的 semantic 最近
        semantic_others = [s for s in channels["semantic"] if s["xname"] != xname]
        sem_nearest_other = semantic_others[0] if semantic_others else None

        # disguise 判:多通道一致 + 语义极近
        is_disguise = False
        disguise_reason = ""
        if nearest and nearest["n_channels"] >= 2:
            is_disguise = True
            disguise_reason = f"{nearest['n_channels']} 通道一致指向 {nearest['xname']}"
        elif sem_nearest_other and sem_nearest_other["dist"] < SEMANTIC_VERY:
            is_disguise = True
            disguise_reason = f"semantic 极近(dist={sem_nearest_other['dist']}) {sem_nearest_other['xname']}"

        # verdict
        if not agg and not sem_nearest_other:
            verdict = "NOVEL"
        elif is_disguise:
            verdict = "DISGUISE"
        elif sem_nearest_other and sem_nearest_other["dist"] < SEMANTIC_NEAR:
            verdict = "REDUCIBLE_TO_EXISTING"
        else:
            verdict = "NOVEL"  # 通道命中弱

        # dead_end 警告
        dead_end_warning = None
        if channels["dead_end"]:
            dead_end_warning = f"{len(channels['dead_end'])} 条 dead_end 命中,可能重蹈覆辙"

        # coverage 报告
        lib_total = conn.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
        vec_total = conn.execute("SELECT COUNT(*) FROM factors_vec").fetchone()[0]
        struct_total = conn.execute("SELECT COUNT(*) FROM factor_structure").fetchone()[0]

        return {
            "realization_verdict": verdict,
            "channels": channels,
            "aggregated": agg,
            "nearest_existing": nearest["xname"] if nearest else None,
            "cross_channel_agreement": nearest["n_channels"] if nearest else 0,
            "disguise_check": {
                "is_disguise": is_disguise,
                "reason": disguise_reason,
            },
            "semantic_nearest_other": (
                {"xname": sem_nearest_other["xname"], "dist": sem_nearest_other["dist"]}
                if sem_nearest_other else None
            ),
            "dead_end_warning": dead_end_warning,
            "coverage": {
                "factors_total": lib_total,
                "factors_vec_total": vec_total,
                "factor_structure_total": struct_total,
                "channels_active": [c for c, v in channels.items() if v],
                "channels_empty": [c for c, v in channels.items() if not v],
            },
        }
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="R3 search_factor_realizations")
    ap.add_argument("--query", help="measurement_question 或 formula")
    ap.add_argument("--xname", help="已有因子 xname(查撞了谁)")
    ap.add_argument("--formula", help="候选 formula(structural/field 通道)")
    args = ap.parse_args()

    if not args.query and not args.xname:
        ap.error("需 --query 或 --xname")

    result = search_factor_realizations(
        query_text=args.query, xname=args.xname, candidate_formula=args.formula
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
