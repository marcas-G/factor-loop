"""必然假设生成机论证链工具(吸收 runtime/mcp/tools/hypothesis-chain.mjs)。"""
import json

from core.db import db


def persist_argument_chain(text: str, argument_chain: dict, parent_idea_id: int = None,
                           necessity_grade: str = None, angle_code: str = None) -> dict:
    """必然假设生成机:写一条假设 + 结构化论证链到 ideas 表。携带论证链(Σ/超加性耦合/唯一性证明/竞争解释/可证伪痕迹),区别于 persist_idea 的纯文本。论证链是假设的属性,不是因子的属性。"""
    with db.get_conn() as conn:
        idea_id = db.add_hypothesis(
            conn, text, argument_chain,
            parent_idea_id=parent_idea_id, necessity_grade=necessity_grade, angle_code=angle_code,
        )
    return {"idea_id": idea_id}


def hypothesis_get(idea_id: int) -> dict:
    """读假设的论证链 + 支持度。reviewer-agent 对抗审稿、忠实度判定(因子实现是否忠于论证链)时读用。argument_chain 自动从 JSON 反序列化。"""
    with db.get_conn() as conn:
        row = db.get_hypothesis(conn, idea_id)
    if not row:
        return {"ok": False, "error": f"idea_id 不存在: {idea_id}"}
    chain = None
    if row["argument_chain"]:
        try:
            chain = json.loads(row["argument_chain"])
        except (json.JSONDecodeError, TypeError):
            chain = row["argument_chain"]  # 反序列化失败保留原文
    return {
        "ok": True, "id": row["id"], "text": row["text"], "argument_chain": chain,
        "necessity_grade": row["necessity_grade"], "support_score": row["support_score"],
        "evaluated_factor_count": row["evaluated_factor_count"], "status": row["status"],
    }


TOOLS = [
    ("persist_argument_chain", persist_argument_chain),
    ("hypothesis_get", hypothesis_get),
]
