"""Test Contract schema 与校验(确定性)。

Contract 是 v1 的核心中间对象:把 Representation Challenge 转成可执行数据实验。
由 evidence_query_compiler 产出,probe_compiler 编译,evidence_card 对照,
adjudicator(agent)审。

字段对齐用户 v1 设计 §三。校验器保证 contract 可编译(缺字段直接 fail)。
"""
import json
import re

REQUIRED_TOP = [
    "test_id", "challenged_equivalence", "task_context", "controls",
    "variation", "competing_predictions", "required_observations",
    "success_pattern", "failure_pattern", "confounders", "data_requirements",
]

REQUIRED_EQUIV = ["representation_equal_on", "collapsed_difference"]
REQUIRED_TASK = ["symbol", "horizon", "target_behavior"]
REQUIRED_CONTROLS = ["must_hold_similar"]
REQUIRED_VARIATION = ["dimensions_allowed_to_change"]
REQUIRED_PRED = ["H1", "H2", "H3", "H0"]

# 每个 competing prediction 里必须有的字段
PRED_FIELDS = ["unique_prediction"]


class ContractError(ValueError):
    pass


def validate(contract: dict) -> list:
    """返回违规列表(空=通过)。不抛异常,便于 designer 迭代。"""
    issues = []
    if not isinstance(contract, dict):
        return ["contract 不是 dict"]
    for k in REQUIRED_TOP:
        if k not in contract:
            issues.append(f"缺顶级字段: {k}")
    eq = contract.get("challenged_equivalence") or {}
    for k in REQUIRED_EQUIV:
        if k not in eq:
            issues.append(f"缺 challenged_equivalence.{k}")
    tc = contract.get("task_context") or {}
    for k in REQUIRED_TASK:
        if k not in tc:
            issues.append(f"缺 task_context.{k}")
    if not contract.get("controls") or not contract["controls"].get("must_hold_similar"):
        issues.append("controls.must_hold_similar 空(必须声明保持相似的坐标)")
    if not contract.get("variation") or not contract["variation"].get("dimensions_allowed_to_change"):
        issues.append("variation.dimensions_allowed_to_change 空(必须声明允许变的维度)")
    preds = contract.get("competing_predictions") or {}
    for h in REQUIRED_PRED:
        if h not in preds:
            issues.append(f"缺 competing_predictions.{h}")
        else:
            for f in PRED_FIELDS:
                if f not in (preds[h] or {}):
                    issues.append(f"缺 competing_predictions.{h}.{f}")
    # 关键:challenge 忠实性——contract 的等价坐标必须能从 witness 推导
    return issues


def from_json(path) -> dict:
    with open(path) as f:
        return json.load(f)


def to_json(contract: dict, path) -> None:
    with open(path, "w") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
