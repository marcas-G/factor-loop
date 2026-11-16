"""Read-only adapter for the existing phenomenon miner.

Import is explicit. Raw P-A/B/C/D records are *unverified candidates*
and cannot masquerade as validated, source-linked Phenomenon observations.
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import quote

from .store import TreEvoStore


def mine_legacy_candidates(*, source_db: str | Path, store: TreEvoStore) -> dict:
    source = Path(source_db).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source factor DB not found: {source}")
    # Read-only SQLite URI: cannot update the existing factor database.
    uri = "file:" + quote(str(source), safe="/") + "?mode=ro"
    from core.cog.phenomenon_miner import mine  # lazy import, numpy is optional unless mining

    with sqlite3.connect(uri, uri=True) as conn:
        # Legacy miner prints progress to stdout. Keep CLI JSON output machine-readable.
        with redirect_stdout(sys.stderr):
            raw = mine(conn)
    return store.import_candidates(raw, source_ref=f"legacy-miner:{source}")
