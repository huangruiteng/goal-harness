from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from loopx.cli_commands import project_lifecycle
from loopx.extensions.lark.goal_channel_contracts import (
    human_gate_auto_notify_marker_path,
    write_human_gate_auto_notify_marker,
)


def _args(*, suppress_external_sinks: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        command="refresh-state",
        goal_id="goal-public-fixture",
        project=None,
        state_file=None,
        classification="validated",
        recommended_action=None,
        next_action=None,
        delivery_batch_scale=None,
        delivery_outcome=None,
        delivery_workspace_path=None,
        agent_id="agent-public-fixture",
        agent_lane=None,
        progress_scope=None,
        autonomous_replan_recorded=False,
        repair_delta_kinds=None,
        agent_vision_json=None,
        vision_state=None,
        vision_summary=None,
        vision_role_scope=None,
        vision_acceptance=None,
        vision_advancement_policy=None,
        vision_replan_trigger=None,
        vision_dreaming_policy=None,
        vision_last_patch=None,
        vision_todo_delta=None,
        vision_unchanged_reason=None,
        available_capabilities=None,
        dry_run=False,
        no_global_sync=False,
        suppress_external_sinks=suppress_external_sinks,
        runtime_root=None,
        subcommand_format="json",
        format=None,
    )


@pytest.mark.parametrize(
    ("gate_sync", "expected_exit", "expected_ok"),
    [
        (
            {
                "ok": True,
                "enabled": True,
                "status": "sent_verified",
                "delivery_postcondition": {
                    "satisfied": True,
                    "blocks_delivery": False,
                },
            },
            0,
            True,
        ),
        (
            {
                "ok": False,
                "enabled": True,
                "status": "failed",
                "delivery_postcondition": {
                    "satisfied": False,
                    "blocks_delivery": True,
                },
            },
            1,
            False,
        ),
    ],
)
def test_refresh_state_applies_goal_channel_delivery_postcondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_sync: dict[str, Any],
    expected_exit: int,
    expected_ok: bool,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        project_lifecycle,
        "refresh_state_run",
        lambda **kwargs: {
            "ok": True,
            "appended": True,
            "dry_run": False,
            "classification": "validated",
        },
    )
    monkeypatch.setattr(
        project_lifecycle,
        "sync_explore_graph_after_material_refresh",
        lambda **kwargs: {
            "enabled": False,
            "delivery_postcondition": {
                "satisfied": True,
                "blocks_delivery": False,
            },
        },
    )
    monkeypatch.setattr(
        project_lifecycle,
        "sync_human_gate_after_refresh",
        lambda **kwargs: gate_sync,
    )

    result = project_lifecycle.handle_project_lifecycle_command(
        _args(),
        registry_path=tmp_path / ".loopx" / "registry.json",
        print_payload=lambda payload, fmt, renderer: captured.update(payload),
        output_format=lambda args: "json",
        append_cli_rollout_event=lambda *args, **kwargs: {},
    )

    assert result == expected_exit
    assert captured["ok"] is expected_ok
    assert captured["goal_channel_gate_sync"] == gate_sync
    if expected_ok:
        assert "error" not in captured
    else:
        assert "human-gate notification/readback failed" in captured["error"]


def test_refresh_state_forwards_external_sink_suppression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    monkeypatch.setattr(
        project_lifecycle,
        "refresh_state_run",
        lambda **kwargs: {
            "ok": True,
            "appended": True,
            "dry_run": False,
            "classification": "validated",
        },
    )
    monkeypatch.setattr(
        project_lifecycle,
        "sync_explore_graph_after_material_refresh",
        lambda **kwargs: {
            "enabled": False,
            "delivery_postcondition": {
                "satisfied": True,
                "blocks_delivery": False,
            },
        },
    )

    def sync_gate(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return {
            "ok": True,
            "enabled": True,
            "status": "external_sink_suppressed",
            "delivery_postcondition": {
                "satisfied": True,
                "blocks_delivery": False,
            },
        }

    monkeypatch.setattr(
        project_lifecycle,
        "sync_human_gate_after_refresh",
        sync_gate,
    )

    result = project_lifecycle.handle_project_lifecycle_command(
        _args(suppress_external_sinks=True),
        registry_path=tmp_path / ".loopx" / "registry.json",
        print_payload=lambda payload, fmt, renderer: None,
        output_format=lambda args: "json",
        append_cli_rollout_event=lambda *args, **kwargs: {},
    )

    assert result == 0
    assert captured_kwargs["external_sink_delivery_authorized"] is False


@pytest.mark.parametrize(
    "constant", ["NaN", "Infinity", "-Infinity"]
)
def test_refresh_state_rejects_non_standard_usage_json_constants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
) -> None:
    """--usage-json is strict JSON: NaN/Infinity must fail before any refresh."""
    captured: dict[str, Any] = {}
    refresh_calls: list[dict[str, Any]] = []

    def _record_refresh(**kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(kwargs)
        return {"ok": True, "appended": True, "dry_run": False}

    monkeypatch.setattr(project_lifecycle, "refresh_state_run", _record_refresh)

    args = _args()
    args.usage_json = (
        '{"input_tokens": 1, "output_tokens": 1, "provider": "p", '
        '"model": "m", "source_snapshot_id": "s", "cost_usd": ' + constant + "}"
    )
    result = project_lifecycle.handle_project_lifecycle_command(
        args,
        registry_path=tmp_path / ".loopx" / "registry.json",
        print_payload=lambda payload, fmt, renderer: captured.update(payload),
        output_format=lambda args: "json",
        append_cli_rollout_event=lambda *a, **kw: {},
    )

    assert result == 1
    assert captured["ok"] is False
    assert "strict JSON" in captured["error"]
    assert refresh_calls == []


def test_refresh_state_redacts_goal_channel_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-public-fixture",
                        "repo": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    write_human_gate_auto_notify_marker(
        human_gate_auto_notify_marker_path(
            registry_path.parent / "goal-channel.json",
            "goal-public-fixture",
        )
    )
    monkeypatch.setattr(
        project_lifecycle,
        "refresh_state_run",
        lambda **kwargs: {
            "ok": True,
            "appended": True,
            "dry_run": False,
            "classification": "validated",
        },
    )
    monkeypatch.setattr(
        project_lifecycle,
        "sync_explore_graph_after_material_refresh",
        lambda **kwargs: {
            "enabled": False,
            "delivery_postcondition": {
                "satisfied": True,
                "blocks_delivery": False,
            },
        },
    )

    def fail_with_private_details(**kwargs: Any) -> dict[str, Any]:
        raise ValueError(
            f"private binding failed at {tmp_path}/.loopx/goal-channel.json "
            "for oc_private_fixture"
        )

    monkeypatch.setattr(
        project_lifecycle,
        "sync_human_gate_after_refresh",
        fail_with_private_details,
    )

    result = project_lifecycle.handle_project_lifecycle_command(
        _args(),
        registry_path=registry_path,
        print_payload=lambda payload, fmt, renderer: captured.update(payload),
        output_format=lambda args: "json",
        append_cli_rollout_event=lambda *args, **kwargs: {},
    )

    serialized = str(captured)
    assert result == 1
    assert captured["goal_channel_gate_sync"]["blocker"] == (
        "goal_channel_gate_sync_failed"
    )
    assert str(tmp_path) not in serialized
    assert "oc_private_fixture" not in serialized
