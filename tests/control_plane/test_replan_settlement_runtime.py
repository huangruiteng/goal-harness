from __future__ import annotations

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.work_items import replan_settlement


def _contract(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": replan_settlement.REPLAN_SETTLEMENT_CONTRACT_SCHEMA,
        "single_binding_required": True,
        "settlement_binding": {
            "kind": "todo",
            "id": "todo_current001",
            "cli_argument": "--todo-id",
        },
        "semantic_obligation": {
            "kind": "autonomous_replan",
            "id": "replan-0000000000000001",
            "settlement_bound": False,
            "discharge": "todo_bound_writeback",
        },
        **overrides,
    }


def test_python_facade_projects_typed_replan_settlement_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return _contract()

    monkeypatch.setattr(replan_settlement, "effect_runtime_result", call)
    result = replan_settlement.project_replan_settlement_contract(
        selected_todo_id="todo_current001",
        semantic_replan_obligation_id="replan-0000000000000001",
    )

    assert result == _contract()
    assert captured == {
        "method": "work_item.replan_settlement.project",
        "params": {
            "schema_version": replan_settlement.REPLAN_SETTLEMENT_REQUEST_SCHEMA,
            "selected_todo_id": "todo_current001",
            "semantic_replan_obligation_id": "replan-0000000000000001",
        },
    }


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        _contract(single_binding_required=False),
        _contract(settlement_binding={}),
        _contract(semantic_obligation={}),
    ],
)
def test_python_facade_rejects_malformed_runtime_result(
    monkeypatch,
    malformed: object,
) -> None:
    monkeypatch.setattr(
        replan_settlement,
        "effect_runtime_result",
        lambda _method, _params: malformed,
    )
    with pytest.raises(RuntimeError, match="result (must be|shape mismatch)"):
        replan_settlement.project_replan_settlement_contract(
            selected_todo_id="todo_current001",
            semantic_replan_obligation_id="replan-0000000000000001",
        )


def test_python_facade_preserves_typed_rejection(monkeypatch) -> None:
    def reject(_method: str, _params: dict[str, object]) -> object:
        raise effect_runtime.EffectRuntimeRejected("typed projection rejected")

    monkeypatch.setattr(replan_settlement, "effect_runtime_result", reject)
    with pytest.raises(ValueError, match="typed projection rejected"):
        replan_settlement.project_replan_settlement_contract(
            selected_todo_id=None,
            semantic_replan_obligation_id="replan-0000000000000001",
        )
