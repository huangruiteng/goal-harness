from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    build_upgrade_plan,
    compile_catalog,
    normalize_selector_request,
    project_runtime_status,
    qualify_desktop_patch,
    qualify_heartbeat_transport,
    qualify_host_control_recovery,
    qualify_quota_recovery,
    qualify_snapshot,
    qualify_tool_transport,
    reconcile_integration_candidate,
    reject_private_material,
)

EXTENSION_ID = "loopx-codex-provider-routing"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=EXTENSION_ID)
    parser.add_argument(
        "--doctor", action="store_true", help="run a side-effect-free readiness check"
    )
    return parser


def _emit(payload: Mapping[str, Any]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


def _doctor() -> int:
    _emit(
        {
            "ok": True,
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "extension_id": EXTENSION_ID,
            "doctor": "ready",
            "operations": [
                "compile_catalog",
                "normalize_selector_request",
                "project_runtime_status",
                "qualify_desktop_patch",
                "qualify_heartbeat_transport",
                "qualify_host_control_recovery",
                "qualify_quota_recovery",
                "qualify_snapshot",
                "qualify_tool_transport",
                "reconcile_integration_candidate",
                "upgrade_plan",
            ],
            "effect_boundary": "read_only_public_safe",
        }
    )
    return 0


def _run_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise TypeError("extension input must be a JSON object")
    reject_private_material(request)
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"extension input must use {REQUEST_SCHEMA_VERSION}")
    operation = request.get("operation")
    operation_fields = {
        "compile_catalog": "source",
        "normalize_selector_request": "normalization",
        "project_runtime_status": "status",
        "qualify_desktop_patch": "desktop_patch",
        "qualify_heartbeat_transport": "heartbeat_transport",
        "qualify_host_control_recovery": "host_control_recovery",
        "qualify_quota_recovery": "quota_recovery",
        "qualify_snapshot": "snapshot",
        "qualify_tool_transport": "tool_transport",
        "reconcile_integration_candidate": "integration",
        "upgrade_plan": "upgrade",
    }
    if not isinstance(operation, str):
        raise TypeError(f"operation must be a string, got {operation!r}")
    expected_field = operation_fields.get(operation)
    if expected_field is None:
        raise ValueError(f"unsupported operation: {operation!r}")
    unexpected = sorted(set(request) - {"schema_version", "operation", expected_field})
    if unexpected:
        raise ValueError(f"extension input has unsupported fields: {unexpected}")
    if operation == "compile_catalog":
        source = request.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("compile_catalog requires object `source`")
        result = compile_catalog(source)
    elif operation == "normalize_selector_request":
        normalization = request.get("normalization")
        if not isinstance(normalization, Mapping):
            raise ValueError(
                "normalize_selector_request requires object `normalization`"
            )
        result = normalize_selector_request(normalization)
    elif operation == "project_runtime_status":
        status = request.get("status")
        if not isinstance(status, Mapping):
            raise ValueError("project_runtime_status requires object `status`")
        result = project_runtime_status(status)
    elif operation == "qualify_desktop_patch":
        desktop_patch = request.get("desktop_patch")
        if not isinstance(desktop_patch, Mapping):
            raise ValueError("qualify_desktop_patch requires object `desktop_patch`")
        result = qualify_desktop_patch(desktop_patch)
    elif operation == "qualify_heartbeat_transport":
        heartbeat_transport = request.get("heartbeat_transport")
        if not isinstance(heartbeat_transport, Mapping):
            raise ValueError(
                "qualify_heartbeat_transport requires object `heartbeat_transport`"
            )
        result = qualify_heartbeat_transport(heartbeat_transport)
    elif operation == "qualify_host_control_recovery":
        host_control_recovery = request.get("host_control_recovery")
        if not isinstance(host_control_recovery, Mapping):
            raise ValueError(
                "qualify_host_control_recovery requires object `host_control_recovery`"
            )
        result = qualify_host_control_recovery(host_control_recovery)
    elif operation == "qualify_quota_recovery":
        quota_recovery = request.get("quota_recovery")
        if not isinstance(quota_recovery, Mapping):
            raise ValueError("qualify_quota_recovery requires object `quota_recovery`")
        result = qualify_quota_recovery(quota_recovery)
    elif operation == "qualify_snapshot":
        snapshot = request.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("qualify_snapshot requires object `snapshot`")
        result = qualify_snapshot(snapshot)
    elif operation == "qualify_tool_transport":
        tool_transport = request.get("tool_transport")
        if not isinstance(tool_transport, Mapping):
            raise ValueError("qualify_tool_transport requires object `tool_transport`")
        result = qualify_tool_transport(tool_transport)
    elif operation == "reconcile_integration_candidate":
        integration = request.get("integration")
        if not isinstance(integration, Mapping):
            raise ValueError(
                "reconcile_integration_candidate requires object `integration`"
            )
        result = reconcile_integration_candidate(integration)
    else:
        upgrade = request.get("upgrade")
        if not isinstance(upgrade, Mapping):
            raise ValueError("upgrade_plan requires object `upgrade`")
        result = build_upgrade_plan(upgrade)
    return {
        "ok": True,
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "extension_id": EXTENSION_ID,
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "operation": operation,
        "result": result,
    }


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.doctor:
        return _doctor()
    try:
        request = json.load(sys.stdin)
        _emit(_run_request(request))
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "extension_id": EXTENSION_ID,
                "error": str(exc),
            }
        )
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
