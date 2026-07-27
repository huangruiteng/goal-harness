#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.traex_planner_worker import (  # noqa: E402
    DEFAULT_TRAEX_PLANNER_MODEL,
    DEFAULT_TRAEX_WORKER_MODEL,
    build_synthetic_planner_worker_plan,
    run_traex_planner_worker_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only TraeX planner-worker probe.")
    parser.add_argument("--traex-bin", default="traex")
    parser.add_argument("--planner-model", default=DEFAULT_TRAEX_PLANNER_MODEL)
    parser.add_argument("--worker-model", default=DEFAULT_TRAEX_WORKER_MODEL)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--worker-cwd")
    parser.add_argument(
        "--full-worker-context",
        action="store_true",
        help="Load normal TraeX user/project context for the worker instead of the minimal cheap-worker path.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--objective", default="Probe LoopX planner-worker mode with TraeX.")
    parser.add_argument(
        "--task-instruction",
        default=(
            "Given a small LoopX planner-worker feature request, produce a compact "
            "implementation plan and then execute the first plan step as a patch-level answer."
        ),
    )
    args = parser.parse_args(argv)
    plan = build_synthetic_planner_worker_plan(objective=args.objective)
    payload = run_traex_planner_worker_probe(
        objective=args.objective,
        task_instruction=args.task_instruction,
        planner_output_plan=plan,
        traex_bin=args.traex_bin,
        planner_model=args.planner_model,
        worker_model=args.worker_model,
        cwd=Path(args.cwd),
        worker_cwd=Path(args.worker_cwd) if args.worker_cwd else None,
        worker_minimal_context=not args.full_worker_context,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
