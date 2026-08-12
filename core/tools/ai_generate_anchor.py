"""生成 factors.anchor_text(embedding 锚定文本)—— 固定四要素模板 + 固定 prompt。

所有因子走同一 prompt,产出风格统一的锚定文本,保证 embedding 检索稳定。
与 intuition(研究用,带 idea#/上下文)分离:anchor_text 专门给 embedding。

只处理 factors.anchor_text IS NULL/空的因子。
- 读 formula_text + tags + angle → 调 glm-5.1 按四要素模板生成 → UPDATE anchor_text

幂等:anchor_text 非空跳过;--force 全部重生成。

用法:
    python factor_db/ai_generate_anchor.py --xname Foo   # 调试
    python factor_db/ai_generate_anchor.py --limit 3      # 试几个
    python factor_db/ai_generate_anchor.py                # 全量缺的
    python factor_db/ai_generate_anchor.py --force        # 全部重生成

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

# GLM-5.1(大写:代理 claudeaggr 认;小写 glm-5.1 代理报 unknown provider)
DEFAULT_MODEL = "GLM-5.1"

# 固定四要素模板 —— 所有因子统一格式,保证 embedding 锚点风格一致
# 核心约束:机制要素必须具体(落到字段+算子+触发条件),禁泛化套话——检索靠它区分因子
SYSTEM_PROMPT = """你是量化因子语义标注专家。给定因子的公式/标签/信息角度,严格按四要素模板输出锚定文本(用于语义检索 embedding)。

**最高优先级规则**:机制要素必须写该因子 formula 特有的、能区分同族变体的具体微观行为,**严禁泛化套话**。检索靠机制要素区分因子,套话(如"做市商盘口不对称")会让同类因子无法区分、检索失效。

严格规则:
1. 输出固定四行,顺序固定,每行"要素:内容":
   机制: <该因子 formula 的具体计算逻辑对应的微观事件——必须落到具体字段(如卖方撤单量/深度档位偏度/成交速率/OI 变化)+ 算子(EMA/差分/分位/加权)+ 触发条件。必须写出该因子区别于同族变体的特异处(同为盘口族:撤单流 vs 深度偏度 vs 加单重心 要写出区别)>
   利润来源: <赚 L1-L5 谁的钱 + 对手方>
   信息源: <具体数据字段 + 算子(从 formula 提取,不泛化)>
   预测: <方向/目标 + horizon>
2. 纯中文。禁:代码符号、变量名、英文标签、研究编号(idea#/子簇/L2-L3)
3. 每要素一句(机制要素可稍长以写具体)
4. **机制要素禁套话——反例 vs 正例**:
   ❌ 套话:"做市商在盘口不对称挂单"(所有盘口因子都适用,零区分度)
   ✅ 具体:"卖方撤单量的指数移动平均累积,浅薄深度档位加权放大撤单冲击"(撤单流特有,区别于深度偏度/加单重心)
5. 只输出四行,无解释/前言/示例复述

示例:
输入: 公式=EMA(卖方撤单量)×浅盘口深度权重, 标签=cancel/liquidity, 角度=撤单流
机制: 卖方撤单量的指数移动平均累积,浅薄深度档位加权放大撤单冲击,撤单方向暴露虚假卖压。
利润来源: 赚 L2 流动性补偿,对手方是被撤单误导的做市商。
信息源: 限价单撤销量的方向性 EMA 累积 × 深度权重。
预测: 短期方向,horizon 60 秒。"""

USER_TEMPLATE = """分析因子,按四要素模板输出锚定文本(固定四行):

类名: {class_name}
信息角度: {angle}
公式/代码:
{formula}
标签: {tags}

只输出四行(机制/利润来源/信息源/预测)。"""


def call_llm(class_name: str, formula: str, tags: str, angle_desc: str, model: str) -> str:
    """调 LLM 返回四要素锚定文本。兼容官方 Anthropic API 和聚合代理。"""
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
        http_client=httpx.Client(verify=False, http2=False, timeout=120),
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


def gen_one(conn, xname: str, model: str, dry_run: bool) -> dict:
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
    # 校验:必须含四要素前缀
    if not all(k in text for k in ("机制:", "利润来源:", "信息源:", "预测:")):
        info["action"] = "error"; info["error"] = f"格式不符(缺四要素): {text[:120]!r}"; return info
    conn.execute("UPDATE factors SET anchor_text=? WHERE xname=?", (text, xname))
    info["action"] = "backfilled"; info["text"] = text
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 factors.anchor_text(固定四要素模板)")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--xname", help="只跑指定 xname(调试)")
    ap.add_argument("--force", action="store_true", help="anchor_text 已有也重生成")
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
                "SELECT xname FROM factors WHERE anchor_text IS NULL OR anchor_text='' ORDER BY xname"
            )]
        if args.limit:
            targets = targets[: args.limit]

        print(f"[INFO] 待生成: {len(targets)} 个, model={args.model}", flush=True)
        ok = err = 0
        for i, x in enumerate(targets, 1):
            r = gen_one(conn, x, args.model, args.dry_run)
            if r["action"] == "backfilled":
                ok += 1
                conn.commit()  # 逐个提交,防中断丢全部
                print(f"[{i}/{len(targets)}] {x}: OK → {r['text'].replace(chr(10), ' | ')[:110]}", flush=True)
            elif r["action"] == "error":
                err += 1
                print(f"[{i}/{len(targets)}] {x}: ERROR {r['error']}", flush=True)
            else:
                print(f"[{i}/{len(targets)}] {x}: dry_run", flush=True)

    print(f"\n[RESULT] backfilled={ok} errors={err} total={len(targets)}")


if __name__ == "__main__":
    main()
