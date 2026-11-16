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
from .model_client import ChatCompletionsClient, ModelError
from .refinement import propose
from .review_queue import ReviewQueue
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
    s = sub.add_parser("propose-refinements", help="LLM diagnosis, typed child proposals and critical review; no tree change")
    s.add_argument("--tree-id", required=True)
    s.add_argument("--parent-id", required=True)
    s.add_argument("--focus", help="Optional research question focus, not an evidence claim")
    s.add_argument("--phenomenon-id", action="append", dest="phenomenon_ids",
                   help="Explicitly registered phenomenon ID (repeat for multiple)")
    s.add_argument("--include-unverified", action="store_true",
                   help="Provide at most 5 raw, explicitly unverified miner candidates as optional leads")
    s.add_argument("--max-candidates", type=int, choices=(1, 2, 3), default=2)
    s.add_argument("--response-file", help="Use a generated JSON fixture instead of calling generation model")
    s.add_argument("--critique-file", help="Use reviewer JSON fixture instead of calling critic model")
    s.add_argument("--model", help="Proposer model (or TREEVO_LLM_MODEL)")
    s.add_argument("--critic-model", help="Optional distinct reviewer model")
    s.add_argument("--base-url", help="Explicit OpenAI-compatible API base URL")
    s.add_argument("--json-mode", action="store_true", help="Request JSON object response format")

    s = sub.add_parser("list-refinement-proposals", help="List proposal queue; proposals are not tree nodes")
    s.add_argument("--tree-id")
    s.add_argument("--limit", type=int, default=100)

    s = sub.add_parser("show-refinement-proposal", help="Show diagnosis, candidate, critic, decision history")
    s.add_argument("--proposal-id", required=True)

    s = sub.add_parser("accept-refinement", help="Human-reviewed commit; atomic node+edge+review decision")
    s.add_argument("--proposal-id", required=True)
    s.add_argument("--reviewer", required=True, help="Human reviewer identifier")
    s.add_argument("--reason", required=True, help="Why parent-child refinement is meaningful")

    s = sub.add_parser("reject-refinement", help="Human rejection with durable reason")
    s.add_argument("--proposal-id", required=True)
    s.add_argument("--reviewer", required=True)
    s.add_argument("--reason", required=True)

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
        elif args.cmd == "propose-refinements":
            generation = _read(args.response_file) if args.response_file else None
            critique = _read(args.critique_file) if args.critique_file else None
            client = None
            critic_client = None
            if generation is None or (critique is None and (generation is None or generation.get("candidates"))):
                client = ChatCompletionsClient(base_url=args.base_url, model=args.model,
                                               json_mode=args.json_mode)
                if args.critic_model:
                    critic_client = ChatCompletionsClient(
                        base_url=args.base_url, model=args.critic_model,
                        json_mode=args.json_mode)
            output = propose(
                store, args.tree_id, args.parent_id, client=client,
                critic_client=critic_client, generation=generation, critique=critique,
                max_candidates=args.max_candidates, phenomenon_ids=args.phenomenon_ids,
                include_unverified=args.include_unverified, focus=args.focus,
                model_label=args.model or ("fixture" if generation is not None else
                                           client.model))
            output["queue_result"] = ReviewQueue(store).enqueue(output["proposals"])
        elif args.cmd == "list-refinement-proposals":
            output = ReviewQueue(store).list(tree_id=args.tree_id, limit=args.limit)
        elif args.cmd == "show-refinement-proposal":
            output = ReviewQueue(store).get(args.proposal_id)
        elif args.cmd == "accept-refinement":
            output = ReviewQueue(store).accept(args.proposal_id, reviewer=args.reviewer,
                                               reason=args.reason)
        elif args.cmd == "reject-refinement":
            output = ReviewQueue(store).reject(args.proposal_id, reviewer=args.reviewer,
                                               reason=args.reason)
        elif args.cmd == "show-tree":
            output = store.tree(args.tree_id)
        elif args.cmd == "list-candidates":
            output = store.candidates(args.limit)
        else:
            raise AssertionError(f"unrecognized cmd {args.cmd}")
    except (ContractError, ModelError, TreeConflict, TreeInvariantError, KeyError,
            ValueError, FileNotFoundError, json.JSONDecodeError,
            OSError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
