from __future__ import annotations

from pathlib import Path

from loopx.control_plane.capability_hooks import (
    INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    InteractionProjectionHookRegistration,
    dispatch_interaction_projection_hooks,
)
from loopx.control_plane.quota.live_decision import (
    build_live_quota_should_run_decision,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload


def _provider_status(*, allowed: bool) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": "repository_change_window_git_hook_status_v2",
        "status": "ready",
        "installed": True,
        "enabled": True,
        "provider_id": "git-hook",
        "enforcement_level": "reference_guard",
        "contains_personal_path": False,
        "checks": [
            {"check": "provider_schema", "ok": True, "status": "current"},
            {"check": "hook_runtime_contract", "ok": True, "status": "current"},
        ],
        "decision": {
            "schema_version": "repository_change_window_decision_v0",
            "allowed": allowed,
            "reason": (
                "outside_blocked_window" if allowed else "inside_blocked_window"
            ),
            "timezone": "Asia/Shanghai",
            "observed_at": "2026-08-24T11:00:00+08:00",
            "next_eligible_at": (
                "2026-08-24T11:00:00+08:00"
                if allowed
                else "2026-08-24T12:00:00+08:00"
            ),
        },
    }


def _hook(
    *,
    status: dict[str, object] | None = None,
    raises: bool = False,
    hook_id: str = "test.repository_delivery",
) -> InteractionProjectionHookRegistration:
    def produce() -> dict[str, object]:
        if raises:
            raise RuntimeError("private producer detail")
        if status is None:
            return {
                "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
                "hook_id": hook_id,
                "capability_id": "repository-change-window",
                "phase": "interaction_projection",
                "status": "not_applicable",
                "projection_slot": None,
                "payload": None,
            }
        return {
            "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": hook_id,
            "capability_id": "repository-change-window",
            "phase": "interaction_projection",
            "status": "candidate",
            "projection_slot": "repository_delivery",
            "payload": status,
        }

    return InteractionProjectionHookRegistration(
        hook_id=hook_id,
        capability_id="repository-change-window",
        projection_slots=("repository_delivery",),
        requested_read_scope=("repository_status",),
        producer=produce,
    )


def test_dispatch_projects_verified_gate_and_isolates_provider_failure() -> None:
    dispatch = dispatch_interaction_projection_hooks(
        [
            _hook(status=_provider_status(allowed=False)),
            _hook(raises=True, hook_id="test.failed"),
        ]
    )

    assert dispatch["projected_hooks"] == ["test.repository_delivery"]
    assert dispatch["failures"] == [
        {
            "hook_id": "test.failed",
            "capability_id": "repository-change-window",
            "error_code": "producer_failed",
        }
    ]
    assert "private producer detail" not in str(dispatch)
    gate = dispatch["projections"]["repository_delivery"]
    assert gate["state"] == "blocked"
    assert gate["change_window_admission"] == {
        "prepare_dirty_worktree": True,
        "validate_dirty_worktree": True,
        "commit": False,
        "push": False,
    }
    assert gate["next_eligible_at"] == "2026-08-24T12:00:00+08:00"


def test_dispatch_does_not_project_unverified_or_conflicting_provider() -> None:
    external = {
        "ok": True,
        "schema_version": "repository_change_window_git_hook_status_v2",
        "status": "effective_external_guard_detected",
        "installed": False,
        "enabled": False,
        "provider_id": "git-hook",
    }
    assert dispatch_interaction_projection_hooks([_hook(status=external)])["projections"] == {}

    conflict = dispatch_interaction_projection_hooks(
        [
            _hook(status=_provider_status(allowed=True), hook_id="test.first"),
            _hook(status=_provider_status(allowed=True), hook_id="test.second"),
        ]
    )
    assert conflict["projected_hooks"] == ["test.first"]
    assert conflict["failures"][0]["error_code"] == "projection_slot_conflict"


def test_registration_is_admitted_before_the_provider_runs() -> None:
    invoked = False

    def produce() -> dict[str, object]:
        nonlocal invoked
        invoked = True
        raise AssertionError("invalid registration must not invoke provider")

    invalid = InteractionProjectionHookRegistration(
        hook_id="test.invalid_budget",
        capability_id="repository-change-window",
        projection_slots=("repository_delivery",),
        requested_read_scope=("repository_status",),
        producer=produce,
        max_result_bytes=100,
    )
    dispatch = dispatch_interaction_projection_hooks([invalid])

    assert invoked is False
    assert dispatch["failures"] == [
        {
            "hook_id": "test.invalid_budget",
            "capability_id": "repository-change-window",
            "error_code": "registration_rejected",
        }
    ]


def test_live_interaction_contract_carries_hook_projection(tmp_path: Path) -> None:
    goal_id = "repository-delivery-fixture"
    status_payload = quota_status_payload(
        goal_id=goal_id,
        status="active",
        agent_todo_items=[
            {
                "index": 1,
                "text": "Prepare and validate the bounded change.",
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
            }
        ],
        recommended_action="Prepare and validate the bounded change.",
        next_action="Prepare and validate the bounded change.",
    )
    packet = build_live_quota_should_run_decision(
        status_payload,
        goal_id=goal_id,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        scheduler_execution_context={
            "host_surface": "generic_cli",
            "scheduler_owner": "agent_cli_loop",
            "execution_mode": "interactive",
        },
        interaction_projection_hooks=[
            _hook(status=_provider_status(allowed=False))
        ],
    )

    interaction = packet["interaction_contract"]
    assert interaction["agent_channel"]["delivery_allowed"] is True
    assert interaction["repository_delivery"]["state"] == "blocked"
    assert "capability_hook_dispatch" not in packet


def test_live_packet_exposes_only_bounded_hook_failure_diagnostic(
    tmp_path: Path,
) -> None:
    status_payload = quota_status_payload(
        goal_id="hook-failure",
        status="active",
        recommended_action="No eligible work.",
    )
    packet = build_live_quota_should_run_decision(
        status_payload,
        goal_id="hook-failure",
        agent_id=None,
        available_capabilities=[],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        interaction_projection_hooks=[_hook(raises=True)],
    )

    assert "repository_delivery" not in packet["interaction_contract"]
    assert packet["capability_hook_dispatch"]["failures"] == [
        {
            "hook_id": "test.repository_delivery",
            "capability_id": "repository-change-window",
            "error_code": "producer_failed",
        }
    ]
    assert "private producer detail" not in str(packet)
