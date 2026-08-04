#!/usr/bin/env python3
"""算子编译器：测量契约 → ≤2 个实现 + swap 变体。

约束（最小实现门）：
  - 每契约 ≤2 个实现（第一轮 1 个主实现 + 1 个对照，不扫参数）
  - 固定参数 1 组，禁止窗口/阈值/档位自动遍历
  - 每个实现生成 原版 + swap 变体（买卖互换，验证方向性质）
  - 禁止依赖不可观测数据（order_identity / event_time / intervention）

输出：实现描述 JSON（因子 xname 规划 + 公式草图 + swap 对），
      .h 生成由 write-factor Skill/手动完成（骨架阶段）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# swap 命名后缀
SWAP_SUFFIX = "_sw"


def check_observability(construct: dict, data_capabilities: dict) -> dict:
    """契约依赖是否可观测。"""
    text = json.dumps(construct, ensure_ascii=False).lower()
    unobs = data_capabilities.get("unobservable", [])
    hits = [u for u in unobs if u.replace("_", " ") in text or u in text]
    if hits:
        return {"ok": False, "hits": hits, "note": f"契约依赖不可观测数据 {hits}"}
    return {"ok": True, "hits": [], "note": "可观测"}


def plan_implementations(candidate: dict, max_impl: int = 2) -> dict:
    """把候选的 candidate_implementations 前 max_impl 条转成实现规划。"""
    impls = candidate.get("candidate_implementations") or []
    if not impls:
        return {"ok": False, "note": "候选无实现描述"}
    base = candidate.get("latent_construct", "construct")
    plan = []
    for i, desc in enumerate(impls[:max_impl]):
        xname = f"{base.capitalize()[:24]}{'A' if i == 0 else 'B'}"
        plan.append({
            "xname": xname,
            "impl_index": i,
            "implementation_desc": desc,
            "swap_xname": xname + SWAP_SUFFIX,
            "params": {"fixed": True, "note": "1 组固定参数，禁止扫描"},
        })
    return {"ok": True, "plan": plan}


def build_contract(candidate: dict) -> dict:
    """测量契约文档：批评器通过后的契约化输出。"""
    return {
        "measurement_question": candidate.get("measurement_question"),
        "latent_construct": candidate.get("latent_construct"),
        "direction_property": candidate.get("direction_property"),
        "expected_distinction": candidate.get("expected_distinction"),
        "falsification": candidate.get("falsification"),
        "data_dependencies": candidate.get("candidate_implementations"),
    }


def compile_contract(candidate: dict, max_impl: int = 2) -> dict:
    """主入口：契约 + 可观测性检查 + 实现规划。"""
    contract = build_contract(candidate)
    obs = check_observability(contract, {
        "unobservable": ["order_identity", "order_event_time", "intervention_model",
                         "queue_position", "true_order_event_time"],
    })
    if not obs["ok"]:
        return {"ok": False, "contract": contract, "observability": obs}
    plan = plan_implementations(candidate, max_impl)
    if not plan["ok"]:
        return {"ok": False, "contract": contract, "observability": obs}
    return {"ok": True, "contract": contract, "observability": obs, **plan}


if __name__ == "__main__":
    # 干跑：一个方向可控性类契约
    demo = {
        "measurement_question": "推动中间价向上/向下移动一个tick，所需的最小方向净流是多少?",
        "latent_construct": "directional_control_cost",
        "direction_property": "EQUIVARIANT",
        "expected_distinction": "同压力不同未来：控制成本差",
        "falsification": ["与静态深度/OFI 完全等价则拒"],
        "candidate_implementations": [
            "状态分组的双向条件冲击弹性比（局部回归查表）",
            "状态未变期间累计方向净流密度（预算消耗）",
        ],
    }
    print(json.dumps(compile_contract(demo), ensure_ascii=False, indent=1))
