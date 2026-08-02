from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..benchmark_adapters.agents_last_exam import (
    build_agents_last_exam_result_benchmark_report,
)
from ..benchmarks.read_models.benchmark_comparison import (
    compact_benchmark_comparison,
)
from ..benchmarks.read_models.benchmark_experiment_report import (
    compact_benchmark_experiment_report,
)
from ..benchmarks.read_models.benchmark_learning_ledger import (
    compact_benchmark_learning_ledger,
)
from ..benchmarks.read_models.benchmark_result import compact_benchmark_result
from ..control_plane.work_items.delivery_batch_scale import DELIVERY_BATCH_SCALE_CHOICES
from ..control_plane.work_items.delivery_outcome import DELIVERY_OUTCOME_CHOICES
from ..control_plane.runtime.active_user_assisted_pilot import (
    compact_active_user_assisted_pilot,
)
from ..control_plane.runtime.trajectory_hygiene import build_trajectory_hygiene_summary
from ..global_registry import sync_project_registry_to_global
from ..history import (
    append_active_user_assisted_pilot,
    append_benchmark_comparison,
    append_benchmark_experiment_report,
    append_benchmark_learning_ledger,
    append_benchmark_result,
    append_benchmark_run,
    collect_history,
    inspect_index_duplicates,
    load_registry,
    repair_index_duplicates,
    rebuild_index_artifact_collisions,
    render_active_user_assisted_pilot_append_markdown,
    render_benchmark_comparison_append_markdown,
    render_benchmark_experiment_report_append_markdown,
    render_benchmark_learning_ledger_append_markdown,
    render_benchmark_result_append_markdown,
    render_benchmark_run_append_markdown,
    render_history_markdown,
    render_index_duplicate_inspection_markdown,
    render_index_duplicate_repair_markdown,
    render_index_collision_rebuild_markdown,
)
from ..paths import resolve_runtime_root
from ..presentation.renderers.trajectory_hygiene_markdown import (
    render_trajectory_hygiene_markdown,
)
from ..status import compact_benchmark_run


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
BenchmarkRolloutEventAppender = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class _HistoryAppendSpec:
    action: str
    input_attr: str
    input_option: str
    schema_name: str
    payload_key: str
    default_classification: str
    compact: Callable[..., dict[str, object]]
    append: Callable[..., dict[str, object]]
    render: Callable[..., str]


_HISTORY_JSON_APPEND_SPECS = {
    spec.action: spec
    for spec in (
        _HistoryAppendSpec(
            action="append-benchmark-run",
            input_attr="benchmark_run_json",
            input_option="--benchmark-run-json",
            schema_name="benchmark_run_v0",
            payload_key="benchmark_run",
            default_classification="benchmark_run_v0",
            compact=compact_benchmark_run,
            append=append_benchmark_run,
            render=render_benchmark_run_append_markdown,
        ),
        _HistoryAppendSpec(
            action="append-benchmark-result",
            input_attr="benchmark_result_json",
            input_option="--benchmark-result-json",
            schema_name="benchmark_result_v0",
            payload_key="benchmark_result",
            default_classification="benchmark_result_v0",
            compact=compact_benchmark_result,
            append=append_benchmark_result,
            render=render_benchmark_result_append_markdown,
        ),
        _HistoryAppendSpec(
            action="append-benchmark-comparison",
            input_attr="benchmark_comparison_json",
            input_option="--benchmark-comparison-json",
            schema_name="benchmark_comparison_v0",
            payload_key="benchmark_comparison",
            default_classification="benchmark_comparison_v0",
            compact=compact_benchmark_comparison,
            append=append_benchmark_comparison,
            render=render_benchmark_comparison_append_markdown,
        ),
        _HistoryAppendSpec(
            action="append-benchmark-learning-ledger",
            input_attr="benchmark_learning_ledger_json",
            input_option="--benchmark-learning-ledger-json",
            schema_name="benchmark_learning_ledger_v0",
            payload_key="benchmark_learning_ledger",
            default_classification="benchmark_learning_ledger_v0",
            compact=compact_benchmark_learning_ledger,
            append=append_benchmark_learning_ledger,
            render=render_benchmark_learning_ledger_append_markdown,
        ),
        _HistoryAppendSpec(
            action="append-benchmark-report",
            input_attr="benchmark_report_json",
            input_option="--benchmark-report-json",
            schema_name="benchmark_experiment_report_v0",
            payload_key="benchmark_experiment_report",
            default_classification="benchmark_experiment_report_v0",
            compact=compact_benchmark_experiment_report,
            append=append_benchmark_experiment_report,
            render=render_benchmark_experiment_report_append_markdown,
        ),
        _HistoryAppendSpec(
            action="append-active-user-assisted-pilot",
            input_attr="active_user_pilot_json",
            input_option="--active-user-pilot-json",
            schema_name="active_user_assisted_pilot_v0",
            payload_key="active_user_assisted_pilot",
            default_classification="active_user_assisted_pilot_v0",
            compact=compact_active_user_assisted_pilot,
            append=append_active_user_assisted_pilot,
            render=render_active_user_assisted_pilot_append_markdown,
        ),
    )
}


def _validate_append_request(args: argparse.Namespace, action: str) -> None:
    if args.dry_run and args.execute:
        raise ValueError(
            f"history {action} accepts either --dry-run or --execute, not both"
        )
    if not args.goal_id:
        raise ValueError(f"history {action} requires --goal-id")


def _load_compact_history_input(
    args: argparse.Namespace,
    spec: _HistoryAppendSpec,
) -> dict[str, object]:
    input_path = getattr(args, spec.input_attr)
    if not input_path:
        raise ValueError(f"history {spec.action} requires {spec.input_option}")
    raw_input = json.loads(
        sys.stdin.read()
        if input_path == "-"
        else Path(input_path).expanduser().read_text(encoding="utf-8")
    )
    if not isinstance(raw_input, dict):
        raise ValueError(f"{spec.input_option} must contain a JSON object")
    compacted = spec.compact(raw_input)
    if not compacted:
        raise ValueError(
            f"{spec.input_option} did not contain a compactable {spec.schema_name} object"
        )
    return compacted


def _history_global_sync(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    dry_run: bool,
) -> dict[str, object]:
    if args.no_global_sync:
        return {
            "ok": True,
            "dry_run": dry_run,
            "skipped": True,
            "reason": "disabled by --no-global-sync",
        }
    return sync_project_registry_to_global(
        registry_path=registry_path,
        runtime_root_override=runtime_root_arg,
        goal_id=args.goal_id,
        dry_run=dry_run,
    )


def _append_history_record(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    spec: _HistoryAppendSpec,
    record: dict[str, object],
    default_classification: str | None = None,
    rollout_event: BenchmarkRolloutEventAppender | None = None,
) -> dict[str, object]:
    dry_run = not bool(args.execute)
    payload = spec.append(
        registry_path=registry_path,
        runtime_root_override=runtime_root_arg,
        goal_id=args.goal_id,
        **{spec.payload_key: record},
        classification=(
            args.classification or default_classification or spec.default_classification
        ),
        recommended_action=args.recommended_action,
        delivery_batch_scale=args.delivery_batch_scale,
        delivery_outcome=args.delivery_outcome,
        dry_run=dry_run,
    )
    payload["global_sync"] = _history_global_sync(
        args,
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        dry_run=dry_run,
    )
    if rollout_event is not None:
        rollout_event(
            payload,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            command="history",
            action=spec.action,
        )
    return payload


def _history_append_error(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    classification: str,
    error: Exception,
) -> dict[str, object]:
    return {
        "ok": False,
        "dry_run": not bool(args.execute),
        "appended": False,
        "registry": str(registry_path),
        "runtime_root": runtime_root_arg,
        "goal_id": args.goal_id,
        "classification": args.classification or classification,
        "error": str(error),
    }


def _handle_json_history_append(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    print_payload: PrintPayload,
    spec: _HistoryAppendSpec,
    rollout_event: BenchmarkRolloutEventAppender | None,
) -> int:
    try:
        _validate_append_request(args, spec.action)
        payload = _append_history_record(
            args,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            spec=spec,
            record=_load_compact_history_input(args, spec),
            rollout_event=rollout_event,
        )
    except Exception as exc:
        payload = _history_append_error(
            args,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            classification=spec.default_classification,
            error=exc,
        )
    print_payload(payload, args.format, spec.render)
    return 0 if payload.get("ok") else 1


def register_history_command(subparsers: argparse._SubParsersAction) -> None:
    history_parser = subparsers.add_parser(
        "history",
        help="Read compact run history from the shared runtime root.",
    )
    history_parser.add_argument(
        "history_action",
        nargs="?",
        choices=[
            "append-benchmark-run",
            "append-benchmark-result",
            "append-benchmark-comparison",
            "append-benchmark-learning-ledger",
            "append-benchmark-report",
            "append-agents-last-exam-result-report",
            "append-active-user-assisted-pilot",
            "inspect-index-duplicates",
            "repair-index-duplicates",
            "rebuild-index-collisions",
            "trajectory-hygiene",
        ],
        help=(
            "Append a compact benchmark_run_v0, benchmark_result_v0, benchmark_comparison_v0, "
            "benchmark_learning_ledger_v0, benchmark_experiment_report_v0, ALE compact result report, or "
            "active_user_assisted_pilot_v0 event; inspect duplicate run-index identities; "
            "repair safe duplicate index rows; rebuild reviewed artifact collisions without deleting events; "
            "or audit compact-history trajectory hygiene."
        ),
    )
    history_parser.add_argument("--goal-id", help="Only show one goal.")
    history_parser.add_argument("--limit", type=int, default=10)
    history_parser.add_argument(
        "--benchmark-run-json",
        help="Path to a benchmark_run_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--benchmark-result-json",
        help="Path to a benchmark_result_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--benchmark-comparison-json",
        help="Path to a benchmark_comparison_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--benchmark-learning-ledger-json",
        help="Path to a benchmark_learning_ledger_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--benchmark-report-json",
        help="Path to a benchmark_experiment_report_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--agents-last-exam-run-dir",
        help=(
            "Path to an existing Agents' Last Exam run directory. The ingest reads "
            "only run.json, eval_result.json, and events.jsonl; raw trajectory, "
            "origin_log, output, task bodies, screenshots, credentials, and local "
            "absolute paths are excluded."
        ),
    )
    history_parser.add_argument(
        "--report-id",
        help="Optional public-safe report id for append-agents-last-exam-result-report.",
    )
    history_parser.add_argument(
        "--active-user-pilot-json",
        help="Path to an active_user_assisted_pilot_v0 JSON object. Use '-' to read stdin.",
    )
    history_parser.add_argument(
        "--review-plan-json",
        help=(
            "For rebuild-index-collisions --execute, a JSON review plan emitted by the dry-run. "
            "Use '-' to read stdin."
        ),
    )
    history_parser.add_argument("--classification")
    history_parser.add_argument(
        "--recommended-action",
        help="Recommended next action for the compact append event.",
    )
    history_parser.add_argument(
        "--delivery-batch-scale",
        choices=DELIVERY_BATCH_SCALE_CHOICES,
        help="Optional delivery scale label for the run index.",
    )
    history_parser.add_argument(
        "--delivery-outcome",
        choices=DELIVERY_OUTCOME_CHOICES,
        help="Optional delivery outcome label for the run index.",
    )
    history_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview append without writing. This is the default.",
    )
    history_parser.add_argument(
        "--execute",
        action="store_true",
        help="Append or repair. Without this flag, history write actions are dry-run previews.",
    )
    history_parser.add_argument(
        "--no-global-sync",
        action="store_true",
        help="Skip global registry sync after append.",
    )


def handle_history_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    print_payload: PrintPayload,
    append_benchmark_run_rollout_event: BenchmarkRolloutEventAppender,
    append_benchmark_result_rollout_event: BenchmarkRolloutEventAppender,
) -> int:
    if args.history_action == "trajectory-hygiene":
        try:
            if not args.goal_id:
                raise ValueError("history trajectory-hygiene requires --goal-id")
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(
                registry,
                runtime_root_arg,
                registry_path=registry_path,
            )
            history = collect_history(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                limit=max(0, args.limit),
            )
            payload = build_trajectory_hygiene_summary(history)
            payload["registry"] = str(registry_path)
            payload["runtime_root"] = str(runtime_root)
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": runtime_root_arg,
                "goal_filter": args.goal_id,
                "error": str(exc),
            }
        print_payload(payload, args.format, render_trajectory_hygiene_markdown)
        return 0 if payload.get("ok") else 1

    if args.history_action == "inspect-index-duplicates":
        try:
            payload = inspect_index_duplicates(
                registry_path=registry_path,
                runtime_root_override=runtime_root_arg,
                goal_id=args.goal_id,
                limit=args.limit,
            )
        except Exception as exc:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(
                registry,
                runtime_root_arg,
                registry_path=registry_path,
            )
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": str(runtime_root),
                "goal_filter": args.goal_id,
                "error": str(exc),
            }
        print_payload(payload, args.format, render_index_duplicate_inspection_markdown)
        return 0 if payload.get("ok") else 1

    if args.history_action == "repair-index-duplicates":
        try:
            payload = repair_index_duplicates(
                registry_path=registry_path,
                runtime_root_override=runtime_root_arg,
                goal_id=args.goal_id,
                limit=args.limit,
                execute=bool(args.execute),
            )
        except Exception as exc:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(
                registry,
                runtime_root_arg,
                registry_path=registry_path,
            )
            payload = {
                "ok": False,
                "dry_run": not bool(args.execute),
                "registry": str(registry_path),
                "runtime_root": str(runtime_root),
                "goal_filter": args.goal_id,
                "error": str(exc),
            }
        print_payload(payload, args.format, render_index_duplicate_repair_markdown)
        return 0 if payload.get("ok") else 1

    if args.history_action == "rebuild-index-collisions":
        try:
            if args.dry_run and args.execute:
                raise ValueError(
                    "history rebuild-index-collisions accepts either --dry-run or --execute, not both"
                )
            reviewed_plan = None
            if args.review_plan_json:
                raw_plan = (
                    sys.stdin.read()
                    if args.review_plan_json == "-"
                    else Path(args.review_plan_json)
                    .expanduser()
                    .read_text(encoding="utf-8")
                )
                reviewed_plan = json.loads(raw_plan)
                if not isinstance(reviewed_plan, dict):
                    raise ValueError("--review-plan-json must contain a JSON object")
            payload = rebuild_index_artifact_collisions(
                registry_path=registry_path,
                runtime_root_override=runtime_root_arg,
                goal_id=args.goal_id,
                limit=args.limit,
                reviewed_plan=reviewed_plan,
                execute=bool(args.execute),
            )
        except Exception as exc:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(
                registry,
                runtime_root_arg,
                registry_path=registry_path,
            )
            payload = {
                "ok": False,
                "dry_run": not bool(args.execute),
                "registry": str(registry_path),
                "runtime_root": str(runtime_root),
                "goal_filter": args.goal_id,
                "error": str(exc),
            }
        print_payload(payload, args.format, render_index_collision_rebuild_markdown)
        return 0 if payload.get("ok") else 1

    append_spec = _HISTORY_JSON_APPEND_SPECS.get(args.history_action)
    if append_spec is not None:
        rollout_event = {
            "append-benchmark-run": append_benchmark_run_rollout_event,
            "append-benchmark-result": append_benchmark_result_rollout_event,
        }.get(append_spec.action)
        return _handle_json_history_append(
            args,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            print_payload=print_payload,
            spec=append_spec,
            rollout_event=rollout_event,
        )

    if args.history_action == "append-agents-last-exam-result-report":
        try:
            action = "append-agents-last-exam-result-report"
            _validate_append_request(args, action)
            if not args.agents_last_exam_run_dir:
                raise ValueError(
                    f"history {action} requires --agents-last-exam-run-dir"
                )
            benchmark_report_input = build_agents_last_exam_result_benchmark_report(
                Path(args.agents_last_exam_run_dir).expanduser(),
                report_id=args.report_id,
            )
            benchmark_report = compact_benchmark_experiment_report(
                benchmark_report_input
            )
            if not benchmark_report:
                raise ValueError(
                    "--agents-last-exam-run-dir did not produce a compactable benchmark_experiment_report_v0 object"
                )
            payload = _append_history_record(
                args,
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                spec=_HISTORY_JSON_APPEND_SPECS["append-benchmark-report"],
                record=benchmark_report,
                default_classification="agents_last_exam_result_report_v0",
            )
            payload["benchmark_report_source"] = {
                "kind": "agents_last_exam_run_dir",
                "raw_surfaces_excluded": True,
                "raw_surface_content_recorded": False,
                "local_paths_recorded": False,
            }
        except Exception as exc:
            payload = _history_append_error(
                args,
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                classification="agents_last_exam_result_report_v0",
                error=exc,
            )
        print_payload(
            payload, args.format, render_benchmark_experiment_report_append_markdown
        )
        return 0 if payload.get("ok") else 1

    try:
        registry = load_registry(registry_path)
        runtime_root = resolve_runtime_root(
            registry,
            runtime_root_arg,
            registry_path=registry_path,
        )
        payload = collect_history(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=args.goal_id,
            limit=max(0, args.limit),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "registry": str(registry_path),
            "runtime_root": runtime_root_arg,
            "error": str(exc),
        }
    print_payload(payload, args.format, render_history_markdown)
    return 0 if payload.get("ok") else 1
