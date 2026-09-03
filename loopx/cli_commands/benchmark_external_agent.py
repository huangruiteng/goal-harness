"""CLI entrypoint for one external benchmark agent phase."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from ..capabilities.benchmark_toolkit.external_agent import (
    BENCHMARK_CONTINUATION_DECISION_SCHEMA_VERSION,
    build_benchmark_continuation_decision,
    execute_external_agent_request,
)

BENCHMARK_EXTERNAL_AGENT_COMMANDS = {"agent-phase", "continuation-decision"}

PrintPayload = Callable[..., None]
OutputFormat = Callable[..., str]


def _render_external_agent_result(payload: dict[str, object]) -> str:
    receipt = payload.get("receipt")
    receipt_mapping = receipt if isinstance(receipt, dict) else {}
    return (
        "# External Agent Phase\n\n"
        f"- Status: `{payload.get('status')}`\n"
        f"- Classification: `{receipt_mapping.get('classification')}`\n"
        f"- Exit code: `{payload.get('exit_code')}`\n"
    )


def _render_continuation_decision(payload: dict[str, object]) -> str:
    return (
        "# Benchmark Continuation Decision\n\n"
        f"- Decision: `{payload.get('decision')}`\n"
        f"- Reason: `{payload.get('reason_code')}`\n"
        f"- Continue: `{payload.get('continuation_allowed')}`\n"
        f"- Next segment timeout: `{payload.get('next_segment_timeout_ms')}` ms\n"
    )


def _read_json_object(path_text: str) -> dict[str, object]:
    raw = (
        sys.stdin.read()
        if path_text == "-"
        else Path(path_text).expanduser().read_text(encoding="utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("progress JSON must contain an object")
    return value


def _invalid_continuation_decision() -> dict[str, object]:
    return {
        "ok": False,
        "schema_version": BENCHMARK_CONTINUATION_DECISION_SCHEMA_VERSION,
        "decision": "input_invalid",
        "reason_code": "continuation_input_invalid",
        "continuation_allowed": False,
        "next_segment_timeout_ms": 0,
        "first_prompt_matches": False,
        "task_shape_matches": False,
        "first_prompt_digest_recorded": False,
        "public_progress_only": True,
        "raw_task_recorded": False,
        "unit_ids_recorded": False,
        "path_recorded": False,
        "read_only": True,
        "host_invoked": False,
        "state_written": False,
    }


def register_benchmark_external_agent_commands(
    benchmark_subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = benchmark_subparsers.add_parser(
        "agent-phase",
        help=(
            "Run one external-agent request without taking task, verifier, or score "
            "authority."
        ),
    )
    add_subcommand_format(parser)
    parser.add_argument(
        "--request",
        default=os.environ.get("LOOPSBENCH_EXTERNAL_AGENT_REQUEST"),
        help="External-agent request JSON; defaults to LOOPSBENCH_EXTERNAL_AGENT_REQUEST.",
    )
    parser.add_argument(
        "--result",
        default=os.environ.get("LOOPSBENCH_EXTERNAL_AGENT_RESULT"),
        help="External-agent result JSON; defaults to LOOPSBENCH_EXTERNAL_AGENT_RESULT.",
    )
    parser.add_argument(
        "--solver-command-json",
        default=os.environ.get("LOOPX_EXTERNAL_AGENT_SOLVER_COMMAND_JSON"),
        help=(
            "Runner-owned solver argv JSON; defaults to "
            "LOOPX_EXTERNAL_AGENT_SOLVER_COMMAND_JSON."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the solver command. Without this flag, validate the request only.",
    )
    parser.set_defaults(benchmark_external_agent_parser=parser)

    continuation_parser = benchmark_subparsers.add_parser(
        "continuation-decision",
        help="Decide whether another benchmark agent segment fits a frozen envelope.",
    )
    add_subcommand_format(continuation_parser)
    continuation_parser.add_argument("--progress-json", required=True)
    continuation_parser.add_argument("--expected-first-prompt-sha256", required=True)
    continuation_parser.add_argument("--observed-first-prompt-sha256", required=True)
    continuation_parser.add_argument(
        "--expected-total-unit-count", required=True, type=int
    )
    continuation_parser.add_argument(
        "--previous-completed-unit-count", required=True, type=int
    )
    continuation_parser.add_argument(
        "--completed-segment-count", required=True, type=int
    )
    continuation_parser.add_argument("--max-agent-segments", required=True, type=int)
    continuation_parser.add_argument("--elapsed-ms", required=True, type=int)
    continuation_parser.add_argument("--total-budget-ms", required=True, type=int)
    continuation_parser.set_defaults(
        benchmark_external_agent_parser=continuation_parser
    )


def handle_benchmark_external_agent_command(
    args: argparse.Namespace,
    *,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.benchmark_command not in BENCHMARK_EXTERNAL_AGENT_COMMANDS:
        return None
    parser: argparse.ArgumentParser = args.benchmark_external_agent_parser
    if args.benchmark_command == "continuation-decision":
        try:
            payload = build_benchmark_continuation_decision(
                _read_json_object(args.progress_json),
                expected_first_prompt_sha256=args.expected_first_prompt_sha256,
                observed_first_prompt_sha256=args.observed_first_prompt_sha256,
                expected_total_unit_count=args.expected_total_unit_count,
                previous_completed_unit_count=args.previous_completed_unit_count,
                completed_segment_count=args.completed_segment_count,
                max_agent_segments=args.max_agent_segments,
                elapsed_ms=args.elapsed_ms,
                total_budget_ms=args.total_budget_ms,
            )
        except (OSError, UnicodeError, TypeError, ValueError):
            payload = _invalid_continuation_decision()
        print_payload(payload, output_format(args), _render_continuation_decision)
        return 0 if payload.get("ok") else 1

    if not args.request or not args.result or not args.solver_command_json:
        parser.error(
            "agent-phase requires --request, --result, and --solver-command-json "
            "(or their documented environment variables)"
        )
    try:
        command = json.loads(args.solver_command_json)
    except json.JSONDecodeError:
        parser.error("--solver-command-json must be a JSON argv array")
    if not isinstance(command, list):
        parser.error("--solver-command-json must be a JSON argv array")

    result = execute_external_agent_request(
        request_path=Path(args.request),
        result_path=Path(args.result),
        solver_command=command,
        execute=args.execute,
    )
    print_payload(result, output_format(args), _render_external_agent_result)
    return 0 if result["status"] == "succeeded" else 1
