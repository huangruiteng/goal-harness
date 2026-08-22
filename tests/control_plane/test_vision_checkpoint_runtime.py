from __future__ import annotations

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.goals import vision_checkpoint


def _runtime_result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": vision_checkpoint.VISION_CHECKPOINT_SCHEMA_VERSION,
        "agent_id": "codex-main",
        "required": False,
        "satisfied": True,
        "decision": "not_required",
        "triggers": [],
        "delivery_boundary": "in_flight_continuation",
        **overrides,
    }


def test_python_facade_sends_explicit_boundary_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return _runtime_result()

    monkeypatch.setattr(vision_checkpoint, "effect_runtime_result", call)
    result = vision_checkpoint.build_vision_checkpoint(
        agent_id="codex-main",
        agent_vision=None,
        existing_agent_vision=None,
        vision_unchanged_reason=None,
        delivery_outcome="outcome_progress",
        active_state_next_action_update=None,
        delivery_boundary="in_flight_continuation",
        todo_id="todo_current001",
    )

    assert result == _runtime_result()
    assert captured["method"] == "goal.vision_checkpoint.evaluate"
    assert captured["params"] == {
        "schema_version": vision_checkpoint.VISION_CHECKPOINT_REQUEST_SCHEMA,
        "agent_id": "codex-main",
        "agent_vision": None,
        "existing_agent_vision": None,
        "vision_unchanged_reason": None,
        "delivery_outcome": "outcome_progress",
        "active_state_next_action_would_update": False,
        "delivery_boundary": "in_flight_continuation",
        "todo_id": "todo_current001",
        "completion_todo_id": None,
        "autonomous_replan_recorded": False,
    }


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        _runtime_result(required="false"),
        _runtime_result(decision="skip"),
        _runtime_result(triggers={}),
    ],
)
def test_python_facade_rejects_malformed_runtime_results(
    monkeypatch, malformed: object
) -> None:
    monkeypatch.setattr(
        vision_checkpoint,
        "effect_runtime_result",
        lambda _method, _params: malformed,
    )
    with pytest.raises(RuntimeError, match="result (must be|shape mismatch)"):
        vision_checkpoint.build_vision_checkpoint(
            agent_id=None,
            agent_vision=None,
            existing_agent_vision=None,
            vision_unchanged_reason=None,
            delivery_outcome=None,
            active_state_next_action_update=None,
        )


def test_python_facade_preserves_typed_rejection(monkeypatch) -> None:
    def reject(_method: str, _params: dict[str, object]) -> object:
        raise effect_runtime.EffectRuntimeRejected("typed checkpoint rejected")

    monkeypatch.setattr(vision_checkpoint, "effect_runtime_result", reject)
    with pytest.raises(ValueError, match="typed checkpoint rejected"):
        vision_checkpoint.build_vision_checkpoint(
            agent_id="codex-main",
            agent_vision=None,
            existing_agent_vision=None,
            vision_unchanged_reason=None,
            delivery_outcome="outcome_progress",
            active_state_next_action_update=None,
            delivery_boundary="in_flight_continuation",
            todo_id="todo_current001",
        )
