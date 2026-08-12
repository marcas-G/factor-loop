#!/usr/bin/env python3
"""R2 · search_operator_closure — 当前 distinction 是否已在 N2 闭包内?

被 S2.6 minimal-repair-critic 调用。N2 闭包 = 标准静态统计 + operators 表已注册算子。

两阶段检索:
  ① SQL 硬过滤:temporal_requirement 兼容 + observable_requirements 包含 + carrier_type 兼容
  ② vec rerank:supported_distinction embedding → operator_capability_vec ANN
  ③ 附加内置 N1/N2 程序判定(linear/interaction/normalization/已有静态算子组合)

返回:
  closure_verdict: SUFFICIENT | NOT_SUFFICIENT | UNCERTAIN
  n1_raw_restoration / n2_standard_static: 程序判定候选
  matching_operators: SQL+vec 召回的算子(capability_match + how_it_expresses)
  remaining_structure: NOT_SUFFICIENT 时还差什么

operators 表空(库初始化态)→ 降级:matching_operators=[],closure_verdict 由 N1/N2 决定。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.db import db

DB_PATH = str(Path(__file__).resolve().parents[2] / "factors.db")
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

# ── 内置 N1/N2 标准闭包(程序常量,不入库)──────────────────────────────
# N1 = 恢复 raw 坐标(量级/各档 size/price level)
# N2 = 标准静态统计(linear/nonlinear/interaction/normalization/monotonic/spline/GLM)
N1_CAPABILITIES = {
    "raw_field_restoration": "恢复因子压缩时丢掉的原始坐标(量级/各档/价格 level)",
    "magnitude": "保留被归一化压掉的绝对量级",
    "per_level": "恢复被聚合掉的多档信息",
}
N2_CAPABILITIES = {
    "linear": "线性组合/加权",
    "nonlinear": "非线性变换(log/tanh/sigmoid/sqrt)",
    "interaction": "交互项(A*B / A/B / 条件)",
    "normalization": "归一化/标准化/分位 rank",
    "monotonic": "单调变换/sign/abs",
    "spline": "样条/分桶",
    "glm": "广义线性模型族",
}

# temporal 兼容矩阵:static ⊂ ordered ⊂ event_driven(后者能表达前者)
TEMPORAL_COMPAT = {
    "static": {"static"},
    "ordered": {"static", "ordered"},
    "cross_section": {"static", "cross_section"},
    "event_driven": {"static", "ordered", "event_driven", "cross_section"},
}


def _embed(text: str):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(DEFAULT_MODEL, device="cpu")
    return model.encode(text, normalize_embeddings=True).tolist()


def _temporal_compatible(required: str | None, op_temporal: str | None) -> bool:
    """op 的 temporal 能否表达 required 的 temporal。"""
    if not required or not op_temporal:
        return True  # 无约束 = 兼容
    compatible = TEMPORAL_COMPAT.get(required, {required})
    return op_temporal in compatible or op_temporal == required


def _observable_satisfied(required_obs: list, op_obs: list) -> bool:
    """op 的 observable 能力是否覆盖 required(⊇)。空 required = 无约束。"""
    if not required_obs:
        return True
    if not op_obs:
        return False  # op 无声明 = 不能硬过滤通过(保守)
    return set(required_obs).issubset(set(op_obs))


def _carrier_compatible(required_carrier: str | None, op_carrier: str | None) -> bool:
    """carrier_type 兼容(精确或 op 更通用)。无约束 = 通过。"""
    if not required_carrier or not op_carrier:
        return True
    return required_carrier == op_carrier or op_carrier == "any"


def _sql_filter(conn, temporal_req: str | None, observable_req: list,
                carrier_req: str | None) -> list:
    """阶段①:SQL 硬过滤 operator_capability_index。"""
    rows = conn.execute("""
        SELECT op_id, op_name, carrier_type, measurement_object, measurement_property,
               temporal_requirement, observable_requirements, input_role_signature
        FROM operator_capability_index
    """).fetchall()
    candidates = []
    for r in rows:
        op_obs = []
        try:
            op_obs = json.loads(r[6]) if r[6] else []
        except Exception:
            pass
        if not _temporal_compatible(temporal_req, r[5]):
            continue
        if not _observable_satisfied(observable_req, op_obs):
            continue
        if not _carrier_compatible(carrier_req, r[2]):
            continue
        candidates.append(dict(r))
    return candidates


def _vec_rerank(conn, candidates: list, query_vec, top_k: int) -> list:
    """阶段②:operator_capability_vec ANN rerank(用 capability_vec 而非 capability_index,后者无向量)。"""
    if not candidates or query_vec is None:
        return candidates
    op_ids = [c["op_id"] for c in candidates]
    if not op_ids:
        return []
    vec_json = json.dumps(query_vec)
    placeholders = ",".join("?" * len(op_ids))
    try:
        rows = conn.execute(f"""
            SELECT op_id, vec_distance_cosine(embedding, ?) AS dist
            FROM operator_capability_vec
            WHERE op_id IN ({placeholders})
            ORDER BY dist
        """, (vec_json, *op_ids)).fetchall()
        dist_map = {r[0]: r[1] for r in rows}
    except Exception:
        return candidates  # vec 表不可用 → 跳过 rerank
    for c in candidates:
        d = dist_map.get(c["op_id"])
        c["capability_match"] = round(1.0 - d, 4) if d is not None else None
        c["semantic_dist"] = round(d, 4) if d is not None else None
    candidates.sort(key=lambda x: x.get("semantic_dist") or 1.0)
    return candidates[:top_k]


def _n1_check(supported_distinction: str) -> dict:
    """N1 raw restoration 程序判定:distinction 是否仅需恢复原始坐标?
    粗启发:distinction 含"量级/绝对值/各档/level"词 → N1 可能够。"""
    if not supported_distinction:
        return {"applicable": False, "reason": "无 distinction 输入"}
    keywords = ["量级", "绝对值", "各档", "level", "magnitude", "原始", "未归一化"]
    hit = [k for k in keywords if k in supported_distinction]
    if hit:
        return {"applicable": True, "reason": f"distinction 含 N1 信号词 {hit}(建议 minimal-repair 确认)"}
    return {"applicable": False, "reason": "distinction 非明显 raw 坐标恢复类(程序无法判,留 agent)"}


def _n2_static_check(supported_distinction: str) -> dict:
    """N2 标准静态闭包程序判定:distinction 是否仅静态变换可表达?
    粗启发:distinction 含"差比/加权/交互/归一化/分位/log/sigmoid" → N2 可能够。
    含"时序/序列/动态/累积/转移/episode/phase" → N2 不够(需动态)。"""
    if not supported_distinction:
        return {"applicable": False, "which": [], "reason": "无 distinction"}
    static_kw = ["差比", "加权", "交互", "归一化", "分位", "log", "sigmoid", "tanh", "比", "差"]
    dynamic_kw = ["时序", "序列", "动态", "累积", "转移", "episode", "phase", "级联", "游程", "持续"]
    static_hit = [k for k in static_kw if k in supported_distinction]
    dynamic_hit = [k for k in dynamic_kw if k in supported_distinction]
    if dynamic_hit:
        return {"applicable": False, "which": [], "reason": f"含动态信号 {dynamic_hit} → N2 静态不够"}
    if static_hit:
        return {"applicable": True, "which": static_hit, "reason": f"含静态变换信号 {static_hit}"}
    return {"applicable": None, "which": [], "reason": "程序无法判(留 agent)"}


def search_operator_closure(
    supported_distinction: str,
    *,
    measurement_object: str | None = None,
    required_roles: list | None = None,
    observable_capabilities: list | None = None,
    temporal_requirement: str | None = None,
    carrier_type: str | None = None,
    top_k: int = 5,
    conn=None,
) -> dict:
    """R2 主入口。返回 closure_verdict + matching_operators + remaining_structure。"""
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
        # ── 阶段①:SQL 硬过滤 ───────────────────────────────────
        candidates = _sql_filter(conn, temporal_requirement, observable_capabilities or [], carrier_type)

        # ── 阶段②:vec rerank(supported_distinction embed)──────
        query_vec = None
        if supported_distinction:
            try:
                query_vec = _embed(supported_distinction)
            except Exception:
                pass
        candidates = _vec_rerank(conn, candidates, query_vec, top_k)

        # measurement_object 精确匹配加权(若给了)
        if measurement_object:
            for c in candidates:
                if c.get("measurement_object") == measurement_object:
                    c["object_exact_match"] = True

        # ── N1/N2 程序判定 ───────────────────────────────────────
        n1 = _n1_check(supported_distinction)
        n2 = _n2_static_check(supported_distinction)

        # ── closure_verdict ──────────────────────────────────────
        has_matching_op = bool(candidates)
        n2_sufficient = n2["applicable"] is True

        if n2_sufficient:
            verdict = "SUFFICIENT"
            reason = f"N2 标准静态闭包判定够({n2['which']})"
        elif has_matching_op:
            # 有算子召回但 N2 程序没说够 → UNCERTANT(让 agent 看算子能力判)
            verdict = "UNCERTAIN"
            reason = f"{len(candidates)} 算子召回,需 agent 判是否语义覆盖"
        elif n2["applicable"] is False and n1["applicable"] is False:
            # 程序判动态且无算子 → NOT_SUFFICIENT
            verdict = "NOT_SUFFICIENT"
            reason = f"动态 distinction 且无匹配算子({n2['reason']})"
        else:
            verdict = "UNCERTAIN"
            reason = "程序无法判(N1/N2 启发均无定论)"

        # coverage
        op_lib_total = conn.execute("SELECT COUNT(*) FROM operators").fetchone()[0]
        cap_index_total = conn.execute("SELECT COUNT(*) FROM operator_capability_index").fetchone()[0]

        return {
            "closure_verdict": verdict,
            "reason": reason,
            "n1_raw_restoration": n1,
            "n2_standard_static": n2,
            "matching_operators": [
                {
                    "op_id": c["op_id"],
                    "op_name": c.get("op_name"),
                    "carrier_type": c.get("carrier_type"),
                    "measurement_object": c.get("measurement_object"),
                    "measurement_property": c.get("measurement_property"),
                    "temporal_requirement": c.get("temporal_requirement"),
                    "capability_match": c.get("capability_match"),
                    "how_it_expresses": None,  # 留 agent 填(语义判断)
                } for c in candidates
            ],
            "remaining_structure": (
                supported_distinction if verdict == "NOT_SUFFICIENT" else None
            ),
            "coverage": {
                "operators_total": op_lib_total,
                "capability_index_total": cap_index_total,
                "sql_filtered": len(candidates),
                "vec_reranked": len(candidates),
                "vec_active": query_vec is not None,
            },
        }
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="R2 search_operator_closure")
    ap.add_argument("--distinction", required=True, help="supported_distinction(Layer1)")
    ap.add_argument("--object", help="measurement_object")
    ap.add_argument("--temporal", help="static/ordered/cross_section/event_driven")
    ap.add_argument("--carrier", help="carrier_type")
    args = ap.parse_args()
    r = search_operator_closure(
        args.distinction, measurement_object=args.object,
        temporal_requirement=args.temporal, carrier_type=args.carrier,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2))
