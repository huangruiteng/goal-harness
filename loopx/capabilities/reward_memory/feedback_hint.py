"""Effect-free guidance for agents reviewing an inbox's captured feedback."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .experiment import (
    resolve_reward_memory_experiment,
    resolve_reward_memory_surface_config,
)
from .scoped_feedback import SCOPED_FEEDBACK_ADAPTER


def build_feedback_review_hint(
    *, registry_path: Path, goal_id: str | None, agent_id: str | None
) -> dict[str, Any] | None:
    """Describe explicit ingestion, never inspect messages or call a provider.

    The caller must first establish an enabled, registry-routed inbox with
    returned items. Automation flags govern hooks, not this explicit path.
    """
    if not goal_id or not agent_id:
        return None
    try:
        status, config = resolve_reward_memory_experiment(
            registry_path=registry_path, goal_id=goal_id, agent_id=agent_id
        )
    except (OSError, ValueError):
        return None
    if config is None:
        return None
    routes = []
    for surface_id, surface in sorted(config["surfaces"].items()):
        if surface["adapter"] != SCOPED_FEEDBACK_ADAPTER:
            continue
        route = resolve_reward_memory_surface_config(config, surface_id)
        corpus, policy = route["corpus"], route["standing_policy"]
        scope = corpus["scope"]
        if (
            not policy["enabled"]
            or scope.get("peer_ref") != f"agent:{agent_id}"
            or corpus["lifecycle"]["state"] != "active"
            or corpus["write_authority"] in {"read_only", "ephemeral_runtime"}
        ):
            continue
        routes.append(
            {
                "surface_id": surface_id,
                "corpus_id": corpus["corpus_id"],
                "target_class": corpus["class_id"],
                "scope": scope | {"surface_ids": [surface_id]},
                "allowed_source_kinds": policy["allowed_source_kinds"],
                "allowed_actor_roles": policy["allowed_actor_roles"],
                "allowed_action_scopes": policy["allowed_action_scopes"],
            }
        )
    if not routes:
        return None
    preview = [
        "loopx",
        "--format",
        "json",
        "--registry",
        str(registry_path.expanduser()),
        "reward-memory",
        "ingest-event",
        "--goal-id",
        goal_id,
        "--agent-id",
        agent_id,
        "--input",
        "<compact-event.json>",
    ]
    return {
        "schema_version": "reward_memory_feedback_review_hint_v0",
        "advisory_only": True,
        "automatic_ingest": status["automatic_ingest"],
        "automatic_ingest_required": False,
        "grants_new_action_authority": False,
        "blocks_inbox_settlement": False,
        "provider_calls_performed": False,
        "routes": routes,
        "preview_command": shlex.join(preview),
        "instruction": (
            "While triaging these messages, consider confirmed, reusable feedback for "
            "Reward Memory. Distill a compact scoped lesson, not raw chat; verify the "
            "source actor, authority, freshness, current artifact and conflicts. "
            "Choose only an applicable configured route below; allowed actor roles "
            "are constraints, not proof of the sender's authority. Do not turn "
            "disagreement or a one-off opinion into a universal prohibition. "
            "Use soft preferences or procedural experience where applicable; hard "
            "policy still requires independently verified existing authority. "
            "For advisory classes, requested_action_scopes must be empty. "
            "Prepare {adapter: scoped_feedback, event: scoped_feedback_reward_memory_event_v0, "
            "observed_at} using the documented event fields and a stable feedback_ref; "
            "replace the input placeholder and preview before adding --execute. "
            "Do not copy fixture actor/guard assertions or expand scope to pass guards. "
            "Automatic ingest being off does not disable explicit ingest-event. "
            "After an authorized write, inspect the ingest receipt and exact readback; "
            "do not claim learning from a preview or failed write. If no reusable "
            "lesson exists, evidence conflicts, or memory is unavailable, continue "
            "normal reply/material-review/ACK with an honest rationale; no new user gate."
        ),
        "event_reference": "loopx/capabilities/reward_memory/README.md",
    }
