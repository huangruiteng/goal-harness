"""Python adapter for the TypeScript-owned replan settlement projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result

REPLAN_SETTLEMENT_REQUEST_SCHEMA = "loopx_replan_settlement_request_v0"
REPLAN_SETTLEMENT_CONTRACT_SCHEMA = "replan_settlement_contract_v0"


def project_replan_settlement_contract(
    *,
    selected_todo_id: str | None,
    semantic_replan_obligation_id: str,
) -> dict[str, Any]:
    """Return the one causal binding for a semantic replan writeback."""

    try:
        result = effect_runtime_result(
            "work_item.replan_settlement.project",
            {
                "schema_version": REPLAN_SETTLEMENT_REQUEST_SCHEMA,
                "selected_todo_id": selected_todo_id,
                "semantic_replan_obligation_id": semantic_replan_obligation_id,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript replan settlement result must be an object")
    binding = result.get("settlement_binding")
    obligation = result.get("semantic_obligation")
    if (
        result.get("schema_version") != REPLAN_SETTLEMENT_CONTRACT_SCHEMA
        or result.get("single_binding_required") is not True
        or not isinstance(binding, Mapping)
        or binding.get("kind") not in {"todo", "autonomous_replan"}
        or not isinstance(binding.get("id"), str)
        or binding.get("cli_argument") not in {"--todo-id", "--replan-obligation-id"}
        or not isinstance(obligation, Mapping)
        or obligation.get("kind") != "autonomous_replan"
        or not isinstance(obligation.get("id"), str)
        or not isinstance(obligation.get("settlement_bound"), bool)
        or obligation.get("discharge")
        not in {"direct_settlement", "todo_bound_writeback"}
    ):
        raise RuntimeError("TypeScript replan settlement result shape mismatch")
    return dict(result)
