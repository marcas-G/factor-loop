"""Deterministic, chapter-level corpus loader with original-source provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARTS = ROOT / "corpora" / "daodejing" / "parts"
CORPUS_ID = "daodejing-wangbi-81-v1"


def load_chapters(parts_dir: Path | None = None) -> list[dict]:
    parts = Path(parts_dir) if parts_dir is not None else DEFAULT_PARTS
    files = sorted(parts.glob("*.json"))
    if not files:
        raise ValueError(f"missing corpus parts under {parts}")
    units = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"expected chapter array in {file}")
        for raw in data:
            chapter, text = raw["chapter"], raw["text"]
            if type(chapter) is not int or not 1 <= chapter <= 81:
                raise ValueError(f"invalid chapter in {file}")
            if not isinstance(text, str) or len(text.strip()) < 10:
                raise ValueError(f"empty chapter {chapter}")
            expected_id = f"daodejing-wangbi-{chapter:03d}"
            if raw.get("unit_id") != expected_id:
                raise ValueError(f"chapter identifier mismatch: {chapter}")
            expected_source = f"data/chapters/{chapter:03d}.json"
            if raw.get("source_file") != expected_source:
                raise ValueError(f"provenance mismatch: {chapter}")
            units.append({**raw, "corpus_id": CORPUS_ID,
                          "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    units.sort(key=lambda x: x["chapter"])
    if len(units) != 81 or [x["chapter"] for x in units] != list(range(1, 82)):
        raise ValueError("Dao De Jing corpus must contain exactly the 81 distinct ordered chapters")
    return units
