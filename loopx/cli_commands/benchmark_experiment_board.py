from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..capabilities.benchmark_toolkit import (
    build_benchmark_experiment_board,
    default_benchmark_experiment_board_path,
    preview_benchmark_experiment_board_upsert,
    read_benchmark_experiment_board_rows,
    render_benchmark_experiment_board_markdown,
    upsert_benchmark_experiment_board_row,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]], None
]
OutputFormat = Callable[[argparse.Namespace], str]

BENCHMARK_EXPERIMENT_BOARD_COMMANDS = {
    "experiment-board-show",
    "experiment-board-upsert",
}


def _read_json_object(path_text: str) -> dict[str, Any]:
    raw = (
        sys.stdin.read()
        if path_text == "-"
        else Path(path_text).expanduser().read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("benchmark experiment board row must be an object")
    return payload


def _add_board_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goal-id", required=True)
    parser.add_argument(
        "--project",
        help="Explicit project root. Defaults to the registry goal repository.",
    )
    parser.add_argument("--benchmark-id")
    parser.add_argument("--study-id")
    parser.set_defaults(benchmark_experiment_board_parser=parser)


def register_benchmark_experiment_board_commands(
    benchmark_subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    show_parser = benchmark_subparsers.add_parser(
        "experiment-board-show",
        help="Read the project-local public-safe benchmark experiment board.",
    )
    add_subcommand_format(show_parser)
    _add_board_location_arguments(show_parser)

    upsert_parser = benchmark_subparsers.add_parser(
        "experiment-board-upsert",
        help="Preview or upsert one compact benchmark run row into the experiment board.",
    )
    add_subcommand_format(upsert_parser)
    _add_board_location_arguments(upsert_parser)
    upsert_parser.add_argument(
        "--row-json",
        required=True,
        help="Compact benchmark_experiment_board_row_v0 JSON path, or - for stdin.",
    )
    upsert_parser.add_argument(
        "--execute",
        action="store_true",
        help="Write project-local domain state. Without this flag, preview only.",
    )


def _board_payload(
    *,
    rows: list[dict[str, Any]],
    benchmark_id: str | None,
    study_id: str | None,
) -> dict[str, Any]:
    return build_benchmark_experiment_board(
        rows,
        benchmark_id=benchmark_id,
        study_id=study_id,
    )


def handle_benchmark_experiment_board_command(
    args: argparse.Namespace,
    *,
    project: Path | None,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.benchmark_command not in BENCHMARK_EXPERIMENT_BOARD_COMMANDS:
        return None

    try:
        if project is None:
            raise ValueError("benchmark project route is required")
        ledger_path = default_benchmark_experiment_board_path(
            project=project,
            goal_id=args.goal_id,
        )
        rows = read_benchmark_experiment_board_rows(ledger_path)
        write: dict[str, Any] | None = None
        if args.benchmark_command == "experiment-board-upsert":
            row = _read_json_object(args.row_json)
            if args.execute:
                receipt = upsert_benchmark_experiment_board_row(ledger_path, row)
                rows = read_benchmark_experiment_board_rows(ledger_path)
                write = {
                    **receipt["write"],
                    "dry_run": False,
                }
            else:
                rows, preview_status = preview_benchmark_experiment_board_upsert(
                    rows, row
                )
                write = {
                    "status": f"preview_{preview_status}",
                    "write_performed": False,
                    "row_count": len(rows),
                    "path_recorded": False,
                    "dry_run": True,
                }
        payload = _board_payload(
            rows=rows,
            benchmark_id=args.benchmark_id,
            study_id=args.study_id,
        )
        payload["goal_id"] = args.goal_id
        payload["path_recorded"] = False
        if write is not None:
            payload["write"] = write
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        args.benchmark_experiment_board_parser.error(
            "invalid benchmark experiment board input"
        )
    print_payload(
        payload, output_format(args), render_benchmark_experiment_board_markdown
    )
    return 0
