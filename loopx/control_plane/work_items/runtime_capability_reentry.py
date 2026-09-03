from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from ..agents.capability_gate import runtime_capabilities_for_cli_projection
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    render_scheduler_execution_args,
)
from ..todos.contract import normalize_todo_id


RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION = "runtime_capability_reentry_v0"


def _verification_target_for_capability(
    capability_gate: Mapping[str, Any],
    capability: str,
) -> dict[str, Any] | None:
    blocked_ids = {
        str(todo_id)
        for binding in capability_gate.get("resolution_bindings") or []
        if isinstance(binding, Mapping)
        and binding.get("owner") == "agent"
        and binding.get("capability") == capability
        for todo_id in (
            binding.get("blocked_todo_ids")
            or [binding.get("primary_blocked_todo_id")]
        )
        if str(todo_id or "").strip()
    }
    for candidate in capability_gate.get("blocked_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        todo_id = str(candidate.get("todo_id") or "").strip()
        if todo_id not in blocked_ids:
            continue
        required = runtime_capabilities_for_cli_projection(
            candidate.get("required_capabilities")
        )
        if capability not in required:
            continue
        instruction = str(candidate.get("text") or "").strip()
        if not instruction:
            continue
        target = {
            "todo_id": todo_id,
            "action_kind": str(candidate.get("action_kind") or "unspecified"),
            "instruction": instruction,
        }
        target_ref = str(candidate.get("target_key") or "").strip()
        if target_ref:
            target["target_ref"] = target_ref
        return target
    return None


def build_runtime_capability_reentry_packet(
    payload: Mapping[str, Any],
    *,
    available_capabilities: Any,
    scheduler_execution_context: (
        Mapping[str, Any] | SchedulerExecutionContextResolution | None
    ),
    turn_instance_id: str | None = None,
    runtime_root: str | None = None,
) -> dict[str, Any] | None:
    """Project verified runtime-capability re-entry without persisting a grant."""

    capability_gate = (
        payload.get("capability_gate")
        if isinstance(payload.get("capability_gate"), Mapping)
        else {}
    )
    observed = runtime_capabilities_for_cli_projection(available_capabilities)
    candidates = [
        capability
        for capability in runtime_capabilities_for_cli_projection(
            capability_gate.get("repair_missing")
        )
        if capability not in observed
    ]
    if not candidates:
        return None

    try:
        scheduler_args = shlex.split(
            render_scheduler_execution_args(
                scheduler_execution_context=scheduler_execution_context,
            )
        )
    except ValueError:
        return None
    if not scheduler_args:
        return None

    selected_todo = (
        payload.get("selected_todo")
        if isinstance(payload.get("selected_todo"), Mapping)
        else {}
    )
    selected_todo_id = normalize_todo_id(selected_todo.get("todo_id"))

    goal_id = str(payload.get("goal_id") or "<GOAL_ID>")
    agent_identity = (
        payload.get("agent_identity")
        if isinstance(payload.get("agent_identity"), Mapping)
        else {}
    )
    agent_id = str(agent_identity.get("agent_id") or "").strip()
    base_args = [
        "loopx",
        *(
            ["--runtime-root", str(runtime_root)]
            if str(runtime_root or "").strip()
            else []
        ),
        "--format",
        "json",
        "quota",
        "should-run",
        "--goal-id",
        goal_id,
    ]
    if agent_id:
        base_args.extend(["--agent-id", agent_id])
    if turn_instance_id:
        base_args.extend(["--turn-instance-id", turn_instance_id])
    for capability in observed:
        base_args.extend(["--available-capability", capability])

    reentry_candidates = []
    for capability in candidates:
        verification_target = _verification_target_for_capability(
            capability_gate,
            capability,
        )
        if verification_target is None:
            continue
        if (
            selected_todo_id
            and normalize_todo_id(verification_target.get("todo_id"))
            != selected_todo_id
        ):
            continue
        cli_args = [
            *base_args,
            "--available-capability",
            capability,
            *scheduler_args,
        ]
        reentry_candidates.append(
            {
                "capability": capability,
                "verification_required": "successful_real_callsite_observation",
                "verification_target": verification_target,
                "command": shlex.join(cli_args),
            }
        )
    if not reentry_candidates:
        return None
    return {
        "schema_version": RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
        "state": "verification_required",
        "source": "quota_should_run.capability_gate.repair_missing",
        "candidates": reentry_candidates,
        "verification_contract": {
            "scope": "real_task_facing_callsite_for_blocked_todo",
            "ordinary_delivery_allowed": False,
            "advancement_checkpoint": False,
            "settles_turn": False,
            "on_success": "rerun_quota_in_same_turn_then_continue_if_allowed",
            "on_failure": "record_exact_blocker_without_capability_flag",
        },
        "inheritance_contract": {
            "source_invocation": "verified quota should-run reentry",
            "propagates_to": [
                "interaction_contract.cli_channel.next_cli_actions",
                "quota spend-slot",
                "quota monitor-poll",
            ],
            "session_scoped": True,
            "durable_grant_written": False,
        },
        "failure_policy": (
            "Do not add the capability flag when the real callsite check fails; "
            "continue the capability repair or record the concrete blocker."
        ),
    }
