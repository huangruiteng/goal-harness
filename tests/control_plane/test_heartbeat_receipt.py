from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loopx.control_plane.quota.heartbeat_receipt import (
    find_heartbeat_receipt,
    upgrade_identityless_heartbeat_receipt,
)
from loopx.rollout_event_log import (
    append_rollout_event,
    build_rollout_event,
    load_rollout_events,
    rollout_event_log_path,
)

GOAL_ID = "heartbeat-receipt-fixture"
AGENT_ID = "codex-heartbeat-receipt"
TURN_ID = "turn-heartbeat-receipt-1"
TODO_ID = "todo_heartbeat_receipt"
EFFECT_ID = f"{GOAL_ID}:{AGENT_ID}:{TODO_ID}:{TURN_ID}"


def _append_receipt(
    runtime_root: Path,
    *,
    todo_id: str = "",
    effect_id: str = "",
) -> dict[str, object]:
    details: dict[str, object] = {"stall_observation": "not_applicable"}
    if todo_id:
        details["todo_id"] = todo_id
    if effect_id:
        details["settlement_effect_id"] = effect_id
    event = build_rollout_event(
        goal_id=GOAL_ID,
        event_kind="quota_should_run",
        agent_id=AGENT_ID,
        todo_id=todo_id or None,
        run_id=TURN_ID,
        status="normal_run",
        summary="heartbeat receipt fixture",
        details=details,
    )
    return append_rollout_event(
        rollout_event_log_path(runtime_root, GOAL_ID),
        event,
    )


def _upgrade(runtime_root: Path, *, todo_id: str = TODO_ID) -> tuple[dict[str, object], bool]:
    effect_id = f"{GOAL_ID}:{AGENT_ID}:{todo_id}:{TURN_ID}"
    return upgrade_identityless_heartbeat_receipt(
        runtime_root,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        turn_instance_id=TURN_ID,
        todo_id=todo_id,
        settlement_effect_id=effect_id,
        status="normal_run",
        summary="heartbeat receipt upgraded",
        details={"stall_observation": "not_applicable", "todo_id": todo_id},
    )


def test_identityless_receipt_upgrade_is_append_only_and_idempotent(
    tmp_path: Path,
) -> None:
    original = _append_receipt(tmp_path)

    corrected, appended = _upgrade(tmp_path)
    replay, replay_appended = _upgrade(tmp_path)

    assert appended is True
    assert replay_appended is False
    assert corrected["event_id"] != original["event_id"]
    assert replay["event_id"] == corrected["event_id"]
    assert corrected["causality"]["source_event_id"] == original["event_id"]
    assert corrected["causality"]["caused_by"] == original["event_id"]
    assert corrected["details"]["todo_id"] == TODO_ID
    assert corrected["details"]["settlement_effect_id"] == EFFECT_ID
    assert corrected["details"]["settlement_receipt_revision"] == "identity_upgrade"
    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL_ID))) == 2


def test_identityless_receipt_upgrade_rejects_conflicting_selected_todo(
    tmp_path: Path,
) -> None:
    _append_receipt(tmp_path)
    _upgrade(tmp_path)

    with pytest.raises(ValueError, match="conflicts with the current selected Todo"):
        _upgrade(tmp_path, todo_id="todo_conflicting")

    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL_ID))) == 2


def test_concurrent_identityless_receipt_upgrades_append_one_correction(
    tmp_path: Path,
) -> None:
    _append_receipt(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: _upgrade(tmp_path), range(16)))

    assert sum(1 for _, appended in results if appended) == 1
    assert {event["event_id"] for event, _ in results} == {
        results[0][0]["event_id"]
    }
    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL_ID))) == 2


def test_legacy_todo_only_receipt_upgrades_derived_effect_identity(
    tmp_path: Path,
) -> None:
    original = _append_receipt(tmp_path, todo_id=TODO_ID)

    corrected, appended = _upgrade(tmp_path)

    assert appended is True
    assert corrected["event_id"] != original["event_id"]
    assert corrected["details"]["settlement_effect_id"] == EFFECT_ID
    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL_ID))) == 2


def test_effect_without_todo_identity_fails_closed(tmp_path: Path) -> None:
    _append_receipt(tmp_path, effect_id=EFFECT_ID)

    with pytest.raises(ValueError, match="effect identity without a Todo"):
        find_heartbeat_receipt(
            tmp_path,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            turn_instance_id=TURN_ID,
        )
    with pytest.raises(ValueError, match="effect identity without a Todo"):
        _upgrade(tmp_path)

    assert len(load_rollout_events(rollout_event_log_path(tmp_path, GOAL_ID))) == 1


def test_effective_receipt_does_not_downgrade_after_identity_correction(
    tmp_path: Path,
) -> None:
    _append_receipt(tmp_path)
    corrected, _ = _upgrade(tmp_path)
    _append_receipt(tmp_path)

    effective = find_heartbeat_receipt(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        turn_instance_id=TURN_ID,
    )

    assert effective is not None
    assert effective["event_id"] == corrected["event_id"]
