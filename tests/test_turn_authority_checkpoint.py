from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from loopx.control_plane.turn_driver import (
    TurnAuthorityCheckpointSession,
    build_turn_authority_command_guard,
)
from loopx.control_plane.turn_driver.authority_checkpoint import (
    build_turn_authority_checkpoint_controller,
)


def _request() -> dict[str, object]:
    return {
        "schema_version": "loopx_turn_authority_checkpoint_request_v0",
        "checkpoint": "host_admission",
        "goal_id": "goal-fixture",
        "agent_id": "agent-fixture",
        "todo_id": "todo-fixture",
        "turn_key": "sha256:" + ("b" * 64),
        "effect_id": "effect-fixture",
        "effect_ref": "effect-fixture",
        "authority_binding": None,
    }


def test_command_guard_uses_json_argv_stdin_and_one_typed_stdout(
    tmp_path: Path,
) -> None:
    script = """
import json
import sys
request = json.load(sys.stdin)
assert request["checkpoint"] == "host_admission"
json.dump({
    "ok": True,
    "binding": {
        "schema_version": "loopx_turn_authority_binding_v0",
        "store_identity": "file:00000000000000000000000000000001",
        "operation_id": "operation-fixture",
        "receipt_digest": "sha256:" + "c" * 64,
        "authority_revision": 1,
        "todo_revision": 1,
        "lease_id": "lease-fixture",
        "lease_epoch": 1,
        "expires_at": "2030-01-01T00:00:00.000Z"
    }
}, sys.stdout)
"""
    guard = build_turn_authority_command_guard(
        [sys.executable, "-c", script],
        project=tmp_path,
        timeout_seconds=2,
    )

    result = guard(_request())

    assert result["ok"] is True
    assert result["binding"]["lease_epoch"] == 1


@pytest.mark.parametrize(
    "script",
    (
        "raise SystemExit(7)",
        "import sys; sys.stdout.write('not-json')",
        "import json, sys; json.dump(['not-an-object'], sys.stdout)",
    ),
)
def test_command_guard_process_failures_collapse_to_public_typed_rejection(
    tmp_path: Path,
    script: str,
) -> None:
    guard = build_turn_authority_command_guard(
        [sys.executable, "-c", script],
        project=tmp_path,
        timeout_seconds=2,
    )

    result = guard(_request())

    assert result == {
        "ok": False,
        "reason_code": "authority_guard_unavailable",
        "reason": "Turn authority guard command did not return a valid receipt",
    }
    assert "private" not in json.dumps(result)


def test_command_guard_rejects_empty_argv(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty argv"):
        build_turn_authority_command_guard(
            [],
            project=tmp_path,
            timeout_seconds=2,
        )


def test_session_identity_copy_and_bad_journal_fail_closed() -> None:
    journal: dict[str, object] = {
        "authority_checkpoint_guard": {
            "schema_version": "loopx_turn_authority_checkpoint_journal_v0",
            "checkpoints": {"host_admission": {"attempt": "corrupt"}},
        }
    }
    persisted = 0

    def persist() -> None:
        nonlocal persisted
        persisted += 1

    session = TurnAuthorityCheckpointSession(
        lambda _request: pytest.fail("corrupt journal must fail before provider"),
        goal_id="goal-fixture",
        agent_id="agent-fixture",
        todo_id="todo-fixture",
        turn_key="sha256:" + ("e" * 64),
        effect_id="effect-fixture",
        journal=journal,
        persist=persist,
    )
    identity = session.identity
    identity["agent_id"] = "mutated-copy"

    outcome = session.checkpoint("host_admission", effect_ref="effect-fixture")

    assert session.identity["agent_id"] == "agent-fixture"
    assert outcome.accepted is False
    assert outcome.receipt["reason_code"] == "authority_journal_invalid"
    assert journal["authority_checkpoint_guard"]["invalid_prior_state"] is True
    assert persisted == 1


def test_completion_context_rejects_unhashable_successor_before_guard() -> None:
    session = TurnAuthorityCheckpointSession(
        lambda _request: pytest.fail("invalid completion must not reach guard"),
        goal_id="goal-fixture",
        agent_id="agent-fixture",
        todo_id="todo-fixture",
        turn_key="sha256:" + ("a" * 64),
        effect_id="effect-fixture",
        journal={},
        persist=lambda: pytest.fail("invalid completion must not persist"),
    )

    with pytest.raises(ValueError, match="successor Todo ids"):
        session.checkpoint(
            "authority_complete",
            effect_ref="effect-fixture#quota_spend",
            completion={
                "todo_id": "todo-fixture",
                "continuation": "successor",
                "successor_todo_ids": [{}],
            },
        )


def test_default_off_controller_does_not_parse_turn_lineage() -> None:
    journal: dict[str, object] = {}
    controller = build_turn_authority_checkpoint_controller(
        None,
        plan={},
        transaction_plan={},
        journal=journal,
        turn_key="sha256:" + ("d" * 64),
        persist=lambda: pytest.fail("default-off controller must not persist"),
    )
    effects = controller.settlement_effects(
        result={"result_kind": "validated_progress"},
        writeback=lambda _result, effect_ref: {
            "ok": True,
            "appended": True,
            "effect_ref": effect_ref,
        },
        completion_writeback=None,
        completion_intent=None,
        terminal_closeout=None,
        spend=lambda effect_ref: {
            "ok": True,
            "appended": True,
            "effect_ref": effect_ref,
        },
        terminal_checkpoint=lambda _payload: pytest.fail(
            "non-terminal Turn must not checkpoint closeout"
        ),
    )

    assert controller.enabled is False
    assert effects.writeback("writeback-ref")["effect_ref"] == "writeback-ref"
    assert effects.spend("spend-ref")["effect_ref"] == "spend-ref"
    assert effects.terminal_closeout is None
    assert effects.terminal_checkpoint is None
    assert controller.run_scheduler(
        lambda spend: {"completed": True, "spend": spend},
        {"receipt": "quota"},
        terminal_closeout_required=False,
    ) == {"completed": True, "spend": {"receipt": "quota"}}
    assert journal == {}


def test_resumed_authority_turn_without_guard_fails_closed_at_admission() -> None:
    journal: dict[str, object] = {
        "authority_checkpoint_guard": {
            "schema_version": "loopx_turn_authority_checkpoint_journal_v0",
            "checkpoints": {},
        }
    }
    persisted = 0

    def persist() -> None:
        nonlocal persisted
        persisted += 1

    controller = build_turn_authority_checkpoint_controller(
        None,
        plan={
            "turn_envelope": {
                "goal_id": "goal-fixture",
                "agent_id": "agent-fixture",
                "action": {"selected_todo": {"todo_id": "todo-fixture"}},
            }
        },
        transaction_plan={
            "settlement_plan": {"identity": {"effect_id": "effect-fixture"}}
        },
        journal=journal,
        turn_key="sha256:" + ("f" * 64),
        persist=persist,
    )

    admitted = controller.admit_host(
        completed_phases=[],
        failure=lambda reason: {"reason": reason, "receipt": {"typed": True}},
    )

    assert admitted is False
    assert journal["status"] == "failed"
    assert journal["result_kind"] == "authority_rejected"
    checkpoint = journal["authority_checkpoint_guard"]["checkpoints"]["host_admission"]
    assert checkpoint["reason_code"] == "authority_guard_missing"
    assert persisted == 2
