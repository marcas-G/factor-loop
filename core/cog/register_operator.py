#!/usr/bin/env python3
"""Operator 注册器 — 认知协议 operator contract → operators 表。

统一链路的回写环节: 认知协议 S3(Operator Invention 4 Gate)产出 operator contract,
**算子注册门槛 = 语义 4 Gate 过(合理的推断), 不受实证 ICIR 影响**。

算子=资产(语义层可复用测量方法), 因子=产品(实证验证)。
- 算子注册(operators 表): 4 Gate 过 → 立即注册(source='cog')
- 因子入库(factors 表): ICIR 达标(assess 管)
- 算子先沉淀, 因子实证后补 — 因子 ICIR 不达标不否定算子(可能是算子实现/基底选错)

source='cog' 区分认知协议产出的算子(严苛 4 Gate), 与历史 concept_invent/phase3_invent 区分。
"""
import json
import sqlite3
from datetime import datetime

import os; DB = str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "factors.db"))


def register_operator(conn, contract: dict, gates: dict = None, source_ref: str = "") -> dict:
    """注册 operator(语义 4 Gate 过即注册, 无 ICIR 门槛)。

    contract: 认知协议 10 字段 operator contract
              (name/measurement_question/input_slots/measured_object/output_semantics/
               temporal_form/statefulness/invariances/information_introduced/parameters/
               failure_conditions + implementation_spec/direction_property)
    gates: 4 Gate 通过记录 {G1, G2, G3, G4: "PASS"} — 供 source_ref 追溯
    source_ref: 来源(Research Object 因子名 / distinction id)
    返回: {ok, op_id?, reason, rejected_reason?}
    """
    name = contract.get("name")
    if not name:
        return {"ok": False, "reason": "contract 缺 name"}

    # 重名检查
    exists = conn.execute("SELECT op_id FROM operators WHERE name=?", (name,)).fetchone()
    if exists:
        return {"ok": False, "op_id": exists[0], "reason": f"同名算子已存在(op{exists[0]})"}

    # 构造记录: definition=measurement_question(测什么), abstract=implementation spec
    input_roles = json.dumps([s.get("semantic_role") for s in contract.get("input_slots", [])],
                             ensure_ascii=False)
    impl_spec = contract.get("implementation_spec", {})
    abstract = impl_spec.get("abstract_structure") or contract.get("measurement_question", "")
    direction = contract.get("direction_property", "INVARIANT")
    # source_ref: gates 摘要 + 来源
    if gates:
        gate_str = ",".join(f"{k}:{v}" for k, v in gates.items() if isinstance(v, str))
        source_ref = f"{source_ref} [{gate_str}]" if source_ref else gate_str

    cur = conn.execute("""
        INSERT INTO operators (name, definition, input_roles, abstract_structure,
                               direction_property, source, source_ref, created_ts)
        VALUES (?,?,?,?,?, 'cog', ?, ?)
    """, (
        name,
        contract.get("measurement_question", ""),
        input_roles,
        abstract,
        direction,
        source_ref,
        datetime.now().isoformat(),
    ))
    conn.commit()
    return {"ok": True, "op_id": cur.lastrowid,
            "reason": f"operator {name} 注册(op{cur.lastrowid}), source='cog', 语义 4 Gate 过"}


if __name__ == "__main__":
    import sys
    conn = sqlite3.connect(DB)
    # 自检: IntraEpisodePhaseLocator(4 Gate 过, ICIR≈0 — 应注册, 不受实证影响)
    contract = {"name": "IntraEpisodePhaseLocator",
                "measurement_question": "对状态序列可观测的样本, 在瞬时状态值被控制相同的前提下, 测量该样本所属的局部演化 episode 及其在 episode 内的相位位置所携带的额外区分信息",
                "input_slots": [{"semantic_role": "state_series", "required_type": "signed_scalar_series"}],
                "implementation_spec": {"abstract_structure": "episode 边界检测(onset/dissipation) + 跨事件状态机 + [onset,dissipation] 区间内归一化相位"},
                "direction_property": "INVARIANT"}
    gates = {"G1": "PASS", "G2": "PASS", "G3": "COMPLETE", "G4": "NEW+NOVEL"}
    r = register_operator(conn, contract, gates=gates, source_ref="BsiSizeLevelBareRank_w500-A3")
    print(f"[自检] IntraEpisodePhaseLocator(ICIR≈0 但 4 Gate 过) → {r}")
    if r.get("ok"):
        conn.execute("DELETE FROM operators WHERE op_id=?", (r["op_id"],))
        conn.commit()
        print("  (清理自检插入)")
    conn.close()
