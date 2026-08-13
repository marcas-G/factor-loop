#!/usr/bin/env python3
"""submit(吸收 runtime/stages/submit.mjs)。

推送到量化平台:subprocess featuretool.py submit。
categories 白名单校验(防 P0:angle 标签误填 → DAG failed)。
"""
from __future__ import annotations

import json
from pathlib import Path

from core.infra.run_py import run_py, parse_json_output
from core.stages.write_factor import extract_class_name_from_h, is_template_class

SUBMIT_TIMEOUT_SEC = 120
# featuretool.py 路径(core/platform/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEATURETOOL_PY = str(_PROJECT_ROOT / "core" / "platform" / "featuretool.py")

# 合法品种代码白名单(沪金银铜铝镍,5 品种)。
# categories 必须是这些代码之一,不是 angle 标签(oi_anomaly/regime_gate 等)。
VALID_CATEGORIES = ["AG", "AU", "CU", "AL", "NI"]


def validate_categories(categories) -> dict:
    """校验 categories 是合法品种代码。返回 {valid, invalid, error}。"""
    if not isinstance(categories, list):
        return {"valid": False, "invalid": [], "error": f"categories 必须是数组, 得到 {type(categories).__name__}"}
    invalid = [c for c in categories if c not in VALID_CATEGORIES]
    if invalid:
        return {
            "valid": False, "invalid": invalid,
            "error": f"categories 必须是品种代码 {'/'.join(VALID_CATEGORIES)} 之一(如 ['AG']), 不是 angle 标签或 tags。非法值: {', '.join(invalid)}",
        }
    return {"valid": True, "invalid": []}


def _categories_to_feeds(categories: list[str] | None) -> str | None:
    """categories: ['CU','AL'] → 'SHFE-CU,SHFE-CU@1,SHFE-AL,SHFE-AL@1'。空/None → None(用默认)。"""
    if not isinstance(categories, list) or not categories:
        return None
    return ",".join(f"SHFE-{c},SHFE-{c}@1" for c in categories)


def submit_factor_programmatic(factor: dict, factor_file: str) -> dict:
    """推送因子。返回 {ok, features, error?, raw?, attempts}。"""
    # P0 防御:categories 必须是合法品种代码
    cat_check = validate_categories(factor.get("categories") or [])
    if not cat_check["valid"]:
        return {
            "ok": False, "features": factor.get("name"),
            "error": f"[categories 语义错误] {cat_check['error']}",
            "raw": f"非法 categories: {factor.get('categories')}",
            "attempts": 1, "failure_layer": "config_error",
        }

    class_name = extract_class_name_from_h(factor_file) or factor.get("name")
    features = f"{class_name}<>" if is_template_class(factor_file) else class_name
    feeds = _categories_to_feeds(factor.get("categories"))

    args = ["submit", "--file", factor_file, "--features", features, "--json"]
    if feeds:
        args += ["--feeds", feeds]

    result = run_py(FEATURETOOL_PY, args, timeout_sec=SUBMIT_TIMEOUT_SEC)

    if result["timed_out"]:
        return {"ok": False, "features": features, "error": f"submit 超时 ({result['duration_ms']}ms)", "raw": result["stdout"], "attempts": 1}
    parsed = parse_json_output(result["stdout"])
    if not parsed:
        return {"ok": False, "features": features, "error": f"submit 输出非 JSON: {(result['stdout'] or result['stderr'])[:200]}", "raw": result["stdout"], "attempts": 1}
    if parsed.get("ok") is True and result["exit_code"] == 0:
        return {"ok": True, "features": parsed.get("features") or features, "raw": json.dumps(parsed, ensure_ascii=False), "attempts": 1}
    return {"ok": False, "features": parsed.get("features") or features, "error": parsed.get("error") or f"exit={result['exit_code']}", "raw": json.dumps(parsed, ensure_ascii=False), "attempts": 1}
