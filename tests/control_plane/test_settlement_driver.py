"""Focused tests for the remaining shared settlement projection facade."""

from loopx.control_plane.effect_program import (
    SettlementIdentity,
    SettlementStepKind,
)
from loopx.control_plane.settlement_driver import (
    effect_ids_match,
    settlement_receipt,
)


IDENTITY = SettlementIdentity(
    goal_id="fixture-goal",
    agent_id="fixture-agent",
    todo_id="todo_fixture0001",
    turn_instance_id="fixture-turn",
)


def test_effect_ids_match_allows_missing_and_equal_provenance() -> None:
    assert effect_ids_match(None, IDENTITY.effect_id) is True
    assert effect_ids_match(IDENTITY.effect_id, IDENTITY.effect_id) is True
    assert effect_ids_match("other-effect", IDENTITY.effect_id) is False


def test_settlement_receipt_is_committed_under_the_identity() -> None:
    receipt = settlement_receipt(
        IDENTITY,
        step_kind=SettlementStepKind.VALIDATION,
        source_ref="rollout_event:abc",
    )
    assert receipt.step_kind is SettlementStepKind.VALIDATION
    assert receipt.status == "committed"
    assert receipt.effect_id == IDENTITY.effect_id
    assert receipt.source_ref == "rollout_event:abc"
