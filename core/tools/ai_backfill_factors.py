"""阶段 B：AI 回填 formula/tags/description，双写 .h frontmatter + DB。

只处理 factors.formula_text IS NULL 的因子。
- 读 .h 全文 → 调 LLM → 解析 YAML 输出
- 注入 frontmatter 到 .h（保留所有原代码不动）
- UPDATE factors SET formula_text=..., params=..., 同步 tags

幂等：formula_text 非空的因子跳过；--force 可强制重新回填。

用法:
    python factor_db/ai_backfill_factors.py
    python factor_db/ai_backfill_factors.py --dry-run
    python factor_db/ai_backfill_factors.py --xname Foo_w21  # 只跑一个
    python factor_db/ai_backfill_factors.py --force          # 强制重新回填

依赖:
    pip install anthropic
    export ANTHROPIC_API_KEY=xxx
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import db
from core.tools.parse_frontmatter import (
    extract_class_name,
    extract_template_default_param,
    inject_frontmatter,
    make_xname,
)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "glm-4.5-air")
FACTORS_DIR = ROOT / "factors"

SYSTEM_PROMPT = """你是 C++ 量化因子代码分析专家。用户会给你一个因子类的源代码，你需要输出 YAML 形式的元数据。

严格规则：
1. 只输出 YAML，不要 markdown 代码块包装，不要解释
2. 第一行就是 `formula:`，最后一行就是某个 tag
3. 字段定义：
   - formula: 一行（如果简单）或多行（YAML `|` 块），描述计算逻辑；用自然语言 + 伪代码混合
   - description: 一句话，描述这个因子想表达的市场观点或信号含义
   - category: 必须是这些之一：microstructure / volume / momentum / cross_section / volatility / sentiment / liquidity
   - tags: 3-6 个标准化英文标签（snake_case），描述数据源、算法、用途
4. formula 必须忠于代码，不要发明不存在的东西
5. 输出示例：

formula: |
  alpha = rolling_mean(mid_price, 20) - rolling_mean(mid_price, 5)
description: 短期均线减长期均线，捕捉短期反转
category: momentum
tags: [moving_average, reversal, intra_day, price_only]
"""

USER_PROMPT_TEMPLATE = """分析以下 C++ 因子代码：

```cpp
{code}
```

类名: {class_name}
文件: {file_name}

输出 YAML 元数据。"""


def call_llm(code: str, class_name: str, file_name: str, model: str) -> str:
    """调 LLM 返回原始 YAML 文本。

    兼容官方 Anthropic API 和聚合代理：
    - 优先读 ANTHROPIC_AUTH_TOKEN（代理常用），回退 ANTHROPIC_API_KEY
    - 自动读 ANTHROPIC_BASE_URL
    """
    try:
        import anthropic
    except ImportError:
        sys.exit(
            "[ERROR] 缺少 anthropic SDK。\n"
            "  pip install anthropic\n"
            "  export ANTHROPIC_AUTH_TOKEN=xxx"
        )

    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "[ERROR] 未设置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY 环境变量"
        )

    import httpx
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        http_client=httpx.Client(verify=False, http2=False, timeout=120),  # claudeaggr SSL 证书需绕过
    )
    msg = client.messages.create(
        model=model,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    code=code, class_name=class_name, file_name=file_name
                ),
            }
        ],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))


_YAML_FENCE_RE = re.compile(r"^\s*```(?:ya?ml)?\s*$", re.MULTILINE)


def parse_llm_yaml(raw: str) -> dict | None:
    """LLM 偶尔会把 YAML 包在 ```yaml ... ``` 里，剥离后用 yaml.safe_load。"""
    cleaned = _YAML_FENCE_RE.sub("", raw).strip()
    try:
        data = yaml.safe_load(cleaned)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def build_frontmatter(
    xname: str,
    class_name: str,
    file_name: str,
    params: dict | None,
    llm_meta: dict,
    created_ts: str,
) -> dict:
    """合并 LLM 输出 + 已知字段，构造完整 frontmatter dict。"""
    formula = llm_meta.get("formula") or ""
    if isinstance(formula, str):
        formula = formula.strip()
    description = llm_meta.get("description") or ""
    if isinstance(description, str):
        description = description.strip()
    tags = llm_meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [tags]
    tags = [str(t) for t in tags]

    return {
        "xname": xname,
        "class_name": class_name,
        "file": file_name,
        "category": llm_meta.get("category"),
        "formula": formula,
        "description": description,
        "tags": tags,
        "params": params or {},
        "parent_xname": None,
        "idea_id": None,
        "status": "draft",
        "created_ts": created_ts,
    }


def backfill_one(conn, xname: str, factors_dir: Path, model: str, dry_run: bool) -> dict:
    """回填一个因子。返回结果 dict。"""
    info = {"xname": xname, "action": None, "error": None}

    row = conn.execute(
        "SELECT class_name, file_path, params, created_ts FROM factors WHERE xname = ?",
        (xname,),
    ).fetchone()
    if not row:
        info["action"] = "error"
        info["error"] = "xname 不在 DB"
        return info

    class_name, file_path, params_json, created_ts = row
    params = None
    if params_json:
        try:
            params = yaml.safe_load(params_json)
        except Exception:
            params = None

    if not file_path:
        info["action"] = "error"
        info["error"] = "DB 里没有 file_path，无法读源码"
        return info

    src_path = factors_dir / file_path
    if not src_path.is_file():
        info["action"] = "error"
        info["error"] = f"源码文件不存在: {src_path}"
        return info

    code = src_path.read_text(encoding="utf-8", errors="replace")
    if not class_name:
        class_name = extract_class_name(code)
    if not params:
        params = extract_template_default_param(code)

    if dry_run:
        info["action"] = "dry_run"
        return info

    # 调 LLM
    try:
        raw_yaml = call_llm(code, class_name or xname, file_path, model)
    except Exception as e:
        info["action"] = "error"
        info["error"] = f"LLM 调用失败: {e}"
        return info

    llm_meta = parse_llm_yaml(raw_yaml)
    if not llm_meta or "formula" not in llm_meta:
        info["action"] = "error"
        info["error"] = f"LLM 输出无法解析: {raw_yaml[:200]!r}"
        return info

    fm = build_frontmatter(
        xname=xname,
        class_name=class_name or xname,
        file_name=file_path,
        params=params,
        llm_meta=llm_meta,
        created_ts=created_ts or "",
    )

    # 1) 回写 .h
    new_text = inject_frontmatter(code, fm)
    src_path.write_text(new_text, encoding="utf-8")

    # 2) UPDATE DB
    db.update_factor_formula(
        conn,
        xname=xname,
        formula_text=fm["formula"],
        description=fm["description"],
        tags=fm["tags"],
        params=fm["params"] or None,
    )

    info["action"] = "backfilled"
    info["tags"] = fm["tags"]
    info["category"] = fm["category"]
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段 B：AI 回填 formula/tags/description")
    ap.add_argument("--db", default=str(db.DB_PATH))
    ap.add_argument("--factors-dir", default=str(FACTORS_DIR))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--xname", help="只跑指定 xname（调试用）")
    ap.add_argument("--force", action="store_true", help="formula 已有也重跑")
    ap.add_argument("--dry-run", action="store_true", help="只列名单不调 LLM")
    ap.add_argument("--limit", type=int, default=None, help="最多跑 N 个（调试用）")
    args = ap.parse_args()

    factors_dir = Path(args.factors_dir)

    with db.get_conn(args.db) as conn:
        if args.xname:
            targets = [args.xname]
        elif args.force:
            targets = [
                r[0]
                for r in conn.execute("SELECT xname FROM factors ORDER BY xname").fetchall()
            ]
        else:
            targets = [
                r[0]
                for r in conn.execute(
                    "SELECT xname FROM factors WHERE formula_text IS NULL ORDER BY xname"
                ).fetchall()
            ]

        if args.limit:
            targets = targets[: args.limit]

        print(f"[INFO] 待回填: {len(targets)} 个因子，model={args.model}")

        results = []
        for i, xname in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {xname} ...", flush=True)
            r = backfill_one(conn, xname, factors_dir, args.model, args.dry_run)
            results.append(r)
            if r["action"] == "error":
                print(f"  ERROR: {r['error']}")
            elif r["action"] == "backfilled":
                print(f"  OK: tags={r.get('tags')} category={r.get('category')}")

    ok = sum(1 for r in results if r["action"] == "backfilled")
    err = sum(1 for r in results if r["action"] == "error")
    print(f"\n[RESULT] backfilled={ok} errors={err} total={len(results)}")


if __name__ == "__main__":
    main()
