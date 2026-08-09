from __future__ import annotations

from pathlib import Path

from loopx.canary.maintainability_ratchet import (
    build_control_plane_maintainability_report,
    module_metric_baseline,
    module_metrics,
)
from loopx.control_plane.effect_program import interpret_quota_should_run_packet
from loopx.control_plane.quota.turn_envelope import build_turn_envelope


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_METRIC_BASELINE_PATH = (
    REPOSITORY_ROOT / "loopx" / "canary" / "module_metric_baseline.json"
)
RFC_MODULE_BUDGETS = {
    "loopx/quota.py": 1999,
    "loopx/status.py": 1999,
    "loopx/heartbeat_prompt.py": 1199,
}


def test_m6_rfc_module_budgets_are_enforced_by_the_ratchet_baseline() -> None:
    baseline = module_metric_baseline(MODULE_METRIC_BASELINE_PATH)

    for relative_path, rfc_ceiling in RFC_MODULE_BUDGETS.items():
        ceiling = baseline[relative_path]["lines"]
        assert ceiling <= rfc_ceiling, relative_path
        actual = module_metrics(REPOSITORY_ROOT / relative_path)["lines"]
        assert actual <= ceiling, relative_path


def test_m6_maintainability_ratchet_has_no_unreviewed_debt() -> None:
    report = build_control_plane_maintainability_report(REPOSITORY_ROOT)

    assert report["ok"] is True
    assert report["unreviewed_count"] == 0
    assert report["stale_exception_count"] == 0
    assert report["category_counts"].get("module_metric_budget", 0) == 0


def test_quota_turn_envelope_consumes_effect_turn_at_runtime() -> None:
    payload = {
        "ok": True,
        "goal_id": "fixture-goal",
        "agent_identity": {"agent_id": "codex-fixture"},
        "decision": "run",
        "should_run": True,
        "effective_action": "normal_run",
        "recommended_action": "advance one bounded slice",
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": "bounded_delivery",
            "user_channel": {
                "action_required": False,
                "notify": "DONT_NOTIFY",
            },
            "agent_channel": {
                "must_attempt": True,
                "delivery_allowed": True,
                "quiet_noop_allowed": False,
                "primary_action": "advance one slice",
            },
            "cli_channel": {
                "next_cli_actions": [
                    "loopx refresh-state --goal-id fixture-goal --execute"
                ],
                "spend_allowed_now": False,
                "spend_after_validation": True,
                "spend_policy": "spend once after validated writeback",
            },
        },
        "scheduler_hint": {
            "action": "run_now",
            "cadence_class": "active_work",
            "codex_app": {
                "apply": "none_already_applied",
                "host_action": "none",
            },
        },
        "work_lane_contract": {
            "lane": "advancement_task",
            "obligation": "advance_bounded_segment",
        },
    }
    turn = interpret_quota_should_run_packet(payload)
    envelope = build_turn_envelope(payload)

    assert envelope["action"]["recommended_action"] == (
        turn.observation.recommended_action
    )
    assert envelope["writeback"]["next_cli_actions"] == list(
        turn.next_effect.cli_actions
    )
    assert envelope["scheduler"]["action"] == turn.next_effect.scheduler_action
    assert envelope["scheduler"]["cadence_class"] == turn.next_effect.cadence_class
