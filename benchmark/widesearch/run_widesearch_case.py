"""Run one WideSearch case under baseline (native Codex Goal) or treatment
(LoopX-guided) arm, producing a fresh final_answer.md in an isolated workspace.

Verifier is intentionally NOT part of this repo: it runs as the official
WideSearch evaluator inside a pier task (sandboxed, gold hidden from the agent)
for the local real-sandbox path, matching the deepswe infrastructure. This file
reuses the shipped native Goal runtime (no second implementation):
  from loopx.capabilities.benchmark_toolkit.native_codex_goal import ...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from tasks import answer_is_fresh, fresh_workspace, prepare_case, stamp_run_start

REPO_ROOT = Path(__file__).resolve().parents[2]


def _objective(case_id: str, workspace: Path, instruction: str, treatment: bool) -> str:
    common = (
        f"Write the final markdown table to {workspace}/final_answer.md and stop. "
        "Use web_search / web_fetch to gather facts from the web."
    )
    if treatment:
        return (
            "Use the installed LoopX skill (/loopx) to start a goal for the benchmark "
            "task in this workspace, then complete the task through LoopX's guided "
            "control (follow its todos and state writebacks). "
            f"Task instruction is in instruction.md: {instruction} {common}"
        )
    return (
        "Complete the benchmark task described in instruction.md inside this "
        f"workspace. {common}"
    )


def _native_goal_modules():
    sys.path.insert(0, str(REPO_ROOT))
    from loopx.capabilities.benchmark_toolkit.native_codex_goal import (  # noqa: PLC0415
        NativeGoalConfig,
        compact_native_goal_receipt,
        run_native_goal_process_until_terminal,
    )

    return NativeGoalConfig, compact_native_goal_receipt, run_native_goal_process_until_terminal


def run_case(
    *,
    case_id: str,
    arm: str,
    data_root: Path,
    timeout_sec: int,
) -> dict:
    raw = data_root / "widesearch.jsonl"
    gold_dir = data_root / "gold"
    cases_root = data_root / "cases"
    run_id = f"{case_id}-{arm}-{time.strftime('%Y%m%d-%H%M%S')}"

    prepare_case(raw=raw, gold_dir=gold_dir, cases_root=cases_root, case_id=case_id)
    workspace = fresh_workspace(cases_root=cases_root, case_id=case_id, run_id=run_id)
    started_at = stamp_run_start(workspace)
    instruction = (workspace / "instruction.md").read_text(encoding="utf-8")

    NativeGoalConfig, compact_receipt, run_native = _native_goal_modules()
    model = os.environ.get("ARK_OPENAI_MODEL", "deepseek-v4-flash-ga-260731")
    config = NativeGoalConfig(
        cwd=str(workspace),
        objective=_objective(case_id, workspace, instruction, treatment=(arm == "treatment")),
        task_instruction=instruction,
        model=model,
        effort=os.environ.get("CODEX_GOAL_EFFORT", "xhigh"),
        approval_policy="never",
        sandbox="danger-full-access",
    )
    turn = run_native(
        config,
        codex_bin=os.environ.get("CODEX_BIN", "codex"),
        process_command=[
            os.environ.get("CODEX_BIN", "codex"),
            "app-server",
            "--listen",
            "stdio://",
            "--enable",
            "goals",
            "-c",
            "tools.web_search=true",
        ],
        process_env={**os.environ},
        process_cwd=str(workspace),
        goal_timeout_sec=timeout_sec,
    )
    receipt = compact_receipt(turn)

    fresh, reason = answer_is_fresh(workspace, started_at)
    if not fresh:
        return {"status": "runner_invalid", "reason": reason, "receipt": receipt}
    return {
        "status": "completed",
        "final_answer": str(workspace / "final_answer.md"),
        "receipt": receipt,
        "arm": arm,
        "run_id": run_id,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=["baseline", "treatment"], required=True)
    p.add_argument("--case", default="ws_en_001")
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--timeout-sec", type=int, default=7200)
    args = p.parse_args()
    outcome = run_case(
        case_id=args.case,
        arm=args.arm,
        data_root=args.data_root,
        timeout_sec=args.timeout_sec,
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
