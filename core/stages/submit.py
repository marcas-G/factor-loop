#!/usr/bin/env python3
"""submit(吸收 runtime/stages/submit.mjs)。

推送评估任务:CPU csv_ic 与 GPU ridge_svd 在同一提交阶段并发触发。
categories 白名单校验(防 P0:非品种代码误填 → DAG failed)。
"""
from __future__ import annotations

from core.platform.gpu import submit_csv_and_gpu_ridge
from core.stages.write_factor import extract_class_name_from_h, is_template_class

# 合法品种代码白名单(沪金银铜铝镍,5 品种)。
# categories 必须是这些代码之一,不是 tags 或因子名。
VALID_CATEGORIES = ["AG", "AU", "CU", "AL", "NI"]


def validate_categories(categories) -> dict:
    """校验 categories 是合法品种代码。返回 {valid, invalid, error}。"""
    if not isinstance(categories, list):
        return {"valid": False, "invalid": [], "error": f"categories 必须是数组, 得到 {type(categories).__name__}"}
    invalid = [c for c in categories if c not in VALID_CATEGORIES]
    if invalid:
        return {
            "valid": False, "invalid": invalid,
            "error": f"categories 必须是品种代码 {'/'.join(VALID_CATEGORIES)} 之一(如 ['AG']), 不是 tags 或因子名。非法值: {', '.join(invalid)}",
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

    result = submit_csv_and_gpu_ridge(
        factor_file,
        features,
        feeds or "SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1",
    )
    if result.get("ok"):
        return {
            "ok": True,
            "features": features,
            "engines": result["engines"],
            "tasks": result["tasks"],
            "raw": result,
            "attempts": 1,
        }
    return {
        "ok": False,
        "features": features,
        "error": result.get("error"),
        "raw": result,
        "attempts": 1,
        "failure_layer": "submit_failed",
    }
