#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from loopx.experiments.planner_worker.traex import (  # noqa: E402
    DEFAULT_TRAEX_PLANNER_MODEL,
    DEFAULT_TRAEX_WORKER_MODEL,
    run_traex_planner_worker_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the experimental TraeX planner-worker vertical slice."
    )
    parser.add_argument("--traex-bin", default="traex")
    parser.add_argument("--planner-model", default=DEFAULT_TRAEX_PLANNER_MODEL)
    parser.add_argument("--worker-model", default=DEFAULT_TRAEX_WORKER_MODEL)
    parser.add_argument("--cwd", default=".")
    parser.add_argument(
        "--full-worker-context",
        action="store_true",
        help="Load normal TraeX user/project context for the worker instead of the minimal cheap-worker path.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--validation-command",
        action="append",
        required=True,
        help="Exact validation command approved by the caller; repeat when needed.",
    )
    parser.add_argument("--objective", default="Probe LoopX planner-worker mode with TraeX.")
    parser.add_argument(
        "--task-instruction",
        default=(
            "Given a small LoopX planner-worker feature request, produce a compact "
            "implementation plan and then execute the first plan step as a patch-level answer."
        ),
    )
    args = parser.parse_args(argv)
    payload = run_traex_planner_worker_probe(
        objective=args.objective,
        task_instruction=args.task_instruction,
        traex_bin=args.traex_bin,
        planner_model=args.planner_model,
        worker_model=args.worker_model,
        cwd=Path(args.cwd),
        worker_minimal_context=not args.full_worker_context,
        approved_validation_commands=tuple(args.validation_command),
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
