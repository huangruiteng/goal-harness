from __future__ import annotations

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.turn_driver import delivery_continuity


def _runtime_result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": delivery_continuity.DELIVERY_CONTINUITY_RESULT_SCHEMA,
        "decision": "resume_in_flight",
        "reason": "same_open_todo_after_progress",
        "todo_id": "todo_current001",
        "delivery_boundary": delivery_continuity.DELIVERY_BOUNDARY_IN_FLIGHT,
        **overrides,
    }


def test_python_facade_sends_one_coarse_typed_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return _runtime_result()

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", call)
    result = delivery_continuity.evaluate_delivery_continuity(
        agent_id="codex-main",
        previous_todo_id="todo_current001",
        previous_delivery_outcome="outcome_progress",
        current_todo={
            "todo_id": "todo_current001",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": "codex-main",
        },
        actionable=True,
        capability_ready=True,
    )

    assert result == _runtime_result()
    assert captured["method"] == "turn.delivery_continuity.evaluate"
    assert captured["params"] == {
        "schema_version": delivery_continuity.DELIVERY_CONTINUITY_REQUEST_SCHEMA,
        "agent_id": "codex-main",
        "previous_todo_id": "todo_current001",
        "previous_delivery_outcome": "outcome_progress",
        "current_todo": {
            "todo_id": "todo_current001",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": "codex-main",
            "actionable": True,
            "capability_ready": True,
        },
        "preemptions": [],
    }


def test_python_facade_asks_ts_for_initial_settlement_boundary(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": delivery_continuity.DELIVERY_BOUNDARY_RESULT_SCHEMA,
            "delivery_boundary": delivery_continuity.DELIVERY_BOUNDARY_IN_FLIGHT,
            "reason": "open_advancement_todo",
            "todo_id": "todo_current001",
        }

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", call)
    result = delivery_continuity.evaluate_delivery_boundary(
        agent_id="codex-main",
        current_todo={
            "todo_id": "todo_current001",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": "codex-main",
        },
        actionable=True,
        capability_ready=True,
    )

    assert result["delivery_boundary"] == "in_flight_continuation"
    assert captured["method"] == "turn.delivery_boundary.evaluate"
    assert captured["params"] == {
        "schema_version": delivery_continuity.DELIVERY_BOUNDARY_REQUEST_SCHEMA,
        "agent_id": "codex-main",
        "current_todo": {
            "todo_id": "todo_current001",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": "codex-main",
            "actionable": True,
            "capability_ready": True,
        },
        "preemptions": [],
    }


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        _runtime_result(schema_version="loopx_delivery_continuity_result_v1"),
        _runtime_result(decision="continue maybe"),
        _runtime_result(todo_id=[]),
    ],
)
def test_python_facade_rejects_malformed_runtime_results(
    monkeypatch, malformed: object
) -> None:
    monkeypatch.setattr(
        delivery_continuity,
        "effect_runtime_result",
        lambda _method, _params: malformed,
    )
    with pytest.raises(RuntimeError, match="result (must be|shape mismatch)"):
        delivery_continuity.evaluate_delivery_continuity(
            agent_id="codex-main",
            previous_todo_id="todo_current001",
            previous_delivery_outcome="outcome_progress",
            current_todo=None,
            actionable=False,
            capability_ready=False,
        )


def test_python_facade_preserves_typed_rejection(monkeypatch) -> None:
    def reject(_method: str, _params: dict[str, object]) -> object:
        raise effect_runtime.EffectRuntimeRejected("typed transition rejected")

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", reject)
    with pytest.raises(ValueError, match="typed transition rejected"):
        delivery_continuity.evaluate_delivery_continuity(
            agent_id="codex-main",
            previous_todo_id="todo_current001",
            previous_delivery_outcome="outcome_progress",
            current_todo=None,
            actionable=False,
            capability_ready=False,
        )
