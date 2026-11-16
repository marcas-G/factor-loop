"""Contract validation against the versioned, docs/standardization JSON Schemas."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "docs" / "standardization" / "schemas"
SCHEMA_NAMES = {
    "node": "hypothesis-node",
    "edge": "refinement-edge",
    "phenomenon": "phenomenon",
}


class ContractError(ValueError):
    """An incoming document does not satisfy its declared contract."""


@lru_cache(maxsize=8)
def _validator(kind: str):
    from jsonschema import Draft202012Validator

    if kind not in SCHEMA_NAMES:
        raise ContractError(f"Unknown contract kind: {kind}")
    path = SCHEMA_ROOT / f"{SCHEMA_NAMES[kind]}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate(kind: str, record: dict) -> dict:
    """Reject malformed input; never silently fill semantic provenance fields."""
    if not isinstance(record, dict):
        raise ContractError(f"{kind} must be a JSON object")
    issues = sorted(_validator(kind).iter_errors(record), key=lambda e: repr(list(e.path)))
    if issues:
        first = issues[0]
        location = ".".join(str(x) for x in first.path) or "<root>"
        raise ContractError(f"{kind}.{location}: {first.message}")

    # A source-linked observation is not automatically evidence of its explanation.
    if kind == "phenomenon":
        window = record["data_window"]
        if not (
            window["feature_end_offset_ms"]
            <= window["label_start_offset_ms"]
            < window["label_end_offset_ms"]
        ):
            raise ContractError("phenomenon data_window: feature data overlaps future response")
        if record["example_status"] == "measured":
            if not record["evidence_refs"]:
                raise ContractError("measured phenomenon requires verifiable evidence_refs")
            if record["dataset_ref"].startswith("synthetic-example/"):
                raise ContractError("synthetic illustrative data cannot be called measured")
    if kind == "edge":
        if record["parent_node_id"] == record["child_node_id"]:
            raise ContractError("refinement cannot be a self-loop")
        if not record["parent_claim_preserved"]:
            raise ContractError("refinement must preserve parent research question")
        if not record["refinement_warrant"].strip():
            raise ContractError("refinement needs a nonblank warrant")
        if any(not x.strip() for x in record["new_information"]):
            raise ContractError("new_information cannot contain blank items")
    if kind == "node" and not record["statement"].strip():
        raise ContractError("node.statement is blank")
    return record
