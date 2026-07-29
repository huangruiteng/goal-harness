from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from ..agents.capability_gate import runtime_capabilities_for_cli_projection
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    render_scheduler_execution_args,
)


RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION = "runtime_capability_reentry_v0"


def build_runtime_capability_reentry_packet(
    payload: Mapping[str, Any],
    *,
    available_capabilities: Any,
    scheduler_execution_context: (
        Mapping[str, Any] | SchedulerExecutionContextResolution | None
    ),
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

    goal_id = str(payload.get("goal_id") or "<GOAL_ID>")
    agent_identity = (
        payload.get("agent_identity")
        if isinstance(payload.get("agent_identity"), Mapping)
        else {}
    )
    agent_id = str(agent_identity.get("agent_id") or "").strip()
    base_args = [
        "loopx",
        "--format",
        "json",
        "quota",
        "should-run",
        "--goal-id",
        goal_id,
    ]
    if agent_id:
        base_args.extend(["--agent-id", agent_id])
    for capability in observed:
        base_args.extend(["--available-capability", capability])

    reentry_candidates = []
    for capability in candidates:
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
                "cli_args": cli_args,
                "command": shlex.join(cli_args),
            }
        )
    return {
        "schema_version": RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
        "state": "verification_required",
        "source": "quota_should_run.capability_gate.repair_missing",
        "candidates": reentry_candidates,
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
