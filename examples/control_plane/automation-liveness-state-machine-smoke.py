#!/usr/bin/env python3
"""Smoke-test heartbeat automation liveness decisions outside quota."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.agents.agent_scope import AgentScopeFrontierAction  # noqa: E402
from loopx.control_plane.scheduler.automation_liveness import (  # noqa: E402
    build_automation_liveness,
)


def payload(
    *,
    effective_action: str = "normal_run",
    recommended_mode: str = "",
    must_attempt_work: bool = False,
    agent_scope_frontier: dict | None = None,
) -> dict:
    result = {
        "effective_action": effective_action,
        "heartbeat_recommendation": {
            "recommended_mode": recommended_mode,
        },
        "execution_obligation": {
            "must_attempt_work": must_attempt_work,
        },
    }
    if agent_scope_frontier is not None:
        result["agent_scope_frontier"] = agent_scope_frontier
    return result


def assert_common_liveness_fields(liveness: dict) -> None:
    assert liveness["schema_version"] == "automation_liveness_v0", liveness
    assert liveness["keep_active"] is True, liveness
    assert liveness["pause_allowed"] is False, liveness
    assert "pause/delete only after" in liveness["pause_policy"], liveness


def assert_monitor_quiet_skip_keeps_heartbeat_active() -> None:
    liveness = build_automation_liveness(
        payload(
            effective_action="monitor_quiet_skip",
            recommended_mode="monitor_quiet_until_material_transition",
        )
    )
    assert_common_liveness_fields(liveness)
    assert liveness["automation_action"] == "keep_active_quiet", liveness
    assert "material monitor transition" in liveness["next_trigger"], liveness
    assert liveness["spend_policy"] == "no quota spend for unchanged monitor-only polls", liveness


def assert_prompt_upgrade_repairs_identity_without_spend() -> None:
    liveness = build_automation_liveness(
        payload(effective_action="automation_prompt_upgrade_required")
    )
    assert_common_liveness_fields(liveness)
    assert liveness["automation_action"] == "repair_automation_prompt_identity", liveness
    assert "registered agent id" in liveness["reason"], liveness
    assert liveness["spend_policy"] == "no quota spend for identity prompt upgrade preflight", liveness


def assert_successor_replan_requires_bounded_work() -> None:
    liveness = build_automation_liveness(
        payload(effective_action=AgentScopeFrontierAction.SUCCESSOR_REPLAN_REQUIRED.value)
    )
    assert_common_liveness_fields(liveness)
    assert liveness["automation_action"] == "execute_bounded_work", liveness
    assert "ready deferred successor" in liveness["reason"], liveness
    assert liveness["next_trigger"] == "deferred successor replan writeback or fresh quota guard", liveness
    assert liveness["spend_policy"] == "spend once only after validated successor replan/todo writeback", liveness


def assert_monitor_blocked_successor_replan_uses_gate_repair_copy() -> None:
    liveness = build_automation_liveness(
        payload(
            effective_action=AgentScopeFrontierAction.SUCCESSOR_REPLAN_REQUIRED.value,
            agent_scope_frontier={
                "monitor_blocked_resume_candidates": [
                    {"todo_id": "todo_monitor_gated_successor"}
                ],
            },
        )
    )
    assert_common_liveness_fields(liveness)
    assert liveness["automation_action"] == "execute_bounded_work", liveness
    assert "open standing monitor" in liveness["reason"], liveness
    assert liveness["next_trigger"] == "standing monitor gate repair writeback or fresh quota guard", liveness
    assert liveness["spend_policy"] == "spend once only after validated gate repair/todo writeback", liveness


def assert_agent_scope_no_candidate_is_quiet_no_spend() -> None:
    liveness = build_automation_liveness(
        payload(effective_action=AgentScopeFrontierAction.AGENT_SCOPE_WAIT.value)
    )
    assert_common_liveness_fields(liveness)
    assert liveness["automation_action"] == "keep_active_quiet", liveness
    assert "no in-scope runnable candidate" in liveness["reason"], liveness
    assert liveness["spend_policy"] == "no quota spend for agent-scoped no-candidate checks", liveness


def assert_must_attempt_or_autonomous_replan_executes_bounded_work() -> None:
    must_attempt = build_automation_liveness(payload(must_attempt_work=True))
    assert_common_liveness_fields(must_attempt)
    assert must_attempt["automation_action"] == "execute_bounded_work", must_attempt
    assert must_attempt["spend_policy"] == "spend once only after validation and durable writeback", must_attempt

    autonomous = build_automation_liveness(
        payload(recommended_mode="autonomous_replan_required")
    )
    assert_common_liveness_fields(autonomous)
    assert autonomous["automation_action"] == "execute_bounded_work", autonomous
    assert autonomous["spend_policy"] == "spend once only after validation and durable writeback", autonomous


def assert_mapped_noop_and_default_keep_alive() -> None:
    mapped = build_automation_liveness(payload(recommended_mode="mapped_noop_if_unchanged"))
    assert_common_liveness_fields(mapped)
    assert mapped["automation_action"] == "keep_active_noop_if_unchanged", mapped
    assert mapped["spend_policy"] == "no quota spend for unchanged mapped no-op checks", mapped

    default = build_automation_liveness(payload())
    assert_common_liveness_fields(default)
    assert default["automation_action"] == "keep_active", default
    assert default["spend_policy"].startswith("follow heartbeat_recommendation"), default


def main() -> int:
    assert_monitor_quiet_skip_keeps_heartbeat_active()
    assert_prompt_upgrade_repairs_identity_without_spend()
    assert_successor_replan_requires_bounded_work()
    assert_monitor_blocked_successor_replan_uses_gate_repair_copy()
    assert_agent_scope_no_candidate_is_quiet_no_spend()
    assert_must_attempt_or_autonomous_replan_executes_bounded_work()
    assert_mapped_noop_and_default_keep_alive()
    print("automation-liveness-state-machine-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
