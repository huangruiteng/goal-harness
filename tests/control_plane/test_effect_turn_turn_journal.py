from __future__ import annotations

from copy import deepcopy
from typing import Any

from loopx.control_plane.effect_program import EffectNext, interpret_turn_journal


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
