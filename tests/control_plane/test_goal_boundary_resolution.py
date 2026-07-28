from __future__ import annotations

from loopx.boundary_authority import build_checkpointed_boundary_authority_entry
from loopx.control_plane.quota.goal_boundary import (
    declared_available_capabilities,
    goal_boundary,
)


def test_goal_boundary_uses_registry_goal_for_scope_and_capability_projection() -> None:
    boundary = goal_boundary(
        {
            "adapter_kind": "project",
            "adapter_status": "connected",
            "available_capabilities": ["registry-root"],
            "coordination": {
                "write_scope": ["docs/**"],
                "available_capabilities": ["registry-coordination"],
                "requires_parent_approval": ["write", "", "publish"],
            },
            "project_asset": {
                "available_capabilities": ["registry-project-asset"],
            },
            "guards": ["stay public", ""],
        },
        item={
            "available_capabilities": ["item-root"],
            "coordination": {
                "write_scope": ["private-item/**"],
                "available_capabilities": ["item-coordination"],
            },
            "project_asset": {
                "available_capabilities": ["item-project-asset"],
            },
        },
    )

    assert boundary is not None
    assert boundary["adapter"] == {
        "kind": "project",
        "status": "connected",
    }
    assert boundary["write_scope"] == ["docs/**"]
    assert boundary["available_capabilities"] == [
        "registry_root",
        "registry_coordination",
        "registry_project_asset",
    ]
    assert boundary["requires_parent_approval"] == ["write", "publish"]
    assert boundary["guards"] == ["stay public"]


def test_goal_boundary_appends_only_active_checkpointed_write_scopes() -> None:
    active = build_checkpointed_boundary_authority_entry(
        write_scopes=["tests/**", "loopx/**"],
        source="operator_gate_resume_contract_v0:active",
        recorded_at="2026-07-01T00:00:00+00:00",
    )
    expired = build_checkpointed_boundary_authority_entry(
        write_scopes=["runners/**"],
        source="operator_gate_resume_contract_v0:expired",
        recorded_at="2026-07-01T00:00:00+00:00",
        expires_at="2000-01-01T00:00:00+00:00",
    )

    boundary = goal_boundary(
        {
            "coordination": {
                "write_scope": ["docs/**", "tests/**", "docs/**"],
                "checkpointed_boundary_authority": [active, expired],
            }
        }
    )

    assert boundary is not None
    assert boundary["write_scope"] == ["docs/**", "tests/**", "loopx/**"]
    authority = boundary["checkpointed_boundary_authority"]
    assert authority["active_count"] == 1
    assert authority["inactive_count"] == 1
    assert authority["active_write_scope"] == ["tests/**", "loopx/**"]


def test_declared_available_capabilities_preserves_layer_order_and_deduplicates() -> None:
    assert declared_available_capabilities(
        {
            "available_capabilities": ["root", "shared"],
            "coordination": {
                "available_capabilities": ["coordination", "shared"],
            },
            "project_asset": {
                "available_capabilities": ["project-asset", "root"],
            },
        }
    ) == [
        "root",
        "shared",
        "coordination",
        "project_asset",
    ]
