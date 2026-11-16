#!/usr/bin/env python3
"""Validate TreEvo RFC schemas and *illustrative* consistency; no real backtest."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"

TYPE_BY_FILE = {
    "phenomenon": "phenomenon",
    "hypothesis-root": "hypothesis-node",
    "hypothesis-child": "hypothesis-node",
    "refinement-edge": "refinement-edge",
    "experiment-design": "experiment-design",
    "factor-handoff": "factor-handoff",
}


def time_window_errors(window: dict, context: str):
    f = window["feature_end_offset_ms"]
    s = window["label_start_offset_ms"]
    e = window["label_end_offset_ms"]
    return [] if f <= s < e else [f"{context}: future leakage / invalid time ordering: {f} <= {s} < {e}"]


def logical_errors(objs: dict):
    errors = []
    root = objs["hypothesis-root"]
    child = objs["hypothesis-child"]
    edge = objs["refinement-edge"]
    phenotype = objs["phenomenon"]
    experiment = objs["experiment-design"]
    handoff = objs["factor-handoff"]

    if root["parent_id"] is not None:
        errors.append("root must have null parent_id")
    if root["tree_id"] != child["tree_id"] or edge["tree_id"] != child["tree_id"]:
        errors.append("tree_id mismatch")
    if edge["parent_node_id"] != root["node_id"] or edge["child_node_id"] != child["node_id"]:
        errors.append("refinement edge endpoints mismatch")
    if child["parent_id"] != root["node_id"]:
        errors.append("child parent_id mismatch")
    if root["node_id"] == child["node_id"]:
        errors.append("self-edge not allowed")
    if root["statement"] == child["statement"]:
        errors.append("refinement cannot repeat the parent claim verbatim")
    if not edge["parent_claim_preserved"]:
        errors.append("this refinement does not preserve its parent question; requires new tree")
    if phenotype["phenomenon_id"] not in child["source_phenomena"]:
        errors.append("child phenomenon link missing")
    if experiment["source_node_id"] != child["node_id"]:
        errors.append("experiment is not linked to the child hypothesis")
    if handoff["source_node_id"] != child["node_id"] or handoff["experiment_id"] != experiment["experiment_id"]:
        errors.append("factor handoff provenance mismatch")
    if "H0" not in {h["hypothesis_id"] for h in experiment["hypotheses"]}:
        errors.append("experiment requires explicit H0")
    ps = [h["unique_prediction"] for h in experiment["hypotheses"]]
    if len(ps) != len(set(ps)):
        errors.append("competing hypotheses must have distinct predictions")
    errors += time_window_errors(phenotype["data_window"], "phenomenon")
    errors += time_window_errors(experiment["data_plan"], "experiment")
    if experiment["design_type"] in {"observational_comparison", "negative_control"}:
        if experiment["causal_claim_level"] != "associational":
            errors.append("observational evidence must not claim interventional causality")
    if phenotype["example_status"] == "measured" and not phenotype["evidence_refs"]:
        errors.append("measured phenomenon requires evidence_refs")
    if experiment["example_status"] == "measured" and not experiment["evidence_refs"]:
        errors.append("measured experiment requires evidence_refs")
    if child["node_status"] == "ready_to_test" and not experiment["required_observations"]:
        errors.append("ready_to_test must define required observations")
    return errors


def validate():
    schema_files = sorted(SCHEMAS.glob("*.schema.json"))
    assert len(schema_files) == 5, "expected 5 schema files"
    validators = {}
    for path in schema_files:
        obj = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(obj)
        validators[path.name.replace(".schema.json", "")] = Draft202012Validator(obj)

    objects = {}
    for filename, schema_name in TYPE_BY_FILE.items():
        obj = json.loads((EXAMPLES / f"{filename}.json").read_text(encoding="utf-8"))
        validator = validators[schema_name]
        issues = sorted(validator.iter_errors(obj), key=lambda error: list(map(str, error.path)))
        if issues:
            raise AssertionError(f"{filename}: " + "; ".join(i.message for i in issues))
        assert obj["example_status"] == "illustrative_only", "examples must not be presented as measured market results"
        objects[filename] = obj

    errs = logical_errors(objects)
    assert not errs, "\n".join(errs)

    # Minimal adversarial checks for boundary enforcement.
    modified = copy.deepcopy(objects)
    modified["refinement-edge"]["refinement_warrant"] = ""
    assert list(validators["refinement-edge"].iter_errors(modified["refinement-edge"])), "empty warrant escaped schema"
    modified = copy.deepcopy(objects)
    modified["experiment-design"]["data_plan"]["label_start_offset_ms"] = -10
    assert logical_errors(modified), "future leakage escaped semantic check"
    modified = copy.deepcopy(objects)
    modified["experiment-design"]["causal_claim_level"] = "interventional"
    assert list(validators["experiment-design"].iter_errors(modified["experiment-design"])), "observational causality escaped schema"
    modified = copy.deepcopy(objects)
    modified["refinement-edge"]["child_node_id"] = "DIFFERENT"
    assert logical_errors(modified), "broken lineage escaped semantic check"

    print(f"PASS: {len(schema_files)} JSON schemas; {len(objects)} illustrative examples")
    print("PASS: refinement, parentage, provenance, H0, temporal and causal-boundary checks")
    print("NOTE: proposal only — no production API integration or platform experiment executed")


if __name__ == "__main__":
    validate()
