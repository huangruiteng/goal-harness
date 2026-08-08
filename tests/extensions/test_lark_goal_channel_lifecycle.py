from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.extensions.lark import goal_channel_lifecycle
from loopx.extensions.lark.goal_channel_contracts import (
    GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
    read_goal_channel_binding,
    write_goal_channel_binding,
)


GOAL_ID = "goal-public-fixture"


def _registry(tmp_path: Path) -> Path:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "objective": "Deliver a public-safe collaboration channel.",
                        "repo": str(tmp_path),
                        "state_file": str(tmp_path / "ACTIVE_GOAL_STATE.md"),
                        "adapter": {"kind": "read_only_project_map_v0"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry_path


def _binding(registry_path: Path, *, enabled: bool) -> None:
    write_goal_channel_binding(
        registry_path.parent / "goal-channel.json",
        {
            "schema_version": GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
            "bindings": {
                GOAL_ID: {
                    "goal_id": GOAL_ID,
                    "provider": "lark",
                    "enabled": True,
                    "automation": {
                        "human_gate_auto_notify_enabled": enabled,
                    },
                    "receipts": {},
                }
            },
        },
    )


def test_refresh_lifecycle_does_not_load_extension_without_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    called = False

    def unexpected(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        raise AssertionError("extension activation must remain lazy")

    monkeypatch.setattr(
        goal_channel_lifecycle,
        "resolve_extension_activation",
        unexpected,
    )

    result = goal_channel_lifecycle.sync_human_gate_after_refresh(
        registry_path=registry_path,
        runtime_root_override=None,
        goal_id=GOAL_ID,
        agent_id=None,
        external_sink_delivery_authorized=True,
    )

    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["status"] == "not_configured"
    assert called is False


def test_refresh_lifecycle_shared_registry_without_source_binding_is_safe_noop(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "runtime" / "registry.global.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "registry_role": "global-local",
                "common_runtime_root": str(registry_path.parent),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "objective": "Deliver a public-safe collaboration channel.",
                        "repo": str(tmp_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = goal_channel_lifecycle.sync_human_gate_after_refresh(
        registry_path=registry_path,
        runtime_root_override=None,
        goal_id=GOAL_ID,
        agent_id=None,
        external_sink_delivery_authorized=True,
    )

    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["status"] == "project_binding_unavailable"


def test_refresh_lifecycle_suppression_skips_extension_and_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    _binding(registry_path, enabled=True)

    def unexpected(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("suppressed delivery must not load external dependencies")

    monkeypatch.setattr(
        goal_channel_lifecycle,
        "resolve_extension_activation",
        unexpected,
    )
    monkeypatch.setattr(goal_channel_lifecycle, "collect_status", unexpected)

    result = goal_channel_lifecycle.sync_human_gate_after_refresh(
        registry_path=registry_path,
        runtime_root_override=None,
        goal_id=GOAL_ID,
        agent_id="agent-public-fixture",
        external_sink_delivery_authorized=False,
    )

    assert result["ok"] is True
    assert result["enabled"] is True
    assert result["status"] == "external_sink_suppressed"


def test_refresh_lifecycle_no_gate_does_not_load_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    _binding(registry_path, enabled=True)
    monkeypatch.setattr(
        goal_channel_lifecycle,
        "collect_status",
        lambda **kwargs: {"status": "fixture"},
    )
    monkeypatch.setattr(
        goal_channel_lifecycle,
        "build_quota_should_run",
        lambda status, **kwargs: {"state": "eligible"},
    )

    def unexpected(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("no selected gate must not load the Lark extension")

    monkeypatch.setattr(
        goal_channel_lifecycle,
        "resolve_extension_activation",
        unexpected,
    )

    result = goal_channel_lifecycle.sync_human_gate_after_refresh(
        registry_path=registry_path,
        runtime_root_override=None,
        goal_id=GOAL_ID,
        agent_id=None,
        external_sink_delivery_authorized=True,
    )

    assert result["ok"] is True
    assert result["enabled"] is True
    assert result["status"] == "not_selected"
    assert "extension_activation" not in result


def test_refresh_lifecycle_reads_quota_then_delivers_selected_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    _binding(registry_path, enabled=True)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        goal_channel_lifecycle,
        "resolve_extension_activation",
        lambda *args, **kwargs: {"status": "active"},
    )
    monkeypatch.setattr(
        goal_channel_lifecycle,
        "collect_status",
        lambda **kwargs: {"status": "fixture"},
    )
    monkeypatch.setattr(
        goal_channel_lifecycle,
        "build_quota_should_run",
        lambda status, **kwargs: {
            "state": "operator_gate",
            "notify_user_on_gate": True,
            "gate_prompt": "Approve the bounded external write.",
        },
    )

    def deliver(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
            "ok": True,
            "enabled": True,
            "status": "sent_verified",
            "external_write_performed": True,
            "readback_verified": True,
            "delivery_postcondition": {
                "satisfied": True,
                "blocks_delivery": False,
            },
        }

    monkeypatch.setattr(
        goal_channel_lifecycle,
        "auto_notify_lark_goal_channel_gate",
        deliver,
    )

    result = goal_channel_lifecycle.sync_human_gate_after_refresh(
        registry_path=registry_path,
        runtime_root_override=None,
        goal_id=GOAL_ID,
        agent_id="agent-public-fixture",
        external_sink_delivery_authorized=True,
    )

    assert result["status"] == "sent_verified"
    assert result["extension_activation"] == {"status": "active"}
    assert captured["quota_packet"]["state"] == "operator_gate"
    assert captured["external_sink_delivery_authorized"] is True
    assert (
        read_goal_channel_binding(registry_path.parent / "goal-channel.json")[
            "bindings"
        ][GOAL_ID]["automation"]["human_gate_auto_notify_enabled"]
        is True
    )
