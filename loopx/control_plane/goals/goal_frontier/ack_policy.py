from __future__ import annotations

from typing import Any

from ...work_items.repair_delta import repair_delta_kinds_have_frontier_delta
from ..goal_vision_policy import goal_vision_repeats_advancement_until_closed
from . import outcome_continuity

REPEAT_VISION_REPLAN_SATISFYING_DELTA_KINDS = (
    outcome_continuity.REPEAT_VISION_REPLAN_SATISFYING_DELTA_KINDS
)


def autonomous_replan_ack_has_frontier_delta(ack: dict[str, Any] | None) -> bool:
    if not isinstance(ack, dict) or ack.get("recorded") is not True:
        return False
    delta_contract = ack.get("delta_contract")
    if (
        not isinstance(delta_contract, dict)
        or delta_contract.get("delta_present") is not True
    ):
        return False
    return repair_delta_kinds_have_frontier_delta(delta_contract.get("delta_kinds"))


def blocked_successor_repeat_vision_open(
    replan_obligation: dict[str, Any] | None,
    acceptance_gaps: list[dict[str, Any]] | None,
) -> bool:
    trigger_kinds = {
        str(trigger.get("kind") or "").strip()
        for trigger in (
            replan_obligation.get("triggers") or []
            if isinstance(replan_obligation, dict)
            else []
        )
        if isinstance(trigger, dict)
    }
    return "blocked_successor_no_progress_repeat" in trigger_kinds and any(
        goal_vision_repeats_advancement_until_closed(gap.get("advancement_policy"))
        for gap in (acceptance_gaps or [])
        if isinstance(gap, dict)
    )


def autonomous_replan_ack_satisfies_obligation(
    ack: dict[str, Any] | None,
    *,
    replan_obligation: dict[str, Any] | None,
    acceptance_gaps: list[dict[str, Any]] | None,
    required_read_validation: dict[str, Any] | None = None,
) -> bool:
    """Reject ACKs that miss either a required read or a required frontier delta."""

    if not autonomous_replan_ack_has_frontier_delta(ack):
        return False
    if (
        isinstance(required_read_validation, dict)
        and required_read_validation.get("accepted") is False
    ):
        return False
    if not blocked_successor_repeat_vision_open(
        replan_obligation,
        acceptance_gaps,
    ):
        return True
    delta_contract = ack.get("delta_contract") if isinstance(ack, dict) else {}
    delta_kinds = {
        str(item or "").strip()
        for item in (
            delta_contract.get("delta_kinds") or []
            if isinstance(delta_contract, dict)
            else []
        )
        if str(item or "").strip()
    }
    return bool(delta_kinds & set(REPEAT_VISION_REPLAN_SATISFYING_DELTA_KINDS))
