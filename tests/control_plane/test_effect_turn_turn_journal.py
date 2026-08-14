from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from loopx.control_plane.effect_program import (
    TURN_TRANSACTION_PHASES,
    EffectNext,
    interpret_turn_journal,
)
from loopx.control_plane.turn_driver.transaction import TRANSACTION_PHASES


def _journal(*, status: str = "committed") -> dict[str, Any]:
    turn_key = "sha256:fixture-turn"
    return {
        "schema_version": "loopx_turn_journal_v0",
        "goal_id": "fixture-goal",
        "turn_key": turn_key,
        "status": status,
        "completed_phases": [
            "host_execute",
            "typed_result",
            "validation",
            "durable_writeback",
            "quota_spend",
            "scheduler_apply",
            "scheduler_ack",
        ],
        "plan": {
            "turn_envelope": {
                "goal_id": "fixture-goal",
                "agent_id": "fixture-agent",
            },
            "transaction": {
                "turn_key": turn_key,
                "settlement_plan": {
                    "identity": {
                        "goal_id": "fixture-goal",
                        "agent_id": "fixture-agent",
                    }
                },
            },
        },
        "host_result": {"turn_key": turn_key},
        "receipt": {"turn_key": turn_key},
    }


def test_turn_journal_reports_legal_replay_without_mutating_input() -> None:
    journal = _journal()
    before = deepcopy(journal)

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
        capabilities=["filesystem_read"],
    )

    assert turn.request.kind == "turn_journal"
    assert turn.request.source == "turn_journal"
    assert turn.request.goal_id == "fixture-goal"
    assert turn.request.agent_id == "fixture-agent"
    assert turn.request.capabilities == ("filesystem_read",)
    assert turn.request.context == {
        "replay_legal": True,
        "goal_matches": True,
        "owner_matches": True,
        "turn_key_matches": True,
        "phases_form_ordered_prefix": True,
        "journal_status": "committed",
        "tombstone_retained": True,
        "completed_phases": (
            "host_execute",
            "typed_result",
            "validation",
            "durable_writeback",
            "quota_spend",
            "scheduler_apply",
            "scheduler_ack",
        ),
        "violations": (),
    }
    assert turn.interpretation.route == "turn_journal_replay"
    assert turn.interpretation.obligation == "observe_fenced_replay"
    assert turn.interpretation.interaction_mode == "read_only"
    assert turn.observation.decision == "replay_legal"
    assert turn.observation.should_run is False
    assert turn.observation.effective_action == "observe_replay"
    assert turn.next_effect == EffectNext()
    assert journal == before


def test_turn_journal_accumulates_identity_and_phase_violations() -> None:
    journal = _journal()
    journal["goal_id"] = "other-goal"
    journal["turn_key"] = "sha256:other-turn"
    journal["completed_phases"] = ["host_execute", "validation"]
    identity = journal["plan"]["transaction"]["settlement_plan"]["identity"]
    identity["agent_id"] = "other-agent"

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["goal_matches"] is False
    assert turn.request.context["owner_matches"] is False
    assert turn.request.context["turn_key_matches"] is False
    assert turn.request.context["phases_form_ordered_prefix"] is False
    assert turn.request.context["violations"] == (
        "goal_mismatch",
        "owner_mismatch",
        "turn_key_mismatch",
        "completed_phases_not_ordered_prefix",
    )
    assert turn.observation.decision == "replay_blocked"
    assert turn.observation.should_run is False
    assert turn.observation.effective_action == "block_replay"
    assert turn.next_effect == EffectNext()


@pytest.mark.parametrize("status", ["committed", "stopped", "failed"])
def test_turn_journal_retains_terminal_tombstones(status: str) -> None:
    turn = interpret_turn_journal(
        _journal(status=status),
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["tombstone_retained"] is True
    assert turn.request.context["journal_status"] == status
    assert turn.request.context["replay_legal"] is True


def test_turn_journal_blocks_non_terminal_and_malformed_trace() -> None:
    journal = {"status": "in_progress", "completed_phases": "host_execute"}

    turn = interpret_turn_journal(journal)

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["goal_matches"] is False
    assert turn.request.context["owner_matches"] is False
    assert turn.request.context["turn_key_matches"] is False
    assert turn.request.context["phases_form_ordered_prefix"] is False
    assert turn.request.context["tombstone_retained"] is False
    assert turn.request.context["completed_phases"] == ()
    assert turn.request.context["violations"] == (
        "goal_identity_missing",
        "owner_identity_missing",
        "turn_key_identity_missing",
        "completed_phases_invalid",
        "journal_not_terminal",
    )
    assert turn.observation.decision == "replay_blocked"
    assert turn.observation.should_run is False


def test_turn_journal_blocks_unknown_status_as_unsupported() -> None:
    turn = interpret_turn_journal(
        _journal(status="retired"),
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["tombstone_retained"] is False
    assert turn.request.context["violations"] == ("journal_status_unsupported",)


def test_turn_journal_compares_identity_strings_exactly() -> None:
    journal = _journal()
    journal["goal_id"] = " fixture-goal "

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["goal_matches"] is False
    assert turn.request.context["violations"] == ("goal_mismatch",)


def test_turn_journal_blocks_present_malformed_identity_fields() -> None:
    journal = _journal()
    journal["plan"]["turn_envelope"]["agent_id"] = 7
    journal["host_result"]["turn_key"] = ""
    journal["receipt"]["turn_key"] = object()

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["owner_matches"] is False
    assert turn.request.context["turn_key_matches"] is False
    assert turn.request.context["violations"] == (
        "owner_identity_missing",
        "turn_key_identity_missing",
    )


def test_turn_journal_blocks_explicit_empty_identity_expectations() -> None:
    turn = interpret_turn_journal(
        _journal(),
        goal_id="",
        agent_id="",
        turn_key="",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["goal_matches"] is False
    assert turn.request.context["owner_matches"] is False
    assert turn.request.context["turn_key_matches"] is False
    assert turn.request.context["violations"] == (
        "goal_identity_missing",
        "owner_identity_missing",
        "turn_key_identity_missing",
    )


def test_turn_transaction_keeps_the_canonical_phase_tuple_alias() -> None:
    assert TRANSACTION_PHASES is TURN_TRANSACTION_PHASES
