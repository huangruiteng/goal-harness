from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.periodic_report.machine_defaults import (
    build_goal_periodic_report_delivery_identity,
    build_goal_periodic_report_delivery_plan,
    normalize_loopx_machine_defaults,
    plan_periodic_report_machine_default_backfill,
    resolve_goal_periodic_report_subscription,
    select_goal_periodic_report_executor,
)
from loopx.cli import main


def _defaults(*, enabled: bool = True, route_ref: str = "loopx-concierge") -> dict:
    periodic_report = {
        "enabled": enabled,
        "inheritance": "materialize_on_goal_connect",
        "timezone": "Asia/Shanghai",
    }
    if enabled:
        periodic_report.update(
            {
                "profile_preset": "weekly-progress",
                "route_ref": route_ref,
            }
        )
    return {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {
            "periodic_report": {
                "schema_version": "periodic_report_machine_defaults_v0",
                **periodic_report,
            }
        },
    }


def _goal(goal_id: str, *, status: str = "active") -> dict:
    return {
        "id": goal_id,
        "repo": f"/projects/{goal_id}",
        "state_file": "GOAL.md",
        "status": status,
    }


def test_machine_defaults_require_a_route_when_weekly_reports_are_enabled() -> None:
    payload = _defaults()
    payload["namespaces"]["periodic_report"].pop("route_ref")

    with pytest.raises(ValueError, match="route_ref is required"):
        normalize_loopx_machine_defaults(payload)


def test_goal_override_beats_machine_default() -> None:
    goal = _goal("research")
    goal["control_plane"] = {
        "periodic_report": {
            "enabled": False,
            "profile_preset": "weekly-progress",
            "route_ref": "project-room",
            "timezone": "UTC",
        }
    }

    subscription = resolve_goal_periodic_report_subscription(goal, _defaults())

    assert subscription["enabled"] is False
    assert subscription["route_ref"] == "project-room"
    assert subscription["source"] == "goal_override"


def test_partial_goal_override_inherits_unspecified_machine_fields() -> None:
    goal = _goal("research")
    goal["control_plane"] = {"periodic_report": {"enabled": True}}

    subscription = resolve_goal_periodic_report_subscription(goal, _defaults())

    assert subscription["enabled"] is True
    assert subscription["profile_preset"] == "weekly-progress"
    assert subscription["route_ref"] == "loopx-concierge"
    assert subscription["timezone"] == "Asia/Shanghai"
    assert subscription["source"] == "goal_override"


def test_unconfigured_goal_previews_machine_default_without_an_agent_identity() -> None:
    subscription = resolve_goal_periodic_report_subscription(
        _goal("research"), _defaults()
    )

    assert subscription == {
        "schema_version": "periodic_report_goal_subscription_v0",
        "goal_id": "research",
        "enabled": True,
        "source": "machine_default_preview",
        "profile_preset": "weekly-progress",
        "route_ref": "loopx-concierge",
        "timezone": "Asia/Shanghai",
        "effective_revision": subscription["effective_revision"],
    }
    assert "agent_id" not in subscription


def test_backfill_preserves_overrides_and_excludes_unusable_goals() -> None:
    inherited = _goal("inherited")
    overridden = _goal("overridden")
    overridden["control_plane"] = {
        "periodic_report": {"enabled": False, "timezone": "UTC"}
    }
    missing = _goal("missing")
    retired = _goal("retired", status="retired")
    registry = {"goals": [inherited, overridden, missing, retired]}

    plan = plan_periodic_report_machine_default_backfill(
        registry,
        _defaults(),
        state_file_exists=lambda path: (
            path == Path("/projects/inherited/GOAL.md")
            or path == Path("/projects/overridden/GOAL.md")
        ),
    )

    assert plan["rows"] == [
        {
            "goal_id": "inherited",
            "action": "materialize",
            "reason": "machine_default_missing",
        },
        {
            "goal_id": "overridden",
            "action": "preserve",
            "reason": "goal_override",
        },
        {
            "goal_id": "missing",
            "action": "excluded",
            "reason": "authoritative_state_unavailable",
        },
        {
            "goal_id": "retired",
            "action": "excluded",
            "reason": "goal_not_active",
        },
    ]
    assert plan["writes_required"] == 1


def test_delivery_identity_is_goal_period_route_owned_not_agent_owned() -> None:
    first = build_goal_periodic_report_delivery_identity(
        goal_id="research",
        period_start_at="2026-08-24T00:00:00+08:00",
        period_end_at="2026-08-31T00:00:00+08:00",
        route_id="loopx-concierge",
    )
    replay = build_goal_periodic_report_delivery_identity(
        goal_id="research",
        period_start_at="2026-08-24T00:00:00+08:00",
        period_end_at="2026-08-31T00:00:00+08:00",
        route_id="loopx-concierge",
    )

    assert first == replay
    assert set(first) == {
        "schema_version",
        "goal_id",
        "period_start_at",
        "period_end_at",
        "route_id",
        "idempotency_key",
    }
    assert "agent_id" not in first


def test_reporting_agent_is_preferred_but_failover_keeps_goal_identity() -> None:
    preferred = select_goal_periodic_report_executor(
        reporting_agent_id="agent-b",
        eligible_agent_ids=["agent-c", "agent-b", "agent-a"],
    )
    failover = select_goal_periodic_report_executor(
        reporting_agent_id="agent-b",
        eligible_agent_ids=["agent-c", "agent-a"],
    )

    assert preferred["selected_agent_id"] == "agent-b"
    assert preferred["selection_reason"] == "reporting_agent_preferred"
    assert failover["selected_agent_id"] == "agent-a"
    assert failover["selection_reason"] == "reporting_agent_unavailable_failover"


def test_goal_delivery_plan_prefers_the_candidate_reporting_agent() -> None:
    result = build_goal_periodic_report_delivery_plan(
        {
            "schema_version": "periodic_report_goal_delivery_plan_request_v0",
            "goal": _goal("research"),
            "machine_defaults": _defaults(),
            "period_window": {
                "start_at": "2026-08-24T00:00:00+08:00",
                "end_at": "2026-08-31T00:00:00+08:00",
            },
            "reporting_agent_id": "agent-b",
            "eligible_agent_ids": ["agent-a", "agent-b"],
        }
    )

    assert result["status"] == "ready"
    assert result["executor"]["selected_agent_id"] == "agent-b"
    assert "agent_id" not in result["delivery_identity"]


def test_delivery_identity_normalizes_equivalent_timestamp_offsets() -> None:
    local = build_goal_periodic_report_delivery_identity(
        goal_id="research",
        period_start_at="2026-08-24T08:00:00+08:00",
        period_end_at="2026-08-31T08:00:00+08:00",
        route_id="loopx-concierge",
    )
    utc = build_goal_periodic_report_delivery_identity(
        goal_id="research",
        period_start_at="2026-08-24T00:00:00Z",
        period_end_at="2026-08-31T00:00:00Z",
        route_id="loopx-concierge",
    )

    assert local == utc


def test_delivery_identity_rejects_an_invalid_period() -> None:
    with pytest.raises(ValueError, match="end must be after"):
        build_goal_periodic_report_delivery_identity(
            goal_id="research",
            period_start_at="2026-08-31T00:00:00Z",
            period_end_at="2026-08-24T00:00:00Z",
            route_id="loopx-concierge",
        )


def test_machine_default_preview_cli_is_an_effect_free_active_callsite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "GOAL.md"
    state_path.write_text("# Goal\n", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "research",
                        "repo": str(tmp_path),
                        "state_file": "GOAL.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    defaults_path = tmp_path / "machine-defaults.json"
    defaults_path.write_text(json.dumps(_defaults()), encoding="utf-8")

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--format",
                "json",
                "periodic-report",
                "plan-machine-defaults",
                "--config-json",
                str(defaults_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["writes_required"] == 1
    assert payload["rows"] == [
        {
            "goal_id": "research",
            "action": "materialize",
            "reason": "machine_default_missing",
        }
    ]


def test_goal_delivery_plan_cli_prefers_the_reporting_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text('{"goals": []}', encoding="utf-8")
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "periodic_report_goal_delivery_plan_request_v0",
                "goal": _goal("research"),
                "machine_defaults": _defaults(),
                "period_window": {
                    "start_at": "2026-08-24T00:00:00+08:00",
                    "end_at": "2026-08-31T00:00:00+08:00",
                },
                "reporting_agent_id": "agent-b",
                "eligible_agent_ids": ["agent-a", "agent-b"],
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--format",
                "json",
                "periodic-report",
                "plan-goal-delivery",
                "--request-json",
                str(request_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["executor"]["reporting_agent_id"] == "agent-b"
    assert payload["executor"]["selected_agent_id"] == "agent-b"
    assert payload["executor"]["selection_reason"] == "reporting_agent_preferred"
    assert "agent_id" not in payload["delivery_identity"]
