from __future__ import annotations

from loopx.control_plane.capability_hooks import (
    TURN_START_HOOK_RESULT_SCHEMA_VERSION,
    TurnStartHookRegistration,
    dispatch_turn_start_hooks,
)


def _result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": TURN_START_HOOK_RESULT_SCHEMA_VERSION,
        "hook_id": "operator_inbox.turn_start_sync",
        "capability_id": "operator-inbox",
        "phase": "turn_start",
        "status": "observed",
        "observation_count": 1,
        "agent_read_required": True,
        "external_reads_performed": True,
        "local_private_state_mutated": True,
        "private_content_returned": False,
        "provider_payload_returned": False,
        "error_code": None,
        **overrides,
    }


def _hook(producer: object) -> TurnStartHookRegistration:
    return TurnStartHookRegistration(
        hook_id="operator_inbox.turn_start_sync",
        capability_id="operator-inbox",
        requested_read_scope=("provider_history",),
        requested_write_scope=("owner_private_inbox", "owner_private_cursor"),
        producer=producer,  # type: ignore[arg-type]
    )


def test_turn_start_hook_returns_only_validated_agent_read_obligation() -> None:
    dispatch = dispatch_turn_start_hooks([_hook(lambda: _result())])

    assert dispatch["failures"] == []
    assert dispatch["invoked_count"] == 1
    assert dispatch["results"][0]["agent_read_required"] is True
    assert dispatch["results"][0]["observation_count"] == 1
    assert "content" not in dispatch["results"][0]


def test_provider_shape_mismatch_is_not_misclassified_as_empty() -> None:
    malformed = _result()
    malformed.pop("agent_read_required")

    dispatch = dispatch_turn_start_hooks([_hook(lambda: malformed)])

    assert dispatch["results"] == []
    assert dispatch["failures"] == [
        {
            "hook_id": "operator_inbox.turn_start_sync",
            "capability_id": "operator-inbox",
            "error_code": "contract_rejected",
        }
    ]


def test_turn_start_hooks_are_single_flight_by_identity() -> None:
    hook = _hook(lambda: _result())

    dispatch = dispatch_turn_start_hooks([hook, hook])

    assert dispatch["invoked_count"] == 1
    assert dispatch["failures"][0]["error_code"] == "duplicate_hook_id"
