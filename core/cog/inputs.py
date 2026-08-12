#!/usr/bin/env python3
"""cog-protocol 数据输入 CLI —— 纯数据层,跑一次输出 representation + N dead_end JSON。

不调 LLM。供 cog-protocol skill 用 Bash 调用取输入:
  python core/cog/inputs.py --seed 42 --n 5

observation_view 的保守抽取(从 text 分离事实 vs 解释)由 skill 主会话(Claude)做,
不在此处——那是认知任务,该由 Claude 执行,不是 python 规则。

输出 JSON:
{
  "representation": {representation_semantics, implementation_examples},
  "deadends": [{id, xname, type, text, evidence, _preextracted:{observed_metrics, interpretation}}]
}
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # factor-autoloop 根
sys.path.insert(0, str(ROOT))
from core.cog import representation  # noqa: E402

DB = ROOT / "factors.db"


def _parse_evidence(raw) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def classify_type(ev: dict, text: str = "") -> str:
    """icir>1 且 weakness 含共线/冗余 → REDUNDANT_REJECT;icir<0.5 → NO_SIGNAL;else OTHER。"""
    icir = (ev or {}).get("icir") or 0
    blob = " ".join((ev or {}).get("weaknesses") or []) + " " + (text or "")
    if any(k in blob for k in ("共线", "冗余", "撞", "残差")) and icir > 1:
        return "REDUNDANT_REJECT"
    if icir < 0.5:
        return "NO_SIGNAL"
    return "OTHER"


def _seg(text: str, key: str):
    """从半模板 text 抽某段(历史解释侧,规则抽够)。"""
    m = re.search(
        rf"{key}\s*[：:]\s*(.+?)(?=\n(?:主要失败原因|弱项|建议迭代|假设|X-Y|deep|可证伪)|$)",
        text, re.S)
    return m.group(1).strip()[:200] if m else None


def select(conn, n: int, seed: int) -> list:
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM lessons WHERE type='dead_end' ORDER BY id").fetchall()]
    rng = random.Random(seed)
    chosen = rng.sample(ids, min(n, len(ids)))
    ph = ",".join("?" * len(chosen))
    rows = conn.execute(
        f"SELECT id, factor_xname, text, evidence FROM lessons WHERE id IN ({ph})",
        chosen).fetchall()
    order = {iid: k for k, iid in enumerate(chosen)}
    rows.sort(key=lambda r: order.get(r[0], 0))
    out = []
    for r in rows:
        ev = _parse_evidence(r[3])
        out.append({
            "id": r[0], "xname": r[1], "type": classify_type(ev, r[2] or ""),
            "text": r[2], "evidence": ev,
            "_preextracted": {
                "observed_metrics": {"icir": ev.get("icir"), "ic_mean": ev.get("ic_mean")},
                "interpretation": {
                    "previous_hypothesis": _seg(r[2] or "", "假设"),
                    "suggested_fix": _seg(r[2] or "", "建议迭代"),
                    "suggested_operator": r[1],
                },
            },
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="cog-protocol 数据输入")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    try:
        rep = representation.build_representation(conn)
        des = select(conn, args.n, args.seed)
    finally:
        conn.close()
    print(json.dumps({"representation": rep, "deadends": des}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
