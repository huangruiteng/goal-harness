from __future__ import annotations

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.turn_driver import delivery_continuity


def _continuity_result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": delivery_continuity.DELIVERY_CONTINUITY_RESULT_SCHEMA,
        "decision": "resume_in_flight",
        "reason": "same_open_todo_after_progress",
        "todo_id": "todo_current001",
        "delivery_boundary": delivery_continuity.DELIVERY_BOUNDARY_IN_FLIGHT,
        **overrides,
    }


def _boundary_result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": delivery_continuity.DELIVERY_BOUNDARY_RESULT_SCHEMA,
        "delivery_boundary": delivery_continuity.DELIVERY_BOUNDARY_IN_FLIGHT,
        "reason": "open_advancement_todo",
        "todo_id": "todo_current001",
        **overrides,
    }


def _route_result(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": delivery_continuity.DELIVERY_ROUTING_RESULT_SCHEMA,
        "selection": "continuity",
        "continuity": _continuity_result(),
        "boundary": _boundary_result(),
        **overrides,
    }


def test_python_facade_sends_one_delivery_routing_transaction(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return _route_result()

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", call)
    current = {
        "todo_id": "todo_current001",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": "codex-main",
    }
    fallback = {
        "todo_id": "todo_queuehead001",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": "codex-main",
    }
    result = delivery_continuity.evaluate_delivery_route(
        agent_id="codex-main",
        previous_todo_id="todo_current001",
        previous_delivery_outcome="outcome_progress",
        continuity_todo=current,
        continuity_actionable=True,
        continuity_capability_ready=True,
        fallback_todo=fallback,
        fallback_actionable=True,
        fallback_capability_ready=True,
    )

    assert result == _route_result()
    assert captured["method"] == "turn.delivery_route.evaluate"
    assert captured["params"] == {
        "schema_version": delivery_continuity.DELIVERY_ROUTING_REQUEST_SCHEMA,
        "agent_id": "codex-main",
        "previous_todo_id": "todo_current001",
        "previous_delivery_outcome": "outcome_progress",
        "continuity_todo": {
            **current,
            "actionable": True,
            "capability_ready": True,
        },
        "fallback_todo": {
            **fallback,
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
        _route_result(schema_version="loopx_delivery_routing_result_v1"),
        _route_result(selection="continue maybe"),
        _route_result(continuity=None),
        _route_result(continuity=_continuity_result(todo_id=[])),
        _route_result(boundary=_boundary_result(reason="free-form prose")),
        _route_result(
            boundary=_boundary_result(delivery_boundary="semantic_closeout")
        ),
        _route_result(selection="none"),
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
    with pytest.raises((TypeError, RuntimeError), match="result (must be|shape mismatch)"):
        delivery_continuity.evaluate_delivery_route(
            agent_id="codex-main",
            previous_todo_id="todo_current001",
            previous_delivery_outcome="outcome_progress",
            continuity_todo=None,
            continuity_actionable=False,
            continuity_capability_ready=False,
            fallback_todo=None,
            fallback_actionable=False,
            fallback_capability_ready=False,
        )


def test_python_facade_preserves_typed_rejection(monkeypatch) -> None:
    def reject(_method: str, _params: dict[str, object]) -> object:
        raise effect_runtime.EffectRuntimeRejected("typed transition rejected")

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", reject)
    with pytest.raises(ValueError, match="typed transition rejected"):
        delivery_continuity.evaluate_delivery_route(
            agent_id="codex-main",
            previous_todo_id="todo_current001",
            previous_delivery_outcome="outcome_progress",
            continuity_todo=None,
            continuity_actionable=False,
            continuity_capability_ready=False,
            fallback_todo=None,
            fallback_actionable=False,
            fallback_capability_ready=False,
        )


def test_python_facade_ignores_unreachable_continuity_without_anchor(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def call(_method: str, params: dict[str, object]) -> dict[str, object]:
        captured.update(params)
        return _route_result(selection="none", continuity=None, boundary=None)

    monkeypatch.setattr(delivery_continuity, "effect_runtime_result", call)
    result = delivery_continuity.evaluate_delivery_route(
        agent_id="codex-main",
        previous_todo_id=None,
        previous_delivery_outcome=None,
        continuity_todo={"todo_id": "legacy-short-id"},
        continuity_actionable=True,
        continuity_capability_ready=True,
        fallback_todo=None,
        fallback_actionable=False,
        fallback_capability_ready=False,
    )

    assert result["selection"] == "none"
    assert captured["previous_todo_id"] is None
    assert captured["continuity_todo"] is None
