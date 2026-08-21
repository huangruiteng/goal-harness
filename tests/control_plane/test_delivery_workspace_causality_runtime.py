from __future__ import annotations

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.quota import settlement_workspace_causality as causality


def _result(**values: object) -> dict[str, object]:
    return {
        "schema_version": causality.DELIVERY_WORKSPACE_CAUSALITY_RESULT_SCHEMA,
        **values,
    }


def test_python_facade_sends_one_normalized_classification_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return _result(
            causality={
                "schema_version": causality.DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
                "todo_id": "todo_write",
                "requirement": "required",
                "source": "selected_todo_contract",
                "reason": "declared_repository_or_write_contract",
            }
        )

    monkeypatch.setattr(causality, "effect_runtime_result", call)

    assert causality.build_delivery_workspace_causality(
        {
            "todo_id": "TODO_WRITE",
            "task_repository": "https://github.com/example/project",
            "required_write_scope": "src/**",
            "required_capabilities": ["filesystem_write", "shell"],
        }
    ) == {
        "schema_version": causality.DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
        "todo_id": "todo_write",
        "requirement": "required",
        "source": "selected_todo_contract",
        "reason": "declared_repository_or_write_contract",
    }
    assert captured["method"] == "quota.delivery_workspace_causality.evaluate"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["operation"] == "classify"
    assert params["normalized_todo_contract"] == {
        "todo_id": "todo_write",
        "task_repository": "git:github.com/example/project",
        "required_write_scopes": ["src/**"],
        "required_capabilities": ["filesystem_write", "shell"],
        "continuation_policy": None,
        "source": "selected_todo_contract",
    }


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {},
        _result(causality=[]),
        _result(causality={"schema_version": "delivery_workspace_causality_v0"}),
        _result(
            causality={
                "schema_version": "delivery_workspace_causality_v0",
                "todo_id": "todo_write",
                "requirement": "optional",
                "source": "selected_todo_contract",
                "reason": "invalid_requirement",
            }
        ),
    ],
)
def test_python_facade_rejects_malformed_runtime_results(
    monkeypatch, malformed: object
) -> None:
    monkeypatch.setattr(
        causality,
        "effect_runtime_result",
        lambda _method, _params: malformed,
    )

    with pytest.raises(RuntimeError, match="result (must be|shape mismatch)"):
        causality.build_delivery_workspace_causality(
            {"todo_id": "todo_write", "required_capabilities": ["filesystem_write"]}
        )


def test_python_facade_surfaces_typed_runtime_rejection(monkeypatch) -> None:
    def reject(_method: str, _params: dict[str, object]) -> object:
        raise effect_runtime.EffectRuntimeRejected("typed causality rejected")

    monkeypatch.setattr(causality, "effect_runtime_result", reject)

    with pytest.raises(RuntimeError, match="typed causality rejected"):
        causality.build_delivery_workspace_causality(
            {"todo_id": "todo_write", "required_capabilities": ["filesystem_write"]}
        )
