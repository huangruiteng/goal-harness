"""Agent-vision checkpoint contract for accountable state refreshes."""

from __future__ import annotations

from typing import Any

from ...feedback import validate_public_safe_text

VISION_CHECKPOINT_SCHEMA_VERSION = "vision_checkpoint_v0"
VISION_CHECKPOINT_MATERIAL_OUTCOMES = {
    "outcome_gap",
    "outcome_progress",
    "primary_goal_outcome",
}
VISION_UNCHANGED_REASON_LIMIT = 240


def normalize_vision_unchanged_reason(value: str | None) -> str:
    """Normalize and validate a vision closeout reason before state mutation."""

    unchanged = " ".join(str(value or "").strip().split())
    if not unchanged:
        return ""
    validate_public_safe_text("vision_unchanged_reason", unchanged)
    if len(unchanged) > VISION_UNCHANGED_REASON_LIMIT:
        raise ValueError(
            "vision_unchanged_reason exceeds "
            f"{VISION_UNCHANGED_REASON_LIMIT} chars"
        )
    return unchanged


def build_vision_checkpoint(
    *,
    agent_id: str | None,
    agent_vision: dict[str, Any] | None,
    existing_agent_vision: dict[str, Any] | None,
    vision_unchanged_reason: str | None,
    delivery_outcome: str | None,
    active_state_next_action_update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the explicit vision closeout decision for this refresh run."""

    triggers: list[dict[str, Any]] = []
    if delivery_outcome in VISION_CHECKPOINT_MATERIAL_OUTCOMES:
        triggers.append(
            {
                "kind": "material_delivery_outcome",
                "delivery_outcome": delivery_outcome,
            }
        )
    if active_state_next_action_update and active_state_next_action_update.get(
        "would_update"
    ):
        triggers.append({"kind": "durable_next_action_update"})

    unchanged = normalize_vision_unchanged_reason(vision_unchanged_reason)
    required = bool(triggers or unchanged)
    if agent_vision:
        decision = "patched"
        satisfied = True
    elif unchanged and existing_agent_vision:
        decision = "unchanged_with_reason"
        satisfied = True
    elif unchanged or required:
        decision = "missing_required"
        satisfied = False
    else:
        decision = "not_required"
        satisfied = True

    checkpoint: dict[str, Any] = {
        "schema_version": VISION_CHECKPOINT_SCHEMA_VERSION,
        "agent_id": agent_id,
        "required": required,
        "satisfied": satisfied,
        "decision": decision,
        "triggers": triggers,
    }
    if agent_vision:
        checkpoint["agent_vision_state"] = agent_vision.get("state")
    if unchanged and existing_agent_vision:
        checkpoint["unchanged_reason"] = unchanged
        checkpoint["agent_vision_state"] = existing_agent_vision.get("state")
    elif unchanged:
        checkpoint["missing_baseline"] = True
        checkpoint["rejected_unchanged_reason"] = unchanged
    if not satisfied:
        checkpoint["required_resolution"] = ["write_vision_patch"]
        if not checkpoint.get("missing_baseline"):
            checkpoint["required_resolution"].append("record_unchanged_reason")
    return checkpoint
