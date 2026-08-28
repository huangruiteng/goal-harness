"""CLI entrypoint for one external benchmark agent phase."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path

from ..capabilities.benchmark_toolkit.external_agent import (
    execute_external_agent_request,
)

BENCHMARK_EXTERNAL_AGENT_COMMANDS = {"agent-phase"}

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


def handle_benchmark_external_agent_command(
    args: argparse.Namespace,
    *,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.benchmark_command not in BENCHMARK_EXTERNAL_AGENT_COMMANDS:
        return None
    parser: argparse.ArgumentParser = args.benchmark_external_agent_parser
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
