"""Visible Goal host policy helpers inside the heartbeat bounded context."""

from __future__ import annotations

import re
from typing import Any

from ..agents.capability_gate import (
    runtime_capabilities_for_cli_projection,
)
from ..work_items.runtime_capability_reentry import (
    RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
)


VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_PROJECTION_SCHEMA_VERSION = (
    "visible_goal_initial_runtime_capability_projection_v0"
)
VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT = 8
VISIBLE_GOAL_HOST_CONTROL_CAPABILITIES = frozenset(
    {
        "automation_update",
        "current_time",
        "first_turn_receipt",
        "heartbeat_prequota",
        "loop",
        "loopx_turn",
        "rrule",
        "scheduler_execution_context",
        "turn_instance_id",
    }
)
VISIBLE_GOAL_HEARTBEAT_ONLY_POLICY_PATTERNS = (
    re.compile(r"(?<![a-z0-9_/])/loop(?![a-z0-9_-])", re.IGNORECASE),
    re.compile(r"\bautomation(?:[\s_-]+update)?\b", re.IGNORECASE),
    re.compile(r"\bheartbeat(?:[\s_-]+prequota)?\b", re.IGNORECASE),
    re.compile(r"\brrule\b", re.IGNORECASE),
    re.compile(r"\breceipt\b|\bfirst[\s_-]*turn[\s_-]*receipt\b", re.IGNORECASE),
    re.compile(r"\bcurrent[\s_-]*time(?:[\s_-]*iso)?\b", re.IGNORECASE),
    re.compile(r"\bloopx[\s_-]*turn\b", re.IGNORECASE),
    re.compile(r"\bturn[\s_-]*instance[\s_-]*id\b", re.IGNORECASE),
    re.compile(r"\bscheduler(?:[\s_-]*execution[\s_-]*context)?\b", re.IGNORECASE),
)


def build_visible_goal_initial_runtime_capability_projection(
    available_capabilities: Any,
) -> dict[str, Any] | None:
    capabilities = [
        capability
        for capability in runtime_capabilities_for_cli_projection(
            available_capabilities
        )
        if capability not in VISIBLE_GOAL_HOST_CONTROL_CAPABILITIES
    ]
    if not capabilities:
        return None
    if len(capabilities) > VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT:
        raise ValueError(
            "visible Goal initial runtime capabilities exceed the limit of "
            f"{VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT}"
        )
    return {
        "schema_version": (
            VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_PROJECTION_SCHEMA_VERSION
        ),
        "source": "activation_available_capabilities",
        "scope": "visible_goal_session",
        "capabilities": capabilities,
        "capability_count": len(capabilities),
        "max_capabilities": VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT,
        "first_quota_path": "task_body.quota_guard_command",
        "user_gate": False,
        "durable_grant_written": False,
        "dynamic_reentry_schema_version": RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
    }


def validate_visible_goal_policy_rule(*, field: str, value: str) -> None:
    if any(
        pattern.search(value)
        for pattern in VISIBLE_GOAL_HEARTBEAT_ONLY_POLICY_PATTERNS
    ):
        raise ValueError(
            f"visible Goal {field} contains heartbeat-only control vocabulary"
        )
