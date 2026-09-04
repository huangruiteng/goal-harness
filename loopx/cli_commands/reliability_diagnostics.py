"""Owner-local CLI readback for the reliability-diagnostics ledger."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..capabilities.reliability_diagnostics import (
    CAPABILITY_ID,
    OBSERVER_STATS_SCHEMA_VERSION,
    ClockSource,
    ShadowObserverIntake,
    append_ledger_records,
    build_diagnostic_projection,
    build_integrity_receipt,
    ledger_path,
    ledger_ref,
    normalize_observer_stats,
    parse_ndjson_lines,
    read_ledger,
    read_ledger_records,
)
from ..history import load_registry
from ..paths import resolve_runtime_root

PrintPayload = Callable[[dict[str, Any], str, Callable[[dict[str, Any]], str]], str | None]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]

INGEST_OBSERVER_ID = "loopx-cli-ingest"
INGEST_BUFFER_BOUND = 4096


def register_reliability_diagnostics_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "reliability-diagnostics",
        help="Read back the L1 shadow-observer ledger: ingest, receipt, status.",
    )
    commands = parser.add_subparsers(dest="reliability_diagnostics_command", required=True)
    ingest = commands.add_parser(
        "ingest",
        help="Validate observer envelopes and append accepted ones to the goal ledger.",
    )
    add_subcommand_format(ingest)
    ingest.add_argument("--goal-id", required=True)
    ingest.add_argument("--input", required=True, help="NDJSON file path, or - for stdin.")
    receipt = commands.add_parser("receipt", help="Render the treatment-integrity receipt.")
    add_subcommand_format(receipt)
    receipt.add_argument("--goal-id", required=True)
    status = commands.add_parser("status", help="Render the read-only diagnostic projection.")
    add_subcommand_format(status)
    status.add_argument("--goal-id", required=True)
    status.add_argument("--as-of", help="Timezone-aware ISO-8601 time used for stall age.")


def _render(payload: dict[str, Any]) -> str:
    lines = [f"# Reliability Diagnostics ({payload.get('command')})", ""]
    for key in ("goal_id", "ledger_ref", "appended_record_count", "rejected_by_reason"):
        if key in payload:
            lines.append(f"- {key}: `{payload[key]}`")
    for section in ("receipt", "projection"):
        body = payload.get(section)
        if isinstance(body, dict):
            lines.append(f"- {section}.status: `{body.get('status') or body.get('integrity', {}).get('status')}`")
            for key in ("stage", "signals", "reason_codes", "lost_event_count", "backpressure_drop_count"):
                if key in body:
                    lines.append(f"- {section}.{key}: `{body[key]}`")
    return "\n".join(lines) + "\n"


def _ingest(path: Path, goal_id: str, source: str) -> dict[str, Any]:
    if source == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(source).expanduser().read_text(encoding="utf-8").splitlines()
    parsed, malformed = parse_ndjson_lines(lines)
    intake = ShadowObserverIntake(
        provider_id="loopx-core",
        observer_id=INGEST_OBSERVER_ID,
        goal_id=goal_id,
        clock_source=ClockSource.OBSERVER_WALL_CLOCK,
        buffer_bound=INGEST_BUFFER_BOUND,
    )
    appended = 0
    passthrough_stats = 0
    for record in parsed:
        if isinstance(record, dict) and record.get("schema_version") == OBSERVER_STATS_SCHEMA_VERSION:
            try:
                stats = normalize_observer_stats(record)
            except ValueError:
                malformed += 1
                continue
            if stats.goal_id != goal_id:
                malformed += 1
                continue
            appended += append_ledger_records(path, [stats.as_dict()])
            passthrough_stats += 1
            continue
        intake.observe(record)
        if intake.buffered_count >= INGEST_BUFFER_BOUND:
            appended += len(intake.flush(lambda records: append_ledger_records(path, records[:-1]), emitted_at=_now()))
    appended += len(intake.flush(lambda records: append_ledger_records(path, records[:-1]), emitted_at=_now()))
    stats_record = intake.stats(emitted_at=_now())
    # A clean ingest is a transparent copy of the observer output. The ingest
    # gate records itself only when it refused, dropped, or failed something,
    # so that violation stays durable and visible in the receipt.
    gate_recorded = bool(
        stats_record.rejected_event_count
        or stats_record.backpressure_drop_count
        or stats_record.observer_failure_count
    )
    if gate_recorded:
        appended += append_ledger_records(path, [stats_record.as_dict()])
    return {
        "ok": True,
        "command": "ingest",
        "goal_id": goal_id,
        "ledger_ref": ledger_ref(goal_id),
        "appended_record_count": appended,
        "accepted_envelope_count": stats_record.accepted_event_count,
        "passthrough_stats_count": passthrough_stats,
        "rejected_event_count": stats_record.rejected_event_count,
        "rejected_by_reason": dict(stats_record.rejected_by_reason),
        "malformed_line_count": malformed,
        "observer_failure_count": stats_record.observer_failure_count,
        "ingest_gate_recorded": gate_recorded,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def handle_reliability_diagnostics_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "reliability-diagnostics":
        return None
    goal_id = str(args.goal_id)
    runtime_root = resolve_runtime_root(
        load_registry(registry_path) if registry_path.is_file() else {},
        runtime_root_arg,
        registry_path=registry_path,
    )
    try:
        path = ledger_path(runtime_root, goal_id)
        command = args.reliability_diagnostics_command
        if command == "ingest":
            payload = _ingest(path, goal_id, str(args.input))
        else:
            records, malformed = read_ledger_records(path)
            reading = read_ledger(records, goal_id=goal_id, malformed_line_count=malformed)
            payload = {"ok": True, "command": command, "goal_id": goal_id, "ledger_ref": ledger_ref(goal_id)}
            if command == "receipt":
                payload["receipt"] = build_integrity_receipt(reading)
            else:
                payload["projection"] = build_diagnostic_projection(reading, as_of=args.as_of)
    except (OSError, ValueError) as exc:
        print(f"error: {CAPABILITY_ID}: {exc}", file=sys.stderr)
        return 2
    print_payload(payload, output_format(args), _render)
    return 0
