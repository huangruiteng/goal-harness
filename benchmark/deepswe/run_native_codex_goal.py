#!/usr/bin/env python3
"""Run the same native Codex Goal transaction used by benchmark adapters."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.benchmark_toolkit.native_codex_goal import (
    NativeGoalConfig,
    compact_native_goal_receipt,
    probe_native_goal_process,
    run_native_goal_process,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to a real `codex app-server`, attach an active Goal, and "
            "optionally run one complete task turn."
        )
    )
    parser.add_argument("--cwd", required=True, help="Task-visible working directory")
    parser.add_argument(
        "--objective-file",
        required=True,
        help="UTF-8 file containing the native Goal objective",
    )
    parser.add_argument(
        "--task-file",
        required=True,
        help="UTF-8 file containing the task instruction",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--response-timeout-seconds", type=float, default=30)
    parser.add_argument("--goal-timeout-seconds", type=float, default=21_600)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Prove initialize/thread/Goal attachment without starting a model turn",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = NativeGoalConfig(
        cwd=args.cwd,
        objective=Path(args.objective_file).read_text(encoding="utf-8"),
        task_instruction=Path(args.task_file).read_text(encoding="utf-8"),
        model=args.model,
        effort=args.effort,
        token_budget=args.token_budget,
    )
    if args.preflight_only:
        turn = probe_native_goal_process(
            config,
            codex_bin=args.codex_bin,
            response_timeout_sec=args.response_timeout_seconds,
        )
        mode = "goal_attachment_preflight"
    else:
        turn = run_native_goal_process(
            config,
            codex_bin=args.codex_bin,
            response_timeout_sec=args.response_timeout_seconds,
            goal_timeout_sec=args.goal_timeout_seconds,
        )
        mode = "complete_goal_turn"
    receipt = compact_native_goal_receipt(turn)
    receipt["execution_mode"] = mode
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
