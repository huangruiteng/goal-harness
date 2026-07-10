from __future__ import annotations

from enum import Enum
from typing import Any


class GoalVisionAdvancementPolicy(str, Enum):
    AS_NEEDED = "as_needed"
    REPEAT_UNTIL_CLOSED = "repeat_until_closed"


GOAL_VISION_ADVANCEMENT_POLICY_CHOICES = tuple(
    policy.value for policy in GoalVisionAdvancementPolicy
)


def normalize_goal_vision_advancement_policy(value: Any) -> str:
    candidate = str(value or "").strip().lower().replace("-", "_")
    try:
        return GoalVisionAdvancementPolicy(candidate).value
    except ValueError as exc:
        raise ValueError(
            "agent_vision.advancement_policy must be one of: "
            + ", ".join(GOAL_VISION_ADVANCEMENT_POLICY_CHOICES)
        ) from exc


def goal_vision_repeats_advancement_until_closed(value: Any) -> bool:
    return (
        str(value or "").strip()
        == GoalVisionAdvancementPolicy.REPEAT_UNTIL_CLOSED.value
    )
