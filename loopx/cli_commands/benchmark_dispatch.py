from __future__ import annotations

import argparse
from collections.abc import Callable

from .benchmark_boundary import (
    handle_benchmark_boundary_command,
    register_benchmark_boundary_commands,
)

AddSubcommandFormat = Callable[[argparse.ArgumentParser], None]
OutputFormat = Callable[..., str]
PrintPayload = Callable[..., None]


def register_benchmark_command_group(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddSubcommandFormat,
) -> None:
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Provider-neutral benchmark integrity and evidence boundaries.",
    )
    benchmark_sub = benchmark_parser.add_subparsers(
        dest="benchmark_command",
        required=True,
    )
    register_benchmark_boundary_commands(benchmark_sub, add_subcommand_format)


def handle_benchmark_command(
    args: argparse.Namespace,
    *,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.command != "benchmark":
        return None
    return handle_benchmark_boundary_command(
        args,
        print_payload=print_payload,
        output_format=output_format,
    )
