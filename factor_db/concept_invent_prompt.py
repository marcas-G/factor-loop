#!/usr/bin/env python3
"""概念发明器：现象卡 → 新测量问题（LLM 层）。

只接收：
  - 匿名现象卡（inventor_view，无因子名/机制词/方向词）
  - 数据能力声明（可观测/不可观测）
  - 问题注册表（已批注问题空间，防旧问题重提）

禁止：输出公式、修改已有算子、使用买卖方向概念。
输出：候选测量问题（每卡最多 3 个），含 latent_construct + direction_property。

LLM 调用留钩子（llm()），默认打印提示词到 stdout——骨架阶段由主会话
用 Skill/Agent 完成 LLM 层，结果回填。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DATA_CAPABILITIES = {
    "frequency": "500ms_snapshot",
    "feeds": ["AG_MAIN", "AG_NEXT", "CU_MAIN", "CU_NEXT"],
    "observable": [
        "bid_ask_prices", "multi_level_depth", "midprice", "spread",
        "snapshot_differences", "directional_flow_proxies", "daily_ic_vectors",
    ],
    "unobservable": [
        "individual_order_identity", "exact_add_cancel_trade_sequence",
        "queue_position", "true_order_event_time", "real_intervention",
    ],
}

INVENTOR_PROMPT = """你是盘口测量概念发明器。目标：提出当前算子语言中不存在的测量问题。

输入：
1. 现象卡（匿名，不含因子名/机制词/买卖方向词）
2. 数据能力声明（哪些可观测、哪些不可观测）
3. 问题注册表（已问过的问题空间——你的问题必须在其之外）

规则：
- 禁止输出公式，禁止修改已有算子，禁止引用已有算子名
- 概念必须方向中性（INVARIANT 不变量 / EQUIVARIANT 等变量 / PAIRED 双分量）
- 概念必须能解释现象卡中的不可区分性/分歧
- 概念必须允许多个数值实现（不是单公式命名）
- 不预设答案（不要说"需要容量归一化"等已有变换）

现象卡：
{card}

数据能力声明：
{data}

问题注册表（问题族摘要）：
{registry_summary}

输出 JSON 数组（最多 3 个候选）：
[
  {{
    "measurement_question": "…",       # 动词开头的测量问题
    "latent_construct": "…",           # 潜在量命名
    "why_needed": "…",                 # 该概念为何解释卡中现象
    "direction_property": "INVARIANT|EQUIVARIANT|PAIRED",
    "expected_distinction": "…",       # 期望区分卡中哪两类
    "falsification": ["…"],            # 若成立应观察到什么，否则拒绝
    "candidate_implementations": ["…", "…"]  # ≥2 种估计思路（描述，非公式）
  }}
]
只输出 JSON，不要其他文字。"""


def registry_summary(registry_path=None):
    """注册表 → 问题族摘要（供发明器防旧问题）。"""
    path = Path(registry_path or ROOT / "concept_cards" / "question_registry.json")
    if not path.exists():
        return "（注册表未生成）"
    reg = json.loads(path.read_text())
    lines = []
    for r in reg:
        fam = r["family"]
        q = r.get("measurement_question") or "待批注"
        if r.get("measured_object") or r.get("question_form"):
            lines.append(f"- {fam} ({r['n_factors']}因子): {q} [obj={r.get('measured_object')}, form={r.get('question_form')}]")
        else:
            lines.append(f"- {fam} ({r['n_factors']}因子): 待批注")
    return "\n".join(lines)


def build_prompt(card: dict, registry_path=None) -> str:
    """组装发明器提示词。card = 现象卡的 inventor_view。"""
    return INVENTOR_PROMPT.format(
        card=json.dumps(card, ensure_ascii=False, indent=1),
        data=json.dumps(DATA_CAPABILITIES, ensure_ascii=False, indent=1),
        registry_summary=registry_summary(registry_path),
    )


def llm(prompt: str) -> list:
    """LLM 调用钩子（骨架）：打印提示词，返回空列表——由主会话接 Agent/Skill 补全。"""
    print("=" * 70)
    print("概念发明器提示词（LLM 层待接入）:")
    print("=" * 70)
    print(prompt)
    return []


def invent(card_id: str, registry_path=None, dry_run=True) -> list:
    """入口：从 cards/ 读卡 → 提示词 → LLM → 候选问题列表。"""
    card_path = ROOT / "concept_cards" / "cards" / f"{card_id}.json"
    if not card_path.exists():
        raise FileNotFoundError(f"卡不存在: {card_path}")
    card = json.loads(card_path.read_text())
    inv = card["inventor_view"]
    prompt = build_prompt(inv, registry_path)
    if dry_run:
        llm(prompt)
        return []
    # 非 dry_run：调用真实 LLM（骨架未接，抛未实现）
    raise NotImplementedError("LLM 层未接入——用 dry_run=True 看提示词，或接 Skill/Agent")


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else "PH_SCALE_IMB_FAMILY"
    invent(cid, dry_run=True)
