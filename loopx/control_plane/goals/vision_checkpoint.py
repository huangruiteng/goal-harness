"""Python adapter for the TypeScript-owned vision-checkpoint transition."""

from __future__ import annotations

from typing import Any

from ...feedback import validate_public_safe_text
from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..turn_driver.delivery_continuity import normalize_delivery_boundary

VISION_CHECKPOINT_SCHEMA_VERSION = "vision_checkpoint_v0"
VISION_CHECKPOINT_REQUEST_SCHEMA = "loopx_vision_checkpoint_request_v0"
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
    delivery_boundary: str | None = None,
    todo_id: str | None = None,
    completion_todo_id: str | None = None,
    autonomous_replan_recorded: bool = False,
) -> dict[str, Any]:
    """Return the TS-owned vision closeout decision for this refresh run."""

    unchanged = normalize_vision_unchanged_reason(vision_unchanged_reason)
    try:
        result = effect_runtime_result(
            "goal.vision_checkpoint.evaluate",
            {
                "schema_version": VISION_CHECKPOINT_REQUEST_SCHEMA,
                "agent_id": agent_id,
                "agent_vision": agent_vision,
                "existing_agent_vision": existing_agent_vision,
                "vision_unchanged_reason": unchanged or None,
                "delivery_outcome": delivery_outcome,
                "active_state_next_action_would_update": bool(
                    active_state_next_action_update
                    and active_state_next_action_update.get("would_update")
                ),
                "delivery_boundary": normalize_delivery_boundary(delivery_boundary),
                "todo_id": todo_id,
                "completion_todo_id": completion_todo_id,
                "autonomous_replan_recorded": bool(autonomous_replan_recorded),
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, dict):
        raise RuntimeError("TypeScript vision checkpoint result must be an object")
    if (
        result.get("schema_version") != VISION_CHECKPOINT_SCHEMA_VERSION
        or result.get("decision")
        not in {
            "patched",
            "unchanged_with_reason",
            "missing_required",
            "not_required",
        }
        or not isinstance(result.get("required"), bool)
        or not isinstance(result.get("satisfied"), bool)
        or not isinstance(result.get("triggers"), list)
        or not isinstance(result.get("delivery_boundary"), str)
    ):
        raise RuntimeError("TypeScript vision checkpoint result shape mismatch")
    return result
