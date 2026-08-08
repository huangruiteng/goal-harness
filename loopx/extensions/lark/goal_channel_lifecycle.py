from __future__ import annotations

from pathlib import Path
from typing import Any

from ...control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)
from ...history import load_registry
from ...paths import registry_project_root
from ...quota import build_quota_should_run
from ...status import collect_status
from ..runtime import default_extension_state_file, resolve_extension_activation
from . import LARK_EXTENSION_ID, LARK_GOAL_CHANNEL_PERMISSION
from .goal_channel_contracts import (
    binding_for_goal,
    default_goal_channel_binding_path,
    human_gate_auto_notify_enabled,
    human_gate_auto_notify_marker_enabled,
    human_gate_auto_notify_marker_path,
    read_goal_channel_binding,
)
from .goal_channel_runtime import auto_notify_lark_goal_channel_gate
from .goal_channel_targets import (
    default_goal_channel_target_path,
    goal_channel_target_for_name,
    read_goal_channel_targets,
)
from .presentation.kanban import (
    CommandRunner,
    default_subprocess_runner,
)


def _inactive_result(status: str) -> dict[str, Any]:
    return {
        "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
        "ok": True,
        "enabled": False,
        "status": status,
        "external_write_performed": False,
        "readback_verified": False,
        "delivery_postcondition": {
            "satisfied": True,
            "blocks_delivery": False,
        },
    }


def _extension_unavailable_result(*, configured: bool) -> dict[str, Any]:
    if configured:
        return {
            "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
            "ok": False,
            "enabled": True,
            "status": "extension_unavailable",
            "external_write_performed": False,
            "readback_verified": False,
            "blocker": "extension_unavailable",
            "delivery_postcondition": {
                "satisfied": False,
                "blocks_delivery": True,
            },
        }
    return {
        **_inactive_result("extension_unavailable"),
        "enabled": False,
    }


def goal_channel_gate_sync_failure(
    *,
    registry_path: Path,
    goal_id: str,
    status: str = "failed",
    blocker: str = "goal_channel_gate_sync_failed",
) -> dict[str, Any]:
    configured = False
    try:
        invoked_registry = load_registry(registry_path)
        source_route = resolve_goal_source_runtime_route(
            registry_path=registry_path,
            goal_id=goal_id,
            registry=invoked_registry,
        )
        source_registry_path = Path(str(source_route["source_registry"]))
        if source_registry_path.parent.name == ".loopx":
            binding_path = default_goal_channel_binding_path(source_registry_path)
            configured = human_gate_auto_notify_marker_enabled(
                human_gate_auto_notify_marker_path(binding_path, goal_id)
            )
    except (OSError, ValueError):
        configured = False
    return {
        "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
        "ok": not configured,
        "enabled": configured,
        "status": status if configured else "not_configured",
        "external_write_performed": False,
        "readback_verified": False,
        **({"blocker": blocker} if configured else {}),
        "delivery_postcondition": {
            "satisfied": not configured,
            "blocks_delivery": configured,
        },
    }


def sync_human_gate_after_refresh(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    goal_id: str,
    agent_id: str | None,
    external_sink_delivery_authorized: bool,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    invoked_registry = load_registry(registry_path)
    source_route = resolve_goal_source_runtime_route(
        registry_path=registry_path,
        goal_id=goal_id,
        registry=invoked_registry,
    )
    source_registry_path = Path(str(source_route["source_registry"]))
    source_registry = (
        invoked_registry
        if source_registry_path.expanduser().resolve()
        == registry_path.expanduser().resolve()
        else load_registry(source_registry_path)
    )
    if source_registry_path.parent.name != ".loopx":
        return _inactive_result("project_binding_unavailable")
    runtime_root = (
        Path(runtime_root_override).expanduser().resolve()
        if runtime_root_override
        else Path(str(source_route["source_runtime_root"]))
    )
    binding_path = default_goal_channel_binding_path(source_registry_path)
    marker_path = human_gate_auto_notify_marker_path(binding_path, goal_id)
    try:
        activation = resolve_extension_activation(
            LARK_EXTENSION_ID,
            state_file=default_extension_state_file(runtime_root),
            required_permissions=(LARK_GOAL_CHANNEL_PERMISSION,),
        )
    except (OSError, ValueError):
        return _extension_unavailable_result(
            configured=human_gate_auto_notify_marker_enabled(marker_path)
        )
    try:
        binding_payload = read_goal_channel_binding(binding_path)
        raw_binding = binding_for_goal(binding_payload, goal_id)
        target_name = str((raw_binding or {}).get("target_ref") or "")
        provider_target = (
            goal_channel_target_for_name(
                read_goal_channel_targets(
                    default_goal_channel_target_path(runtime_root)
                ),
                target_name,
            )
            if target_name
            else None
        )
    except (OSError, ValueError):
        return goal_channel_gate_sync_failure(
            registry_path=registry_path,
            goal_id=goal_id,
            blocker="invalid_goal_channel_binding",
        )
    if target_name and provider_target is None:
        return {
            "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
            "ok": False,
            "enabled": True,
            "status": "provider_target_missing",
            "external_write_performed": False,
            "readback_verified": False,
            "blocker": "provider_target_missing",
            "delivery_postcondition": {
                "satisfied": False,
                "blocks_delivery": True,
            },
        }
    binding = binding_for_goal(
        binding_payload,
        goal_id,
        provider_target=provider_target,
    )
    quota_packet: dict[str, Any] = {}
    if (
        human_gate_auto_notify_enabled(binding)
        and external_sink_delivery_authorized
    ):
        status = collect_status(
            registry_path=source_registry_path,
            runtime_root_override=str(runtime_root),
            scan_roots=[registry_project_root(source_registry_path)],
            limit=20,
            goal_id=goal_id,
        )
        quota_packet = build_quota_should_run(
            status,
            goal_id=goal_id,
            agent_id=agent_id,
        )

    result = auto_notify_lark_goal_channel_gate(
        registry=source_registry,
        goal_id=goal_id,
        binding_path=binding_path,
        quota_packet=quota_packet,
        provider_target=provider_target,
        external_sink_delivery_authorized=external_sink_delivery_authorized,
        runner=runner,
    )
    if quota_packet:
        result["extension_activation"] = activation
    return result
