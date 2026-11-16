"""Opt-in, synchronous OpenCode runner for the existing run-factor-agent spec.

The task is serialized because run-factor-agent still reads a legacy fixed
.tmp/agent_task.json path. Never overwrite another agent's task file. The
model uses configured quant-mcp tools and is responsible for real C++,
submission, check and restest. Its answer is not trusted as execution evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .execution_adapter import EvidenceError, NativeQuantBackend
from .workflow import WorkflowConflict

ROOT = Path(__file__).resolve().parents[2]


def _task_path(root):
    return Path(root).resolve() / ".tmp" / "agent_task.json"


def _task_document(state, obj):
    if state.get("run_id") is None:
        raise WorkflowConflict("missing quant run id")
    factors = state.get("factors") or []
    if len(factors) != 1 or factors[0].get("name") != obj["factor"]["name"]:
        raise WorkflowConflict("executor run does not match research object")
    return {
        "input": {
            "factor": {key: obj["factor"][key] for key in (
                "name","formula","intuition","hypothesis","tags","categories","params")},
            "idea": obj["hypothesis"]["hypothesis"],
            "run_id": state["run_id"], "factor_index": 0,
        },
        "corpus_autoloop": {"object_id": obj["object_id"],
                            "source_id": obj["source_id"],
                            "policy": "screening_only_no_persist_verdict"},
    }


def _instruction(task_file, run_id):
    return f"""You are running ONE corpus-guided factor execution using the existing
run-factor-agent flow and quant-mcp tools (not a hypothetical simulation).
Read the task JSON at {task_file}. Read the project's
.zcode/agents/executors/run-factor-agent.md and
.agents/skills/write-factor/SKILL.md before writing code.
Use the real quant-mcp run_load for run_id={run_id}.
The run was ALREADY created and its candidates persisted. Do not invoke
run_init or persist_candidates again.
Follow actual write -> platform_submit_factor -> platform_check_factor
-> platform_restest_factor, retrying only according to the original agent spec.
Record actual C++ path and final status through quant-mcp run_save.
Do NOT fabricate test results, factor values or run ID.
IMPORTANT: Do not invoke assess Skill's persistence step, and NEVER call
persist_factor(mode=commit) in this screening run. Corpus Autoloop owns
holdout confirmation and admission. Any C++/MCP/platform failure must
be reported via failure_layer in original run state, not invented as success.
Read the final run_load state; stop only after factor status is done or failed.
Respond with run_id and terminal factor status only. Do not create child agents.
"""


class OpenCodeRunner:
    def __init__(self, *, root=None, binary=None, model=None, timeout=1800,
                 spawn=None, backend=None):
        self.root = Path(root or ROOT).expanduser().resolve()
        self.binary = binary or os.getenv("CORPUS_EXECUTOR_BINARY") or "opencode"
        self.model = model or os.getenv("CORPUS_EXECUTOR_MODEL")
        self.timeout = timeout
        self.spawn = spawn or subprocess.run
        self.backend = backend or NativeQuantBackend()
        if not self.model:
            raise WorkflowConflict("set --executor-model or CORPUS_EXECUTOR_MODEL")
        if type(timeout) is not int or not 30 <= timeout <= 7200:
            raise WorkflowConflict("timeout must be 30..7200 seconds")
        if not (self.root / ".zcode" / "agents" / "executors" /
                "run-factor-agent.md").is_file():
            raise WorkflowConflict("executor agent contract absent from workspace")

    def execute(self, research_object, run_id):
        # Absolutely no use of shell=True or global agent-task overrides.
        task_file = _task_path(self.root)
        if task_file.exists():
            raise WorkflowConflict(
                ".tmp/agent_task.json already exists; concurrent runner forbidden")
        state = self.backend.run_load(run_id)
        if state.get("parent_session") != (
            f"corpus:{research_object['object_id']}:screening:{research_object['revision']}"
        ):
            raise WorkflowConflict("run ownership token does not match research object")
        task = _task_document(state, research_object)
        task_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with task_file.open("x", encoding="utf-8") as handle:
                json.dump(task, handle, ensure_ascii=False, indent=2)
            log_dir = self.root / ".tmp" / "corpus_executor"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{run_id}.log"
            command = [self.binary, "run", "--model", self.model, "--dir",
                       str(self.root), _instruction(task_file, run_id)]
            with log_file.open("wb") as output:
                try:
                    finished = self.spawn(command, cwd=self.root, stdin=subprocess.DEVNULL,
                                          stdout=output, stderr=subprocess.STDOUT,
                                          timeout=self.timeout, check=False)
                except FileNotFoundError as exc:
                    raise WorkflowConflict(
                        f"executor program not installed: {self.binary}") from exc
                except subprocess.TimeoutExpired as exc:
                    raise WorkflowConflict(
                        "executor timed out; inspect original quant run for resumption, "
                        "DO NOT blindly resubmit") from exc
            # Never accept a model's summary; inspect the actual authoritative state.
            updated = self.backend.run_load(run_id)
            factors = updated.get("factors") or []
            factor = factors[0] if len(factors) == 1 else {}
            result = {
                "run_id": run_id, "exit_code": finished.returncode,
                "log_file": str(log_file),
                "factor_status": factor.get("status"),
                "failure_layer": factor.get("failure_layer"),
            }
            if finished.returncode != 0:
                raise WorkflowConflict(
                    f"executor returned {finished.returncode}; see {log_file}")
            if factor.get("status") not in ("done", "failed"):
                raise WorkflowConflict(
                    f"executor did not persist terminal status; see {log_file}")
            if factor.get("status") == "done" and factor.get("failure_layer") != "check_done":
                raise EvidenceError("factor done without check_done evidence")
            if factor.get("persisted") or factor.get("verdict"):
                raise EvidenceError("executor prematurely wrote a factor library verdict")
            return result
        finally:
            if task_file.exists():
                # O_EXCL creation guarantees we did not overwrite another task.
                # If a third party modified the task unexpectedly, preserve it.
                if task_file.read_text(encoding="utf-8") == json.dumps(
                    task, ensure_ascii=False, indent=2):
                    task_file.unlink()
