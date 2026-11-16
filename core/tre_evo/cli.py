"""TreEvo minimal tree CLI: python -m core.tre_evo.cli --help.

Intentional separation from production factor-loop: no write to factors.db,
no MCP server or Claude session required. All outputs are JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import ContractError
from .phenomena import mine_legacy_candidates
from .store import TreEvoStore, TreeConflict, TreeInvariantError


def _read(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, help="TreEvo-only database path (default: ~/.quant-tre-evo/trees.sqlite3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("create-root", help="Create an initial research_theme HypothesisNode")
    s.add_argument("--node", required=True)

    s = sub.add_parser("add-refinement", help="Append a new child with a typed RefinementEdge")
    s.add_argument("--edge", required=True)
    s.add_argument("--child", required=True)
    s.add_argument("--expected-revision", type=int, required=True)

    s = sub.add_parser("record-phenomenon", help="Record an explicitly sourced Phenomenon (not a raw miner candidate)")
    s.add_argument("--record", required=True)

    s = sub.add_parser("import-candidates", help="Stage legacy miner JSON as unverified candidates")
    s.add_argument("--input", required=True)
    s.add_argument("--source-ref", required=True, help="Stable dataset/snapshot identifier")

    s = sub.add_parser("mine-candidates", help="Read-only scan of existing factors.db; requires numpy")
    s.add_argument("--source-db", required=True)

    s = sub.add_parser("show-tree", help="Return full immutable-versioned tree snapshot")
    s.add_argument("--tree-id", required=True)

    s = sub.add_parser("list-candidates", help="List unverified phenomenon candidates")
    s.add_argument("--limit", type=int, default=50)
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = TreEvoStore(args.db)
        if args.cmd == "create-root":
            output = store.create_root(_read(args.node))
        elif args.cmd == "add-refinement":
            output = store.add_refinement(
                _read(args.edge), _read(args.child),
                expected_revision=args.expected_revision
            )
        elif args.cmd == "record-phenomenon":
            output = store.record_phenomenon(_read(args.record))
        elif args.cmd == "import-candidates":
            output = store.import_candidates(_read(args.input), source_ref=args.source_ref)
        elif args.cmd == "mine-candidates":
            output = mine_legacy_candidates(source_db=args.source_db, store=store)
        elif args.cmd == "show-tree":
            output = store.tree(args.tree_id)
        elif args.cmd == "list-candidates":
            output = store.candidates(args.limit)
        else:
            raise AssertionError(f"unrecognized cmd {args.cmd}")
    except (ContractError, TreeConflict, TreeInvariantError, KeyError,
            ValueError, FileNotFoundError, json.JSONDecodeError,
            OSError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
