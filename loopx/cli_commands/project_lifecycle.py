from __future__ import annotations

import argparse
from importlib import import_module
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..capabilities.explore.activation import (
    sync_explore_graph_after_material_refresh,
)
from ..control_plane.agents.capability_gate import (
    runtime_capabilities_for_cli_projection,
)
from ..control_plane.goals.goal_vision_policy import (
    GOAL_VISION_ADVANCEMENT_POLICY_CHOICES,
)
from ..control_plane.quota.settlement import (
    require_settlement_writeback,
    resolve_heartbeat_settlement_identity,
    settlement_result_payload,
)
from ..control_plane.work_items.delivery_batch_scale import (
    DELIVERY_BATCH_SCALE_INPUT_CHOICES,
)
from ..control_plane.work_items.delivery_outcome import DELIVERY_OUTCOME_CHOICES
from ..extensions.runtime import (
    default_extension_state_file,
    resolve_extension_activation,
)
from ..extensions.lark.goal_channel_lifecycle import (
    goal_channel_gate_sync_failure,
    sync_human_gate_after_refresh,
)
from ..history import load_registry
from ..feedback import LESSON_KINDS, append_human_reward, compact_reward, render_reward_markdown
from ..operator_gate import (
    DEFAULT_OPERATOR_GATE,
    OPERATOR_GATE_DECISIONS,
    record_operator_gate,
    render_operator_gate_markdown,
)
from ..project_map import (
    DEFAULT_PROJECT_MAP_CLASSIFICATION,
    read_only_project_map_run,
    render_read_only_project_map_markdown,
)
from ..paths import resolve_runtime_root
from ..state_refresh import (
    DEFAULT_REFRESH_ACTION,
    DEFAULT_REFRESH_CLASSIFICATION,
    PROGRESS_SCOPE_CHOICES,
    REPAIR_DELTA_KIND_CHOICES,
    refresh_state_run,
    render_state_refresh_markdown,
)


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
OutputFormat = Callable[[argparse.Namespace], str]
AppendCliRolloutEvent = Callable[..., dict[str, object]]

PROJECT_LIFECYCLE_COMMANDS = {
    "refresh-state",
    "read-only-map",
    "reward",
    "operator-gate",
    "goal-closure",
}


def render_goal_closure_markdown(payload: dict[str, Any]) -> str:
    """Render a goal-closure evaluation as compact Markdown."""
    evaluation = payload.get("evaluation") or {}
    lines = [
        "# Goal Closure\n",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- ready: `{evaluation.get('ready')}`",
        f"- tri_state: `{evaluation.get('tri_state')}`",
        f"- reason: `{evaluation.get('reason')}`",
    ]
    evidence = evaluation.get("evidence") or {}
    lines.append(
        "- evidence: ready="
        f"`{len(evidence.get('ready_todo_ids') or [])}`, "
        f"blocked=`{len(evidence.get('blocked_todo_ids') or [])}`, "
        f"deferred=`{len(evidence.get('deferred_todo_ids') or [])}`, "
        f"replan=`{evidence.get('replan_required')}`, "
        f"acceptance_satisfied=`{evidence.get('acceptance_satisfied')}`, "
        f"acceptance_gap_count=`{evidence.get('acceptance_gap_count')}`"
    )
    acceptance = payload.get("acceptance") or {}
    gaps = acceptance.get("acceptance_gaps") or []
    if gaps:
        lines.append(
            "- acceptance gaps: `"
            + "`, `".join(str(g.get("criterion_id")) for g in gaps)
            + "`"
        )
    if payload.get("applied"):
        lines.append("- applied: `true` (goal_closure_ready + goal_closed emitted)")
    return "\n".join(lines) + "\n"

INLINE_VISION_FIELDS = {
    "vision_summary": "vision_summary",
    "vision_role_scope": "role_scope",
    "vision_acceptance": "acceptance_summary",
    "vision_advancement_policy": "advancement_policy",
    "vision_replan_trigger": "replan_trigger_summary",
    "vision_dreaming_policy": "dreaming_policy",
    "vision_last_patch": "last_patch_summary",
}


def _lark_explore_graph_syncer(
    runtime_root_arg: str | None,
    *,
    registry_path: Path,
) -> Callable[..., Mapping[str, object]]:
    extension_runtime_root = resolve_runtime_root(
        load_registry(registry_path), runtime_root_arg
    )

    def sync(**kwargs: object) -> Mapping[str, object]:
        provider = import_module("loopx.extensions.lark")
        activation = resolve_extension_activation(
            str(provider.LARK_EXTENSION_ID),
            state_file=default_extension_state_file(extension_runtime_root),
            required_permissions=(str(provider.LARK_PROJECTION_SINK_PERMISSION),),
        )
        implementation = import_module(
            "loopx.extensions.lark.presentation.explore_results"
        )
        result = dict(
            implementation.sync_issue_fix_explore_on_material_change(**kwargs)
        )
        result["extension_activation"] = activation
        return result

    return sync


def _apply_external_sink_postcondition(
    payload: dict[str, object],
    *,
    sink_result: Mapping[str, object],
    warning: str,
    error: str,
) -> None:
    postcondition = (
        sink_result.get("delivery_postcondition")
        if isinstance(sink_result.get("delivery_postcondition"), Mapping)
        else {}
    )
    if not sink_result.get("enabled") or postcondition.get("satisfied"):
        return
    payload.setdefault("warnings", []).append(warning)
    if postcondition.get("blocks_delivery"):
        payload["ok"] = False
        payload["error"] = error


def _inline_agent_vision_packet(args: argparse.Namespace) -> dict[str, object] | None:
    patch = {
        field: str(value).strip()
        for attr, field in INLINE_VISION_FIELDS.items()
        for value in [getattr(args, attr, None)]
        if str(value or "").strip()
    }
    todo_delta = [
        str(item or "").strip()
        for item in (getattr(args, "vision_todo_delta", None) or [])
        if str(item or "").strip()
    ]
    state = str(getattr(args, "vision_state", None) or "").strip()
    if not patch and not todo_delta and not state:
        return None
    if not str(getattr(args, "agent_id", None) or "").strip():
        raise ValueError("inline agent vision requires --agent-id")
    if not patch:
        raise ValueError("inline agent vision requires at least one --vision-* patch field")
    packet: dict[str, object] = {
        "schema_version": "goal_vision_replan_contract_v0",
        "vision_patch": patch,
        "todo_delta": todo_delta,
    }
    if state:
        packet["state"] = state
    return packet


def register_project_lifecycle_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    refresh_state_parser = subparsers.add_parser(
        "refresh-state",
        help="Append a read-only run from active goal state after state-only updates.",
    )
    add_subcommand_format(refresh_state_parser)
    refresh_state_parser.add_argument(
        "--goal-id",
        required=True,
        help="Goal id whose active state should be refreshed.",
    )
    refresh_state_parser.add_argument("--project", help="Project root. Defaults to the registry goal repo.")
    refresh_state_parser.add_argument(
        "--state-file",
        help="Active goal state path. Defaults to the registry goal state_file.",
    )
    refresh_state_parser.add_argument(
        "--classification",
        default=DEFAULT_REFRESH_CLASSIFICATION,
        help=f"Refresh run classification. Defaults to {DEFAULT_REFRESH_CLASSIFICATION}.",
    )
    refresh_state_parser.add_argument(
        "--recommended-action",
        help=(
            "Local-control next action. Private project refs are allowed; "
            f"inline secrets are rejected. Defaults to: {DEFAULT_REFRESH_ACTION}"
        ),
    )
    refresh_state_parser.add_argument(
        "--next-action",
        help=(
            "Explicitly update the active state's durable ## Next Action before "
            "appending the refresh run. Without this flag, --recommended-action "
            "only describes the run record."
        ),
    )
    refresh_state_parser.add_argument(
        "--delivery-batch-scale",
        choices=DELIVERY_BATCH_SCALE_INPUT_CHOICES,
        help=(
            "Optional explicit delivery scale for this refresh run, overriding "
            "classification-name inference. Accepts canonical scales plus "
            "single_segment/bounded_segment aliases for single_surface."
        ),
    )
    refresh_state_parser.add_argument(
        "--delivery-outcome",
        choices=DELIVERY_OUTCOME_CHOICES,
        help="Optional explicit outcome-floor signal for this refresh run.",
    )
    refresh_state_parser.add_argument(
        "--delivery-workspace-path",
        help=(
            "Local git worktree that produced this accountable delivery. Use when "
            "refresh-state must run from a separate registry checkout; the local "
            "path is validated but is not persisted."
        ),
    )
    refresh_state_parser.add_argument(
        "--todo-id",
        help=(
            "Selected Todo from the original turn-scoped quota guard. Requires "
            "--turn-instance-id and an accountable delivery outcome."
        ),
    )
    refresh_state_parser.add_argument(
        "--turn-instance-id",
        help=(
            "Stable quota guard turn id for settlement writeback. Reuse the same "
            "value on retries."
        ),
    )
    refresh_state_parser.add_argument(
        "--autonomous-replan-recorded",
        action="store_true",
        help=(
            "Mark this refresh as the explicit autonomous replan ACK. "
            "Use only after the agent has performed and written back the bounded replan slice."
        ),
    )
    refresh_state_parser.add_argument(
        "--repair-delta-kind",
        dest="repair_delta_kinds",
        choices=REPAIR_DELTA_KIND_CHOICES,
        action="append",
        help=(
            "Machine-visible frontier changed by this repair/replan ACK. Repeat for "
            "multiple deltas. Without a delta, --autonomous-replan-recorded is stored "
            "as replan_noop/repair_noop and does not clear the obligation."
        ),
    )
    refresh_state_parser.add_argument(
        "--agent-vision-json",
        help=(
            "Path to a complete generated goal_vision_replan_contract_v0 update. "
            "The CLI enforces budgets; any autonomous replan that changes durable "
            "mainline fields requires goal_path_delta_v0."
        ),
    )
    refresh_state_parser.add_argument(
        "--vision-state",
        help=(
            "Optional lower snake_case lifecycle state for an inline "
            "goal_vision_replan_contract_v0 patch. Closure aliases such as "
            "satisfied and vision_satisfied normalize to vision_closed; "
            "custom states remain open until explicitly closed."
        ),
    )
    refresh_state_parser.add_argument(
        "--vision-summary",
        help=(
            "Inline bounded vision_summary for a field-level patch merged into the "
            "current agent's latest active vision."
        ),
    )
    refresh_state_parser.add_argument(
        "--vision-role-scope",
        help="Inline bounded role_scope for the current agent's vision patch.",
    )
    refresh_state_parser.add_argument(
        "--vision-acceptance",
        help="Inline bounded acceptance_summary for the current agent's vision patch.",
    )
    refresh_state_parser.add_argument(
        "--vision-advancement-policy",
        choices=GOAL_VISION_ADVANCEMENT_POLICY_CHOICES,
        help=(
            "Whether open acceptance needs advancement only as needed or must "
            "keep a runnable advancement frontier until the vision closes."
        ),
    )
    refresh_state_parser.add_argument(
        "--vision-replan-trigger",
        help="Inline bounded replan_trigger_summary that quota can project as an acceptance gap.",
    )
    refresh_state_parser.add_argument(
        "--vision-dreaming-policy",
        help="Inline bounded dreaming_policy for the current agent's vision patch.",
    )
    refresh_state_parser.add_argument(
        "--vision-last-patch",
        help="Inline bounded last_patch_summary for the current agent's vision patch.",
    )
    refresh_state_parser.add_argument(
        "--vision-todo-delta",
        action="append",
        help="Compact todo delta for an inline vision patch. Repeat for multiple deltas.",
    )
    refresh_state_parser.add_argument(
        "--vision-unchanged-reason",
        help=(
            "Compact reason why a required vision checkpoint is intentionally unchanged."
        ),
    )
    refresh_state_parser.add_argument(
        "--agent-id",
        help=(
            "Registered agent id for agent-lane state refreshes. When set, the "
            "refresh is visible in run history but does not replace goal-level status."
        ),
    )
    refresh_state_parser.add_argument(
        "--available-capability",
        dest="available_capabilities",
        action="append",
        help=(
            "Preserve one observed public-safe runtime capability from the scoped "
            "quota decision. Repeatable; this context does not grant authority or "
            "change refresh-state write scope."
        ),
    )
    refresh_state_parser.add_argument(
        "--agent-lane",
        help="Public-safe lane label for --agent-id scoped refreshes, such as productization_frontstage.",
    )
    refresh_state_parser.add_argument(
        "--progress-scope",
        choices=PROGRESS_SCOPE_CHOICES,
        help=(
            "Refresh scope. In multi-agent goals, use agent_lane for per-agent runnable "
            "status, or goal with any registered peer for durable goal-level status/Next Action."
        ),
    )
    refresh_state_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the refresh payload without appending.",
    )
    refresh_state_parser.add_argument(
        "--no-global-sync",
        action="store_true",
        help="Do not refresh the shared global registry after writing the state run.",
    )
    refresh_state_parser.add_argument(
        "--suppress-external-sinks",
        action="store_true",
        help=(
            "Keep enabled local projections active but suppress configured external "
            "sink writes for this refresh. Pending sink digests remain retryable."
        ),
    )

    read_only_map_parser = subparsers.add_parser(
        "read-only-map",
        help="Append a generic read-only project-map run for a connected project.",
    )
    add_subcommand_format(read_only_map_parser)
    read_only_map_parser.add_argument(
        "--goal-id",
        required=True,
        help="Goal id whose project should be mapped.",
    )
    read_only_map_parser.add_argument("--project", help="Project root. Defaults to the registry goal repo.")
    read_only_map_parser.add_argument(
        "--state-file",
        help="Active goal state path. Defaults to the registry goal state_file.",
    )
    read_only_map_parser.add_argument(
        "--classification",
        default=DEFAULT_PROJECT_MAP_CLASSIFICATION,
        help=f"Project-map run classification. Defaults to {DEFAULT_PROJECT_MAP_CLASSIFICATION}.",
    )
    read_only_map_parser.add_argument(
        "--recommended-action",
        help=(
            "Local-control next action. Private project refs are allowed; "
            "inline secrets are rejected. Defaults to the first item from the "
            "active state's Next Action."
        ),
    )
    read_only_map_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the project-map payload without appending.",
    )
    read_only_map_parser.add_argument(
        "--no-global-sync",
        action="store_true",
        help="Do not refresh the shared global registry after writing the project-map run.",
    )

    reward_parser = subparsers.add_parser(
        "reward",
        help="Append a compact human reward overlay to a goal run index.",
    )
    add_subcommand_format(reward_parser)
    reward_parser.add_argument("--goal-id", required=True, help="Goal id whose latest run should receive feedback.")
    reward_parser.add_argument(
        "--run-generated-at",
        help="Exact run generated_at timestamp. Defaults to the latest compact run for the goal.",
    )
    reward_parser.add_argument("--recorded-at", help="Reward timestamp. Defaults to current UTC time.")
    reward_parser.add_argument("--decision", required=True, help="Operator decision label, such as continue_route.")
    reward_parser.add_argument(
        "--reward",
        required=True,
        choices=["positive", "negative", "mixed", "neutral"],
        help="Compact reward polarity.",
    )
    reward_parser.add_argument(
        "--reason-summary",
        required=True,
        help="Short public-safe reason. Do not include raw private evidence.",
    )
    reward_parser.add_argument("--follow-up", help="Optional next handoff or experiment condition.")
    reward_parser.add_argument(
        "--lesson-kind",
        choices=sorted(LESSON_KINDS),
        help="Optional public-safe lesson kind when this reward records an explicit user correction.",
    )
    reward_parser.add_argument(
        "--lesson-summary",
        help="Short public-safe lesson summary. Required when --lesson-kind is set.",
    )
    reward_parser.add_argument(
        "--lesson-avoid",
        action="append",
        default=[],
        help="Public-safe phrase/action that future recommended_action should avoid. Repeatable.",
    )
    reward_parser.add_argument(
        "--lesson-prefer",
        action="append",
        default=[],
        help="Public-safe phrase/action that future recommended_action should prefer. Repeatable.",
    )
    reward_parser.add_argument(
        "--state-file",
        help="Active goal state path for optional summary writeback. Defaults to the registry goal state_file.",
    )
    reward_parser.add_argument(
        "--write-active-state-summary",
        action="store_true",
        help="After a real append, also add the returned active_state_summary to the active state's Progress Ledger. With --dry-run, preview only.",
    )
    reward_parser.add_argument("--dry-run", action="store_true", help="Print the overlay without appending it.")

    gate_parser = subparsers.add_parser(
        "operator-gate",
        help="Record an operator gate decision such as read-only map opt-in.",
    )
    add_subcommand_format(gate_parser)
    gate_parser.add_argument("--goal-id", required=True, help="Goal id whose operator gate is being judged.")
    gate_parser.add_argument("--gate", default=DEFAULT_OPERATOR_GATE, help=f"Gate id. Defaults to {DEFAULT_OPERATOR_GATE}.")
    gate_parser.add_argument(
        "--decision",
        required=True,
        choices=sorted(OPERATOR_GATE_DECISIONS),
        help="Operator decision for this gate.",
    )
    gate_parser.add_argument("--recorded-at", help="Decision timestamp. Defaults to current local time.")
    gate_parser.add_argument(
        "--operator-question",
        help="Human-facing question being answered. Defaults from --gate and --goal-id.",
    )
    gate_parser.add_argument(
        "--reason-summary",
        required=True,
        help="Short public-safe reason. Do not include raw private evidence.",
    )
    gate_parser.add_argument("--follow-up", help="Optional next handoff or evidence condition.")
    gate_parser.add_argument(
        "--agent-command",
        help="Target-agent command that becomes valid after approval. Defaults for read_only_map_opt_in approvals.",
    )
    gate_parser.add_argument(
        "--recommended-action",
        help="Local-control next action for status/dashboard; inline secrets are rejected.",
    )
    gate_parser.add_argument("--dry-run", action="store_true", help="Print the decision run without appending it.")
    gate_parser.add_argument(
        "--no-global-sync",
        action="store_true",
        help="Do not refresh the shared global registry after writing the gate decision.",
    )

    closure_parser = subparsers.add_parser(
        "goal-closure",
        help=(
            "Evaluate whether a goal is closable (no ready work, no pending "
            "dependencies, no replan, no external follow-up) and emit "
            "goal_closure_ready + goal_closed events when it is."
        ),
    )
    add_subcommand_format(closure_parser)
    closure_parser.add_argument(
        "--goal-id",
        required=True,
        help="Goal id whose closure is being evaluated.",
    )
    closure_parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime root where the task queue / rollout event log live. Defaults to the registry goal's runtime root.",
    )
    closure_parser.add_argument(
        "--ready-todo-id",
        action="append",
        default=[],
        help="Ready todo id (repeatable). Any present value keeps the goal RUN/WAIT.",
    )
    closure_parser.add_argument(
        "--blocked-todo-id",
        action="append",
        default=[],
        help="Blocked todo id (repeatable). Any present value keeps the goal WAIT.",
    )
    closure_parser.add_argument(
        "--deferred-todo-id",
        action="append",
        default=[],
        help="Deferred todo id (repeatable). Any present value keeps the goal WAIT.",
    )
    closure_parser.add_argument(
        "--replan-required",
        action="store_true",
        help="Treat the goal as requiring replan (keeps it WAIT, not closable).",
    )
    closure_parser.add_argument(
        "--external-followup-required",
        action="store_true",
        help="Treat the goal as requiring external follow-up (keeps it WAIT).",
    )
    closure_parser.add_argument(
        "--apply",
        action="store_true",
        help="When closable, actually emit goal_closure_ready + goal_closed events.",
    )
    closure_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the evaluation without writing any events.",
    )
    closure_parser.add_argument(
        "--acceptance-criteria",
        action="append",
        default=[],
        help=(
            "Declare an acceptance criterion as criterion_id=description "
            "(repeatable). A goal is NOT closable until every criterion has "
            "satisfying evidence. e.g. color_green=theme color is #22c55e"
        ),
    )
    closure_parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help=(
            "Declare evidence as criterion_id=kind=ref[=regex] (repeatable). "
            "kind in {grep,snapshot,test,file,manual}. For kind=grep, an optional "
            "4th segment is the regex pattern the framework independently matches "
            "against ref (relative to --project), overriding any self-reported ok. "
            "e.g. color_green=grep=index.html=#22c55e"
        ),
    )
    closure_parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Run the Goal Acceptance evaluator: verify every acceptance "
            "criterion against evidence. Emits goal_acceptance_pending when gaps "
            "remain, blocking closure."
        ),
    )
    closure_parser.add_argument(
        "--project",
        default=None,
        help=(
            "Project root for independently verifying grep evidence. Defaults to "
            "the registry goal repo. Without it, grep evidence degrades to "
            "self-reported ok."
        ),
    )


def handle_project_lifecycle_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    print_payload: PrintPayload,
    output_format: OutputFormat,
    append_cli_rollout_event: AppendCliRolloutEvent,
) -> int | None:
    if args.command not in PROJECT_LIFECYCLE_COMMANDS:
        return None

    fmt = output_format(args)
    if args.command == "refresh-state":
        agent_vision_packet: dict[str, object] | None = None
        merge_agent_vision_patch = False
        try:
            inline_agent_vision_packet = _inline_agent_vision_packet(args)
            if args.agent_vision_json and inline_agent_vision_packet:
                raise ValueError(
                    "--agent-vision-json cannot be combined with inline --vision-* fields"
                )
            if args.agent_vision_json:
                agent_vision_packet = json.loads(
                    Path(args.agent_vision_json).expanduser().read_text(encoding="utf-8")
                )
            elif inline_agent_vision_packet:
                agent_vision_packet = inline_agent_vision_packet
                merge_agent_vision_patch = True
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "goal_id": args.goal_id,
                "classification": args.classification,
                "appended": False,
                "dry_run": bool(args.dry_run),
                "error": str(exc),
            }
            print_payload(payload, fmt, render_state_refresh_markdown)
            return 1
        try:
            payload = refresh_state_run(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                goal_id=args.goal_id,
                project=Path(args.project).expanduser() if args.project else None,
                state_file=Path(args.state_file).expanduser() if args.state_file else None,
                classification=args.classification,
                recommended_action=args.recommended_action,
                next_action=args.next_action,
                delivery_batch_scale=args.delivery_batch_scale,
                delivery_outcome=args.delivery_outcome,
                delivery_workspace_path=(
                    Path(args.delivery_workspace_path).expanduser()
                    if args.delivery_workspace_path
                    else None
                ),
                todo_id=getattr(args, "todo_id", None),
                turn_instance_id=getattr(args, "turn_instance_id", None),
                agent_id=args.agent_id,
                agent_lane=args.agent_lane,
                progress_scope=args.progress_scope,
                autonomous_replan_recorded=bool(args.autonomous_replan_recorded),
                repair_delta_kinds=args.repair_delta_kinds,
                agent_vision_packet=agent_vision_packet,
                merge_agent_vision_patch=merge_agent_vision_patch,
                vision_unchanged_reason=args.vision_unchanged_reason,
                dry_run=bool(args.dry_run),
                sync_global=not bool(args.no_global_sync),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "goal_id": args.goal_id,
                "classification": args.classification,
                "appended": False,
                "dry_run": bool(args.dry_run),
                "error": str(exc),
            }
        projected_capabilities = runtime_capabilities_for_cli_projection(
            args.available_capabilities
        )
        if projected_capabilities:
            payload["available_capabilities"] = projected_capabilities
        payload["external_sink_delivery_authorized"] = not bool(
            args.suppress_external_sinks
        )
        material_refresh_ready = bool(
            payload.get("ok")
            and (
                payload.get("appended")
                or payload.get("idempotent_replay")
            )
            and not payload.get("dry_run")
        )
        settlement_receipt_repair = bool(
            payload.get("ok")
            and payload.get("receipt_repair_required")
            and getattr(args, "turn_instance_id", None)
            and getattr(args, "todo_id", None)
        )
        if material_refresh_ready or settlement_receipt_repair:
            append_cli_rollout_event(
                payload,
                registry_path=registry_path,
                runtime_root_arg=args.runtime_root,
                event_kind="refresh_state",
                agent_id=args.agent_id,
                todo_id=getattr(args, "todo_id", None),
                run_id=getattr(args, "turn_instance_id", None),
                status=(
                    "receipt_repaired"
                    if settlement_receipt_repair
                    else "appended"
                ),
                summary=(
                    "refresh-state appended compact control-plane state with "
                    f"classification={payload.get('classification')}"
                ),
                details={
                    "command": "refresh-state",
                    "progress_scope": payload.get("progress_scope") or "",
                    "agent_lane": payload.get("agent_lane") or "",
                    "autonomous_replan_recorded": bool(
                        payload.get("autonomous_replan_recorded")
                    ),
                    "global_sync_wrote": bool(
                        isinstance(payload.get("global_sync"), dict)
                        and payload["global_sync"].get("wrote")
                    ),
                    "settlement_effect_id": (
                        payload.get("settlement_identity", {}).get("effect_id")
                        if isinstance(payload.get("settlement_identity"), dict)
                        else None
                    ),
                },
                idempotency_fields=(
                    ["goal_id", "event_kind", "agent_id", "todo_id", "run_id"]
                    if getattr(args, "turn_instance_id", None)
                    else None
                ),
            )
            if getattr(args, "turn_instance_id", None) and getattr(
                args,
                "todo_id",
                None,
            ):
                runtime_root = resolve_runtime_root(
                    load_registry(registry_path),
                    args.runtime_root,
                )
                settlement_result = resolve_heartbeat_settlement_identity(
                    runtime_root,
                    goal_id=args.goal_id,
                    agent_id=args.agent_id,
                    todo_id=getattr(args, "todo_id", None),
                    turn_instance_id=getattr(args, "turn_instance_id", None),
                ).bind(
                    lambda identity: require_settlement_writeback(
                        runtime_root,
                        identity,
                    )
                )
                payload["settlement_result"] = settlement_result_payload(
                    settlement_result
                )
                if settlement_result.failure is not None:
                    payload["ok"] = False
                    payload["receipt_repair_required"] = True
                    payload["error"] = settlement_result.failure.reason
                elif settlement_receipt_repair:
                    payload["receipt_repair_required"] = False
                    payload["receipt_repaired"] = True
            if not material_refresh_ready:
                print_payload(payload, fmt, render_state_refresh_markdown)
                return 0 if payload.get("ok") else 1
            graph_sync = sync_explore_graph_after_material_refresh(
                registry_path=registry_path,
                goal_id=args.goal_id,
                agent_id=args.agent_id,
                project=Path(args.project).expanduser() if args.project else None,
                state_file=Path(args.state_file).expanduser() if args.state_file else None,
                external_sink_delivery_authorized=not bool(
                    args.suppress_external_sinks
                ),
                syncer=_lark_explore_graph_syncer(
                    args.runtime_root,
                    registry_path=registry_path,
                ),
            )
            payload["explore_graph_sync"] = graph_sync
            _apply_external_sink_postcondition(
                payload,
                sink_result=graph_sync,
                warning=(
                    "enabled Explore Graph delivery postcondition is unsatisfied; "
                    "the unchanged sink digest keeps it retryable"
                ),
                error=(
                    "enabled Explore Graph sync/readback failed after the material "
                    "refresh; retry it before delivery"
                ),
            )
            try:
                gate_sync = sync_human_gate_after_refresh(
                    registry_path=registry_path,
                    runtime_root_override=args.runtime_root,
                    goal_id=args.goal_id,
                    agent_id=args.agent_id,
                    external_sink_delivery_authorized=not bool(
                        args.suppress_external_sinks
                    ),
                )
            except Exception:
                gate_sync = goal_channel_gate_sync_failure(
                    registry_path=registry_path,
                    goal_id=args.goal_id,
                )
            payload["goal_channel_gate_sync"] = gate_sync
            _apply_external_sink_postcondition(
                payload,
                sink_result=gate_sync,
                warning=(
                    "enabled Goal Channel human-gate delivery postcondition is "
                    "unsatisfied; the notification remains retryable"
                ),
                error=(
                    "enabled Goal Channel human-gate notification/readback failed "
                    "after the refresh; retry it before delivery"
                ),
            )
        print_payload(payload, fmt, render_state_refresh_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "read-only-map":
        try:
            payload = read_only_project_map_run(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                goal_id=args.goal_id,
                project=Path(args.project).expanduser() if args.project else None,
                state_file=Path(args.state_file).expanduser() if args.state_file else None,
                classification=args.classification,
                recommended_action=args.recommended_action,
                dry_run=bool(args.dry_run),
                sync_global=not bool(args.no_global_sync),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "goal_id": args.goal_id,
                "classification": args.classification,
                "appended": False,
                "dry_run": bool(args.dry_run),
                "error": str(exc),
            }
        print_payload(payload, fmt, render_read_only_project_map_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "reward":
        try:
            reward = compact_reward(
                recorded_at=args.recorded_at,
                decision=args.decision,
                reward=args.reward,
                reason_summary=args.reason_summary,
                follow_up=args.follow_up,
                lesson={
                    "kind": args.lesson_kind,
                    "summary": args.lesson_summary,
                    "avoid": args.lesson_avoid,
                    "prefer": args.lesson_prefer,
                }
                if args.lesson_kind
                else None,
            )
            payload = append_human_reward(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                goal_id=args.goal_id,
                run_generated_at=args.run_generated_at,
                reward=reward,
                dry_run=bool(args.dry_run),
                state_file_override=Path(args.state_file).expanduser() if args.state_file else None,
                write_active_state_summary=bool(args.write_active_state_summary),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "goal_id": args.goal_id,
                "appended": False,
                "dry_run": bool(args.dry_run),
                "error": str(exc),
            }
        print_payload(payload, fmt, render_reward_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "goal-closure":
        try:
            from ..control_plane.goals.goal_closure import (
                build_goal_closure_state,
                emit_goal_closed,
                emit_goal_closure_ready,
                evaluate_goal_closure,
            )
            from ..control_plane.scheduler.event_driven_dispatch import (
                load_task_queue,
                task_queue_path,
            )
            from ..rollout_event_log import rollout_event_log_path

            runtime_root = Path(
                resolve_runtime_root(load_registry(registry_path), args.runtime_root)
            )
            queue_view = load_task_queue(
                task_queue_path(runtime_root, goal_id=args.goal_id)
            )
            # Goal Acceptance evaluation (when criteria/evidence supplied).
            acceptance = None
            if (
                bool(getattr(args, "verify", False))
                or getattr(args, "acceptance_criteria", None)
                or getattr(args, "evidence", None)
            ):
                from ..control_plane.goals.goal_acceptance import (
                    evaluate_goal_acceptance,
                )

                criteria = []
                for spec in getattr(args, "acceptance_criteria", None) or []:
                    if "=" in spec:
                        cid, _, desc = spec.partition("=")
                        criteria.append(
                            {"criterion_id": cid.strip(), "description": desc.strip()}
                        )
                evidence = []
                for spec in getattr(args, "evidence", None) or []:
                    # format: criterion_id=kind=ref[=regex]
                    parts = spec.split("=")
                    if len(parts) < 3:
                        continue
                    kind = parts[1].strip()
                    item: dict[str, Any] = {
                        "criterion_ids": [parts[0].strip()],
                        "kind": kind,
                        "ref": parts[2].strip(),
                        "ok": True,
                    }
                    if len(parts) >= 4:
                        item["pattern"] = parts[3].strip()
                    if kind == "grep":
                        # Independent verification when a regex is provided; the
                        # self-reported ok is only a fallback without one.
                        item["ok"] = bool(item.get("pattern"))
                    evidence.append(item)
                # Resolve the project root for independent grep verification.
                base_dir = None
                if getattr(args, "project", None):
                    base_dir = Path(args.project).expanduser().resolve()
                acceptance = evaluate_goal_acceptance(
                    acceptance_criteria=criteria or None,
                    evidence=evidence or None,
                    base_dir=base_dir,
                )
            state = build_goal_closure_state(
                ready_todo_ids=list(getattr(args, "ready_todo_id", None) or [])
                or queue_view.get("pending_todo_ids", []),
                blocked_todo_ids=list(getattr(args, "blocked_todo_id", None) or []),
                deferred_todo_ids=list(getattr(args, "deferred_todo_id", None) or []),
                pending_dependency_ids=list(getattr(args, "blocked_todo_id", None) or []),
                replan_required=bool(getattr(args, "replan_required", False)),
                external_followup_required=bool(
                    getattr(args, "external_followup_required", False)
                ),
                open_todo_count=queue_view.get("pending_count", 0),
                claimed_advancement_count=queue_view.get("claimed_count", 0),
                acceptance=acceptance,
            )
            evaluation = evaluate_goal_closure(state)
            applied = False
            log_path = rollout_event_log_path(runtime_root, goal_id=args.goal_id)
            if evaluation["ready"] and bool(getattr(args, "apply", False)):
                emit_goal_closure_ready(
                    log_path=log_path,
                    goal_id=args.goal_id,
                    reason=evaluation["reason"],
                    evidence=evaluation["evidence"],
                )
                emit_goal_closed(
                    log_path=log_path,
                    goal_id=args.goal_id,
                    kind="derived",
                    reason=evaluation["reason"],
                )
                applied = True
                # Keep the registry goal entry's status in lockstep with the
                # rollout log so `status`/registry and start-goal's guided packet
                # (which reads the rollout log) agree that the goal is closed.
                from ..registry import sync_registry_goal_closed

                sync_registry_goal_closed(registry_path, args.goal_id)
            # When acceptance has gaps and --apply (or --verify), record pending.
            if (
                acceptance is not None
                and acceptance.get("satisfied") is not True
                and (
                    bool(getattr(args, "apply", False))
                    or bool(getattr(args, "verify", False))
                )
            ):
                from ..control_plane.goals.goal_acceptance import (
                    emit_goal_acceptance_pending,
                )

                gaps = acceptance.get("acceptance_gaps") or []
                if gaps:
                    emit_goal_acceptance_pending(
                        log_path=log_path,
                        goal_id=args.goal_id,
                        acceptance_gaps=gaps,
                    )
            payload = {
                "ok": True,
                "goal_id": args.goal_id,
                "evaluation": evaluation,
                "acceptance": acceptance,
                "applied": applied,
                "dry_run": bool(getattr(args, "dry_run", False)),
            }
        except Exception as exc:  # noqa: BLE001
            payload = {
                "ok": False,
                "goal_id": args.goal_id,
                "evaluation": None,
                "applied": False,
                "error": str(exc),
            }
        print_payload(payload, fmt, render_goal_closure_markdown)
        return 0 if payload.get("ok") else 1

    try:
        payload = record_operator_gate(
            registry_path=registry_path,
            runtime_root_override=args.runtime_root,
            goal_id=args.goal_id,
            gate=args.gate,
            decision=args.decision,
            operator_question=args.operator_question,
            reason_summary=args.reason_summary,
            follow_up=args.follow_up,
            agent_command=args.agent_command,
            recommended_action=args.recommended_action,
            recorded_at=args.recorded_at,
            dry_run=bool(args.dry_run),
            sync_global=not bool(args.no_global_sync),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "registry": str(registry_path),
            "runtime_root": args.runtime_root,
            "goal_id": args.goal_id,
            "appended": False,
            "dry_run": bool(args.dry_run),
            "error": str(exc),
        }
    print_payload(payload, fmt, render_operator_gate_markdown)
    return 0 if payload.get("ok") else 1
