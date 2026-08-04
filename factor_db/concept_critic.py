#!/usr/bin/env python3
"""测量契约批评器：候选测量问题 → 保留/拒绝。

四检查（全部程序化，不依赖 LLM 判断好恶）：
  1. 问题级去重    — 候选 measured_object+question_form 是否已被注册表占用
  2. 概念不可约    — 候选 latent_construct 能否由已有概念经 单调变换/加权/平滑/差分/门控/累计 还原
  3. 多实现要求    — candidate_implementations ≥ 2 且实现思路不同（防单公式命名）
  4. 方向性质声明  — direction_property 必须合法且实现描述与之一致

输出：{question_id?, decision: ACCEPT|REJECT, checks: {...}, reasons: [...]}
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 概念不可约：这些词出现 → 可能是旧概念换名
REDUCIBLE_PATTERNS = [
    r"不平衡|imbalance", r"订单流|order.?flow|ofi", r"深度|depth",
    r"撤单|cancel", r"价差|spread", r"冲击|impact|kyle", r"恢复|recovery|refill",
    r"动量|momentum", r"反转|reversal", r"毒性|vpin|toxicity",
    r"持仓|oi|open.?interest", r"成交流|turnover|trade.?flow",
]

# 变换词：概念描述中出现 → 若只靠这些词定义，属可还原
TRANSFORM_WORDS = ["加权", "平滑", "差分", "门控", "累计", "单调", "rank", "zscore",
                   "标准化", "归一", "窗口", "threshold", "阈值"]

VALID_DIRECTION = {"INVARIANT", "EQUIVARIANT", "PAIRED"}


def check_question_novel(candidate: dict, registry_path=None) -> dict:
    """问题级去重：measured_object + question_form 五元组 vs 注册表。"""
    path = Path(registry_path or ROOT / "concept_cards" / "question_registry.json")
    if not path.exists():
        return {"novel": True, "dup_with": None, "note": "注册表未生成，跳过去重"}
    reg = json.loads(path.read_text())
    obj = (candidate.get("measured_object") or "").strip().lower()
    form = (candidate.get("question_form") or "").strip().lower()
    for r in reg:
        ro = (r.get("measured_object") or "").strip().lower()
        rf = (r.get("question_form") or "").strip().lower()
        if ro and ro == obj:
            return {"novel": False, "dup_with": r["family"], "note": f"measured_object '{obj}' 已被族 {r['family']} 占用"}
        if ro and obj and (ro in obj or obj in ro):
            return {"novel": False, "dup_with": r["family"], "note": f"measured_object '{obj}' 与族 {r['family']} 的 '{ro}' 近似"}
    return {"novel": True, "dup_with": None, "note": "通过"}


def check_irreducible(candidate: dict) -> dict:
    """概念不可约：描述中是否只有旧概念词 + 变换词。"""
    text = json.dumps(candidate, ensure_ascii=False).lower()
    construct = (candidate.get("latent_construct") or "").lower()
    # 若 latent_construct 本身就是旧概念词 → 换名
    for pat in REDUCIBLE_PATTERNS:
        if re.search(pat, construct):
            return {"irreducible": False, "reason": f"latent_construct 命中旧概念词 {pat}"}
    # 若描述除变换词外无实质内容 → 可还原
    stripped = re.sub(r"[a-z\s_\[\]\{\},.\"']", "", text)
    meaningful = [c for c in stripped if c not in "，。、（）():"]
    if len(meaningful) < 2 and text.count("transformation") < 1:
        return {"irreducible": False, "reason": "描述无可辨识的实质概念（只有变换/通用词）"}
    return {"irreducible": True, "reason": "通过"}


def check_multi_impl(candidate: dict) -> dict:
    """多实现：≥2 且描述不同。"""
    impls = candidate.get("candidate_implementations") or []
    if len(impls) < 2:
        return {"multi_impl": False, "reason": f"只有 {len(impls)} 个实现（需≥2，防单公式命名）"}
    # 实现去重：描述归一后是否重复
    norm = []
    for i in impls:
        n = re.sub(r"[^a-z0-9一-鿿]", "", str(i).lower())
        norm.append(n)
    if len(set(norm)) < 2:
        return {"multi_impl": False, "reason": "多个实现描述实质相同"}
    return {"multi_impl": True, "reason": "通过"}


def check_direction(candidate: dict) -> dict:
    """方向性质：声明合法 + 描述一致。"""
    prop = candidate.get("direction_property")
    if prop not in VALID_DIRECTION:
        return {"direction": False, "reason": f"direction_property={prop} 非法（需 {VALID_DIRECTION}）"}
    text = json.dumps(candidate, ensure_ascii=False).lower()
    if prop == "INVARIANT" and ("买" in text or "卖" in text or "buy" in text or "sell" in text):
        return {"direction": False, "reason": "声明 INVARIANT 但描述含方向词"}
    return {"direction": True, "reason": "通过"}


def review(candidate: dict, registry_path=None) -> dict:
    """批评器主入口：四检查 → decision。"""
    checks = {
        "question_novel": check_question_novel(candidate, registry_path),
        "irreducible": check_irreducible(candidate),
        "multi_impl": check_multi_impl(candidate),
        "direction": check_direction(candidate),
    }
    reasons = []
    for k, v in checks.items():
        if not v.get(list(v)[0] if isinstance(v, dict) else "novel", False):
            # 提取首个布尔判定字段
            bool_key = next((kk for kk, vv in v.items() if isinstance(vv, bool)), None)
            if bool_key and not v[bool_key]:
                reasons.append(f"{k}: {v.get('reason','')}")
    accept = len(reasons) == 0
    return {
        "decision": "ACCEPT" if accept else "REJECT",
        "checks": checks,
        "reasons": reasons,
    }


def _cli(candidate_json, registry_path=None):
    """CLI 入口：--candidate <JSON字符串或文件路径> → review 结果。"""
    cand = json.loads(candidate_json) if candidate_json.lstrip().startswith("{") \
        else json.loads(Path(candidate_json).read_text())
    return review(cand, registry_path)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="测量契约批评器: 四检查(问题去重/不可约/多实现/方向)")
    ap.add_argument("--candidate", type=str, help="候选 JSON 字符串或文件路径")
    ap.add_argument("--registry", type=str, default=None, help="注册表路径(默认 concept_cards/question_registry.json)")
    args = ap.parse_args()
    if args.candidate:
        print(json.dumps(_cli(args.candidate, args.registry), ensure_ascii=False, indent=1))
    else:
        # 干跑示例：一个"旧概念换名"候选应被拒，一个"新概念"候选应过
        fake_old = {
            "measurement_question": "测量订单流失衡有多强",
            "measured_object": "order_flow_imbalance",
            "question_form": "STATE_MAGNITUDE",
            "latent_construct": "order_flow_imbalance_strength",
            "candidate_implementations": ["用买卖量差", "用买卖量比"],
            "direction_property": "EQUIVARIANT",
        }
        fake_new = {
            "measurement_question": "维持当前中间价状态需要多少持续的资源输入?",
            "measured_object": "state_maintenance_burden",
            "question_form": "BUDGET_CONSUMPTION",
            "latent_construct": "state_maintenance_burden",
            "candidate_implementations": ["状态未变期间累计方向净流", "匹配状态下条件资源消耗密度", "状态退出前的持续投入强度"],
            "direction_property": "INVARIANT",
            "falsification": ["若与静态深度完全等价则拒"],
        }
        print("旧概念换名候选:", json.dumps(review(fake_old), ensure_ascii=False, indent=1))
        print()
        print("新概念候选:", json.dumps(review(fake_new), ensure_ascii=False, indent=1))
