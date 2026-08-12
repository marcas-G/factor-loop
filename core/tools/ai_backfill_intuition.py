"""AI 回填 factors.intuition(语义意图描述,embedding 主原料)。

只处理 factors.intuition IS NULL/空的因子。
- 读 formula_text + tags + angle 描述 → 调 LLM → 生成纯中文语义意图描述
- UPDATE factors SET intuition=...
- 不碰 formula/tags/.h(那些归 ai_backfill_factors.py 管)

幂等:intuition 非空跳过;--force 全部重生成。

用法:
    python factor_db/ai_backfill_intuition.py --dry-run
    python factor_db/ai_backfill_intuition.py --xname Foo
    python factor_db/ai_backfill_intuition.py --limit 5
    python factor_db/ai_backfill_intuition.py            # 全量缺的
    python factor_db/ai_backfill_intuition.py --force    # 全部重生成

依赖: pip install anthropic httpx; export ANTHROPIC_AUTH_TOKEN=xxx
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db

# GLM-5.1(大写:代理 claudeaggr 认;小写 glm-5.1 / 环境变量 SONNET 的值代理报 unknown provider)
DEFAULT_MODEL = "GLM-5.1"

SYSTEM_PROMPT = """你是量化微观结构因子语义分析专家。给你一个因子的公式/代码、标签、信息角度,输出一段纯中文的**语义意图描述**(80-150 字),用于语义检索 embedding。

严格规则:
1. 描述这个因子"赚谁的什么钱、靠什么微观机制、什么信息源、预测什么"——用市场机制语言,不描述代码实现(变量名/算子/语法)
2. 落到微观事件:谁在交易(知情者/套保者/做市商/噪声交易者)、对手方是谁、什么行为留下痕迹、为什么这个痕迹可预测
3. 纯中文。禁止:代码符号、变量名、英文标签、YAML、markdown、解释性前缀
4. 只输出描述正文,第一字就开始写机制,不要"该因子..."开场
5. 若信息不足以判断机制,基于类名+信息角度给最合理的机制假设并标注"(推测)"

示例:
输入: 公式=EMA(卖方撤单量), 标签=cancel/liquidity, 角度=撤单流
输出: 薄盘口流动性提供者挂单后遭遇撤单冲击的模式。卖方急于撤卖单往往意味虚假卖压、实际偏多,撤单累积方向与同期主动成交方向构成意图双确认。信息源是限价单撤销流的不对称累积,预测短期方向。"""

USER_TEMPLATE = """分析因子,输出语义意图描述(80-150 字纯中文):

类名: {class_name}
信息角度: {angle}
公式/代码:
{formula}
标签: {tags}

只输出描述正文。"""


def call_llm(class_name: str, formula: str, tags: str, angle_desc: str, model: str) -> str:
    """调 LLM 返回 intuition 文本。兼容官方 Anthropic API 和聚合代理。"""
    try:
        import anthropic
    except ImportError:
        sys.exit("[ERROR] 缺 anthropic SDK。pip install anthropic; export ANTHROPIC_AUTH_TOKEN=xxx")
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("[ERROR] 未设置 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY")
    import httpx
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        http_client=httpx.Client(verify=False, http2=False, timeout=120),  # claudeaggr SSL 绕过
    )
    msg = client.messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_TEMPLATE.format(
                class_name=class_name,
                formula=(formula or "(无)")[:600],
                tags=tags or "(无)",
                angle=angle_desc or "(无)",
            ),
        }],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text")).strip()


def get_factor_input(conn, xname: str):
    row = conn.execute(
        "SELECT class_name, formula_text, angle_code FROM factors WHERE xname=?", (xname,)
    ).fetchone()
    if not row:
        return None
    class_name, formula, angle_code = row
    tags = ", ".join(r[0] for r in conn.execute(
        "SELECT t.name FROM factor_tags ft JOIN tags t ON t.id=ft.tag_id WHERE ft.factor_xname=?",
        (xname,),
    ))
    angle_desc = ""
    if angle_code:
        a = conn.execute(
            "SELECT name, signal_target FROM angle_ontology WHERE code=?", (angle_code,)
        ).fetchone()
        if a:
            angle_desc = f"{a[0]}({a[1]})" if a[1] else a[0]
    return class_name or xname, formula, tags, angle_desc


def backfill_one(conn, xname: str, model: str, dry_run: bool) -> dict:
    info = {"xname": xname, "action": None, "error": None, "text": None}
    inp = get_factor_input(conn, xname)
    if not inp:
        info["action"] = "error"; info["error"] = "xname 不在 DB"; return info
    class_name, formula, tags, angle_desc = inp
    if dry_run:
        info["action"] = "dry_run"; return info
    try:
        text = call_llm(class_name, formula, tags, angle_desc, model)
    except Exception as e:
        info["action"] = "error"; info["error"] = f"LLM 失败: {e}"; return info
    if not text or len(text) < 20:
        info["action"] = "error"; info["error"] = f"输出过短: {text[:80]!r}"; return info
    conn.execute("UPDATE factors SET intuition=? WHERE xname=?", (text, xname))
    info["action"] = "backfilled"; info["text"] = text
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="AI 回填 factors.intuition(语义意图)")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--xname", help="只跑指定 xname(调试)")
    ap.add_argument("--force", action="store_true", help="intuition 已有也重生成")
    ap.add_argument("--dry-run", action="store_true", help="只列名单不调 LLM")
    ap.add_argument("--limit", type=int, help="最多跑 N 个(调试)")
    args = ap.parse_args()

    with db.get_conn(args.db) as conn:
        if args.xname:
            targets = [args.xname]
        elif args.force:
            targets = [r[0] for r in conn.execute("SELECT xname FROM factors ORDER BY xname")]
        else:
            targets = [r[0] for r in conn.execute(
                "SELECT xname FROM factors WHERE intuition IS NULL OR intuition='' ORDER BY xname"
            )]
        if args.limit:
            targets = targets[: args.limit]

        print(f"[INFO] 待回填: {len(targets)} 个, model={args.model}", flush=True)
        ok = err = 0
        for i, x in enumerate(targets, 1):
            r = backfill_one(conn, x, args.model, args.dry_run)
            if r["action"] == "backfilled":
                ok += 1
                conn.commit()  # 逐个提交,防中断丢全部
                print(f"[{i}/{len(targets)}] {x}: OK → {r['text'][:100]}", flush=True)
            elif r["action"] == "error":
                err += 1
                print(f"[{i}/{len(targets)}] {x}: ERROR {r['error']}", flush=True)
            else:
                print(f"[{i}/{len(targets)}] {x}: dry_run", flush=True)

    print(f"\n[RESULT] backfilled={ok} errors={err} total={len(targets)}")


if __name__ == "__main__":
    main()
