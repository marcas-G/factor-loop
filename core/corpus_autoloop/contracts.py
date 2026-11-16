"""Strict input boundary for corpus -> hypothesis -> factor -> evaluation -> fusion."""
from __future__ import annotations

import math
import re

class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def string_list(value, *, require_one=False):
    return isinstance(value, list) and (not require_one or len(value) > 0) and all(
        nonempty(x) for x in value
    )


def hypothesis(doc: dict, source_text: str) -> dict:
    """Force a source-grounded cross-domain mechanism, not a made-up quotation."""
    require(isinstance(doc, dict), "hypothesis must be an object")
    for key in ("source_quote", "source_principle", "market_analogy",
                "hypothesis", "observable_prediction", "alternative_explanation",
                "causal_limit"):
        require(nonempty(doc.get(key)), f"hypothesis.{key} required")
    require(doc["source_quote"].strip() in source_text,
            "source_quote must be an exact nonempty substring of current chapter")
    require(string_list(doc.get("required_data"), require_one=True), "hypothesis.required_data must be nonempty")
    require(string_list(doc.get("assumptions")), "hypothesis.assumptions invalid")
    return doc


def factor_spec(doc: dict, expected_hypothesis: str) -> dict:
    """Match the existing persist_candidates factor shape without claiming C++ compilability."""
    require(isinstance(doc, dict), "factor_spec must be an object")
    for key in ("name", "formula", "intuition", "hypothesis"):
        require(nonempty(doc.get(key)), f"factor_spec.{key} required")
    require(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", doc["name"])), "factor name is not a C++ class identifier")
    require(string_list(doc.get("tags"), require_one=True), "factor_spec.tags missing")
    require(isinstance(doc.get("params"), dict), "factor_spec.params must be an object")
    require(isinstance(doc.get("categories"), list) and bool(doc["categories"])
            and all(x in ("AG", "AU", "CU", "AL", "NI") for x in doc["categories"]),
            "categories must be supported product codes, not factor labels")
    require(string_list(doc.get("required_data"), require_one=True), "factor_spec.required_data required")
    require(doc["hypothesis"] == expected_hypothesis,
            "factor_spec.hypothesis must exactly match researched hypothesis")
    require(doc.get("feature_uses_future") is False,
            "factor_spec.feature_uses_future must explicitly be false; execution still requires verification")
    return doc


def evaluation(report: dict, expected_factor: str) -> dict:
    require(isinstance(report, dict), "evaluation must be object")
    for key in ("executor_run_id", "execution_ref", "factor_xname", "library_snapshot_ref", "dataset_ref"):
        require(nonempty(report.get(key)), f"evaluation.{key} required")
    require(report["factor_xname"] == expected_factor, "factor name differs from compiled candidate")
    require(report.get("data_split") in ("screening", "holdout_confirmation"), "evaluation data_split required")
    for field in ("fidelity", "predictive"):
        value = report.get(field)
        require(isinstance(value, dict) and type(value.get("passed")) is bool
                and nonempty(value.get("evidence_ref")), f"evaluation.{field} requires passed and evidence_ref")
    pred = report["predictive"]
    require(nonempty(pred.get("metric_name")), "predictive metric_name required")
    require(isinstance(pred.get("metric_value"), (int, float))
            and type(pred.get("metric_value")) is not bool
            and math.isfinite(pred["metric_value"]), "predictive metric_value must be finite")
    indep = report.get("independence")
    require(isinstance(indep, dict), "independence evaluation required")
    require(indep.get("decision") in ("independent", "redundant", "inconclusive"),
            "independence decision must be independent/redundant/inconclusive")
    require(nonempty(indep.get("evidence_ref")), "independence evidence_ref required")
    require(isinstance(indep.get("nearest_factors"), list) and
            all(nonempty(s) for s in indep["nearest_factors"]), "nearest_factors required")
    for metric in ("r2_x", "res_ic"):
        if indep.get(metric) is not None:
            val = indep[metric]
            require(type(val) in (int, float) and math.isfinite(val), f"independence.{metric} nonfinite")
            if metric == "r2_x":
                require(-0.01 <= val <= 1.01, "independence.r2_x outside expected range")
    if indep["decision"] == "redundant":
        require(bool(indep["nearest_factors"]), "redundant requires at least one nearest existing factor")
    return report


def fusion(report: dict, compared_factor: str) -> dict:
    require(isinstance(report, dict), "fusion report must be object")
    require(report.get("base_factor_xname") == compared_factor, "fusion base factor mismatches candidate")
    require(type(report.get("success")) is bool, "fusion.success must be boolean")
    require(nonempty(report.get("evidence_ref")), "fusion requires evidence reference")
    require(nonempty(report.get("method")), "fusion method must be recorded")
    if report["success"]:
        require(nonempty(report.get("fused_factor_xname")), "successful fusion needs fused_factor_xname")
        require(nonempty(report.get("persist_ref")), "successful fusion must be actually persisted")
        require(report.get("data_split") == "holdout_confirmation",
                "successful fusion requires independent confirmation")
        value = report.get("incremental_value")
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                "successful fusion requires positive independent incremental value")
    else:
        require(nonempty(report.get("failure_reason")), "failed fusion requires failure_reason")
    return report


def admission(report: dict, expected_factor: str) -> dict:
    require(isinstance(report, dict), "admission report must be object")
    require(report.get("factor_xname") == expected_factor, "admission factor mismatches")
    require(nonempty(report.get("persist_ref")), "admission needs real library persist receipt")
    require(nonempty(report.get("confirmation_ref")), "admission needs independent confirmation reference")
    return report


def children(proposals: dict, original_hypothesis: str) -> list[dict]:
    require(isinstance(proposals, dict), "split response must be object")
    require(nonempty(proposals.get("failure_diagnosis")), "split requires why original failed")
    ch = proposals.get("children")
    require(isinstance(ch, list) and len(ch) == 2, "each split must produce exactly two child research objects")
    seen = set()
    for child in ch:
        require(isinstance(child, dict), "child must be object")
        for key in ("hypothesis", "split_reason", "changed_mechanism",
                    "observable_prediction", "alternative_explanation"):
            require(nonempty(child.get(key)), f"split child.{key} required")
        require(string_list(child.get("required_data"), require_one=True), "split child.required_data required")
        require(child["hypothesis"].strip() != original_hypothesis.strip(), "split must change hypothesis")
        require(child["hypothesis"] not in seen, "duplicate children")
        seen.add(child["hypothesis"])
    return ch
