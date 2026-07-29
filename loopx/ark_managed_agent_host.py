"""Thin one-shot goal activation contract for Ark Managed Agent."""

from __future__ import annotations

from typing import Any

from .control_plane.work_items.runtime_capability_reentry import (
    RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
)


ARK_MANAGED_AGENT_HOST = "ark-managed-agent"
ARK_MANAGED_AGENT_HOST_CONTRACT_SCHEMA_VERSION = (
    "loopx_ark_managed_agent_goal_host_v0"
)
ARK_MANAGED_AGENT_PROMPT_FAMILY = "loopx_goal_prompt_v0"


def build_ark_managed_agent_host_contract() -> dict[str, Any]:
    """Describe transport-neutral ownership for one goal prompt activation."""

    return {
        "schema_version": ARK_MANAGED_AGENT_HOST_CONTRACT_SCHEMA_VERSION,
        "host_kind": ARK_MANAGED_AGENT_HOST,
        "activation_mode": "goal_once",
        "prompt_family": ARK_MANAGED_AGENT_PROMPT_FAMILY,
        "policy_source": "quota_should_run.interaction_contract",
        "transport_contract": "goal_prompt_v0",
        "goal_runtime_owns_continuation": True,
        "loopx_turn_driver_required": False,
        "session_state_authoritative": False,
        "runtime_capability_reentry": {
            "source_ref": (
                "quota_should_run.interaction_contract.cli_channel."
                "runtime_capability_reentry"
            ),
            "cli_projection_ref": "quota_should_run.runtime_capability_reentry",
            "packet_schema_version": RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
            "delivery_channel": "quota_tool_result",
            "goal_prompt_mutated": False,
            "session_scoped": True,
            "durable_grant_written": False,
        },
    }
