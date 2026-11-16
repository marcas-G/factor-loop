"""CLI for opt-in Dao De Jing -> factor research lifecycle.

No platform calls or database writes to the existing Factor Autoloop occur
without a separate executing Agent using the handoff payload.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.tre_evo.model_client import ChatCompletionsClient, ModelError
from .contracts import ContractError
from .generator import generate_hypothesis, generate_factor, generate_split, factor_handoff
from .workflow import CorpusAutoloop, WorkflowConflict
from .execution_adapter import CorpusExecutionAdapter, EvidenceError
from .agent_runner import OpenCodeRunner


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="isolated corpus loop sqlite; default ~/.quant-corpus-autoloop/research.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="register all 81 source chapters as research objects")
    commands.add_parser("next", help="show earliest active research object; no external executor is launched")
    commands.add_parser("status", help="show queue and run audit statistics")

    p = commands.add_parser("show", help="show object plus original chapter text")
    p.add_argument("--object-id", required=True)
    p = commands.add_parser("events", help="show append-only action history")
    p.add_argument("--object-id", required=True)

    for name, description in (
        ("hypothesis", "generate a source-anchored financial hypothesis"),
        ("factor", "generate one factor specification without submitting code"),
        ("split", "generate exactly two hypotheses from actual experiment/fusion failure"),
    ):
        p = commands.add_parser(name, help=description)
        p.add_argument("--object-id", required=True)
        p.add_argument("--expected-revision", type=int, required=True)
        p.add_argument("--response-file", help="JSON fixture instead of remote model")
        p.add_argument("--base-url", help="explicit OpenAI-compatible model endpoint")
        p.add_argument("--model", help="explicit model identifier")
        p.add_argument("--json-mode", action="store_true", help="request JSON response")
        if name == "factor":
            p.add_argument("--capabilities-file", help="JSON array of verified, platform-available data fields")

    p = commands.add_parser("handoff", help="emit exact persist_candidates payload; DOES NOT execute")
    p.add_argument("--object-id", required=True)

    p=commands.add_parser("fail", help="explicitly close infeasible task, with failed-attempt audit")
    p.add_argument("--object-id", required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--stage", choices=("hypothesis","factor","evaluation","confirmation","fusion","split"),required=True)
    p.add_argument("--attempt-ref", required=True)
    p.add_argument("--reason", required=True)

    for name in ("evaluation", "fusion", "admission"):
        p = commands.add_parser(name, help=f"import externally verified {name} evidence")
        p.add_argument("--object-id", required=True)
        p.add_argument("--expected-revision", type=int, required=True)
        p.add_argument("--file", required=True, help="actual platform evidence/receipt JSON file")

    p = commands.add_parser(
        "execution-start",
        help="REAL SIDE EFFECT: create quant-mcp run and persist one candidate into existing factor ideas DB"
    )
    p.add_argument("--object-id", required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--dataset-ref", required=True, help="actual platform screening dataset identity")
    p.add_argument("--library-snapshot-ref", required=True, help="factor library baseline snapshot identity")
    p.add_argument("--enable-platform-writes", action="store_true",
                   help="explicit acknowledgement of quant-mcp persist_candidates side effects")

    p = commands.add_parser(
        "execution-run",
        help="REAL SIDE EFFECT: launch OpenCode to write C++, submit and check actual platform tasks"
    )
    p.add_argument("--object-id", required=True)
    p.add_argument("--executor-model", required=True, help="registered OpenCode model")
    p.add_argument("--executor-binary", default="opencode")
    p.add_argument("--timeout-sec", type=int, default=1800)
    p.add_argument("--enable-platform-writes", action="store_true",
                   help="explicitly authorize real code generation and platform execution")

    p = commands.add_parser(
        "execution-collect",
        help="read actual quant-mcp state; derive screening metrics; require source-bound fidelity review"
    )
    p.add_argument("--object-id", required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--fidelity-file", required=True, help="review + actual .h SHA-256 attestation")
    p.add_argument("--nearest-file", help="verified JSON array of already-existing similar factor names")
    p.add_argument("--zero-rate", type=float,
                   help="only if measured zero-rate is absent from platform eval_metrics")
    p.add_argument("--enable-platform-writes", action="store_true",
                   help="allow writing result to isolated corpus ledger (not production factor DB)")

    p = commands.add_parser("execution-status", help="show authoritative quant run binding")
    p.add_argument("--object-id", required=True)

    return parser.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    try:
        store = CorpusAutoloop(args.db)
        cmd = args.command
        if cmd == "seed":
            result = store.seed()
        elif cmd == "next":
            result = store.next_object()
        elif cmd == "status":
            result = store.status()
        elif cmd == "show":
            result = store.get(args.object_id)
        elif cmd == "events":
            result = store.events(args.object_id)
        elif cmd == "fail":
            result=store.record_infeasible(args.object_id,revision=args.expected_revision,
                 stage=args.stage,attempt_ref=args.attempt_ref,reason=args.reason)
        elif cmd == "execution-start":
            if not args.enable_platform_writes:
                raise WorkflowConflict("explicit --enable-platform-writes required")
            result=CorpusExecutionAdapter(store).begin(
                args.object_id, expected_revision=args.expected_revision,
                dataset_ref=args.dataset_ref, library_snapshot_ref=args.library_snapshot_ref)
        elif cmd == "execution-run":
            if not args.enable_platform_writes:
                raise WorkflowConflict("explicit --enable-platform-writes required")
            adapter=CorpusExecutionAdapter(store)
            link=adapter._link(args.object_id)
            if not link or not link.get("run_id") or link["status"]!="prepared":
                raise WorkflowConflict("no prepared quant run; call execution-start first")
            obj=store.get(args.object_id)
            if obj["status"]!="awaiting_evaluation":
                raise WorkflowConflict("research object no longer awaiting evaluation")
            result=OpenCodeRunner(
                binary=args.executor_binary, model=args.executor_model,
                timeout=args.timeout_sec
            ).execute(obj,link["run_id"])
        elif cmd == "execution-collect":
            if not args.enable_platform_writes:
                raise WorkflowConflict("explicit --enable-platform-writes required")
            result=CorpusExecutionAdapter(store).collect(
                args.object_id,expected_revision=args.expected_revision,
                fidelity_review=_read(args.fidelity_file),
                nearest_factors=_read(args.nearest_file) if args.nearest_file else None,
                zero_rate=args.zero_rate)
        elif cmd == "execution-status":
            adapter=CorpusExecutionAdapter(store)
            link=adapter._link(args.object_id)
            result={"binding":link}
            if link and link.get("run_id"):
                state=adapter.backend.run_load(link["run_id"])
                fac=(state.get("factors") or [{}])[0]
                result["run"]={"run_id":state.get("run_id"),
                               "factor_status":fac.get("status"),
                               "failure_layer":fac.get("failure_layer"),
                               "has_eval_metrics":bool((fac.get("evidence") or {}).get("eval_metrics")),
                               "has_ridge_svd":bool((fac.get("evidence") or {}).get("ridge_svd_agg")),
                               "premature_persistence":bool(fac.get("persisted") or fac.get("verdict"))}
        elif cmd == "handoff":
            result = factor_handoff(store.get(args.object_id))
        elif cmd in ("hypothesis", "factor", "split"):
            obj = store.get(args.object_id)
            response = _read(args.response_file) if args.response_file else None
            client = (ChatCompletionsClient(base_url=args.base_url,model=args.model,
                                             json_mode=args.json_mode)
                      if response is None else None)
            if cmd == "hypothesis":
                payload = generate_hypothesis(obj, client=client, response=response)
                result = store.record_hypothesis(obj["object_id"], payload, revision=args.expected_revision)
            elif cmd == "factor":
                capabilities = _read(args.capabilities_file) if args.capabilities_file else None
                if capabilities is not None and not (
                    isinstance(capabilities, list) and all(isinstance(x,str) for x in capabilities)
                ):
                    raise ValueError("--capabilities-file must be a JSON array of field names")
                payload = generate_factor(obj,client=client,response=response,capabilities=capabilities)
                result = store.record_factor(obj["object_id"], payload, revision=args.expected_revision)
            else:
                payload = generate_split(obj,client=client,response=response)
                result = store.record_split(obj["object_id"],payload,revision=args.expected_revision)
        elif cmd == "evaluation":
            result = store.record_evaluation(args.object_id,_read(args.file),revision=args.expected_revision)
        elif cmd == "fusion":
            result = store.record_fusion(args.object_id,_read(args.file),revision=args.expected_revision)
        elif cmd == "admission":
            result = store.record_admission(args.object_id,_read(args.file),revision=args.expected_revision)
        else:
            raise ValueError(f"unknown command {cmd}")
    except (WorkflowConflict,ContractError,ModelError,EvidenceError,KeyError,ValueError,
            ImportError,FileNotFoundError,OSError) as exc:
        print("ERROR:",exc,file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
