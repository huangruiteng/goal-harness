from __future__ import annotations

from collections.abc import Sequence


PLANNING_HORIZON_REGRESSION_GATE_ACTION_ORACLE = (
    "planning_horizon_regression_gate_v0"
)


def planning_horizon_regression_gate_failures(
    actions: Sequence[str],
) -> list[str]:
    """Grade semantic stages without requiring one memorized trajectory."""

    failures: list[str] = []
    if not actions or actions[0] != "inspect":
        failures.append("action_oracle:first_action_must_inspect")
    elif "test" not in actions[1:-2]:
        failures.append("action_oracle:test_must_precede_settlement")
    if list(actions[-2:]) != ["writeback", "spend"]:
        failures.append("action_oracle:settlement_suffix_mismatch")
    premature_settlement = sorted({"writeback", "spend"} & set(actions[:-2]))
    failures.extend(
        f"action_oracle:premature_settlement_action:{kind}"
        for kind in premature_settlement
    )
    forbidden = sorted({"edit", "notify", "stop", "wait"} & set(actions))
    failures.extend(f"action_oracle:forbidden_action:{kind}" for kind in forbidden)
    return failures


def model_behavior_action_oracle_failures(
    oracle: str | None,
    actions: Sequence[str],
) -> list[str]:
    if oracle is None:
        return []
    if oracle != PLANNING_HORIZON_REGRESSION_GATE_ACTION_ORACLE:
        raise ValueError(f"unknown action oracle: {oracle}")
    return planning_horizon_regression_gate_failures(actions)
