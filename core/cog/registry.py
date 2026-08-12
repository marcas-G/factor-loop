"""question_registry 加载与摘要(后置判重用)。

registry 是已批注的问题空间(46 个 family),供 Operator Question 生成**之后**做
判重(NEW/SEMANTIC_DUPLICATE/REFINEMENT/RECOORDINATION)——创造与判重分离,
生成时不喂 registry,防 LLM 被旧问题空间锚定。
"""
import json
from pathlib import Path

REG_PATH = Path(__file__).resolve().parents[0] / "question_registry.json"


def load_registry() -> list:
    """加载 question_registry.json。缺失返回 []。"""
    if not REG_PATH.exists():
        return []
    return json.loads(REG_PATH.read_text(encoding="utf-8"))


def registry_summary(max_families: int = 46) -> str:
    """registry → 问题族摘要(供后置判重 prompt 用,不喂生成阶段)。

    只给 family / n_factors / measurement_question / measured_object —— 够判重,
    不给 formula_snippet(防锚定实现)。
    """
    reg = load_registry()
    if not reg:
        return "(question_registry 未生成)"
    lines = []
    for r in reg[:max_families]:
        fam = r.get("family", "?")
        n = r.get("n_factors", 0)
        q = r.get("measurement_question") or "待批注"
        obj = r.get("measured_object") or ""
        obj_str = f" [obj={obj}]" if obj else ""
        lines.append(f"- {r.get('question_id', '?')} {fam} (n={n}): {q}{obj_str}")
    return "\n".join(lines)
