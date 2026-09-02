from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loopx.capabilities.machine_configuration.contract import (
    MachineConfigurationNamespace,
    MachineConfigurationRegistry,
)
from loopx.chat_machine_configuration_api import (
    CHAT_MACHINE_CONFIGURATION_APPLY_PATH,
    CHAT_MACHINE_CONFIGURATION_PATH,
    CHAT_MACHINE_CONFIGURATION_PREVIEW_PATH,
    CHAT_MACHINE_CONFIGURATION_ROLLBACK_PATH,
    MachineConfigurationRequestMixin,
)


def _configuration(*, enabled: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {
            "periodic_report": {
                "schema_version": "periodic_report_machine_defaults_v0",
                "enabled": enabled,
                "inheritance": "materialize_on_goal_connect",
                "profile_preset": "weekly-progress",
                "route_ref": "loopx-manager",
                "timezone": "Asia/Shanghai",
            }
        },
    }


def _namespace(*, enabled: bool = True) -> dict[str, Any]:
    return _configuration(enabled=enabled)["namespaces"]["periodic_report"]


class _Handler(MachineConfigurationRequestMixin):
    def __init__(self, runtime_root: Path, body: dict[str, Any] | None = None) -> None:
        self.server = SimpleNamespace(runtime_root=runtime_root)
        self.body = body or {}
        self.responses: list[dict[str, Any]] = []

    def _read_json(self) -> dict[str, Any]:
        return self.body

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.responses.append({"status_code": status, **payload})

    def _send_error(
        self,
        message: str,
        *,
        status: int,
        error_code: str,
        **_kwargs: Any,
    ) -> None:
        self.responses.append(
            {
                "ok": False,
                "status_code": status,
                "error": message,
                "error_code": error_code,
            }
        )


class _MultiNamespaceHandler(_Handler):
    def _machine_configuration_registry(self) -> MachineConfigurationRegistry:
        registry = super()._machine_configuration_registry()
        return registry.register(
            MachineConfigurationNamespace(
                namespace="search_defaults",
                schema_versions=frozenset({"search_defaults_v0"}),
                normalize=lambda value: dict(value),
                project_public=lambda value: dict(value),
            )
        )


def test_machine_configuration_uses_generic_chat_routes() -> None:
    assert CHAT_MACHINE_CONFIGURATION_PATH == "/api/chat/machine-configuration"
    assert CHAT_MACHINE_CONFIGURATION_PREVIEW_PATH.endswith("/preview")
    assert CHAT_MACHINE_CONFIGURATION_APPLY_PATH.endswith("/apply")
    assert CHAT_MACHINE_CONFIGURATION_ROLLBACK_PATH.endswith("/rollback")


def test_inspection_lists_registered_namespaces_without_local_refs(
    tmp_path: Path,
) -> None:
    handler = _Handler(tmp_path)

    handler._machine_configuration_inspect()

    response = handler.responses[0]
    assert response["status"] == "absent"
    assert response["available_namespaces"] == ["periodic_report"]
    assert response["machine_configuration"] is None
    encoded = json.dumps(response)
    assert str(tmp_path) not in encoded
    assert "defaults_ref" not in response


def test_preview_apply_inspect_and_rollback_are_revision_locked(tmp_path: Path) -> None:
    configuration = _configuration()
    preview_handler = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
        },
    )
    preview_handler._machine_configuration_update(execute=False)
    preview = preview_handler.responses[0]
    assert preview["status"] == "preview"
    assert preview["action"] == "create"
    assert preview["changed_namespaces"] == ["periodic_report"]

    apply_handler = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
            "expected_plan_revision": preview["plan_revision"],
        },
    )
    apply_handler._machine_configuration_update(execute=True)
    receipt = apply_handler.responses[0]
    assert receipt["status"] == "applied"
    assert receipt["readback_verified"] is True
    assert receipt["rollback_available"] is True
    assert "transaction_ref" not in receipt
    assert "backup_ref" not in receipt

    inspect_handler = _Handler(tmp_path)
    inspect_handler._machine_configuration_inspect()
    inspection = inspect_handler.responses[0]
    assert inspection["status"] == "configured"
    assert inspection["machine_configuration"] == configuration

    rollback_preview_handler = _Handler(
        tmp_path,
        {"transaction_id": receipt["transaction_id"], "execute": False},
    )
    rollback_preview_handler._machine_configuration_rollback()
    rollback_preview = rollback_preview_handler.responses[0]
    assert rollback_preview["rollback_allowed"] is True
    assert rollback_preview["action"] == "delete"

    rollback_handler = _Handler(
        tmp_path,
        {
            "transaction_id": receipt["transaction_id"],
            "execute": True,
            "expected_plan_revision": rollback_preview["plan_revision"],
        },
    )
    rollback_handler._machine_configuration_rollback()
    rollback = rollback_handler.responses[0]
    assert rollback["status"] == "rolled_back"
    assert rollback["readback_verified"] is True
    assert "rollback_ref" not in rollback

    final_handler = _Handler(tmp_path)
    final_handler._machine_configuration_inspect()
    assert final_handler.responses[0]["status"] == "absent"


def test_apply_rejects_a_stale_preview_without_writing(tmp_path: Path) -> None:
    first = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
        },
    )
    first._machine_configuration_update(execute=False)

    stale = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(enabled=False),
            "expected_plan_revision": first.responses[0]["plan_revision"],
        },
    )
    stale._machine_configuration_update(execute=True)

    assert stale.responses[0]["status_code"] == 409
    assert stale.responses[0]["error_code"] == "machine_configuration_preview_stale"


def test_namespace_patch_preserves_other_capability_namespaces(tmp_path: Path) -> None:
    first_preview_handler = _MultiNamespaceHandler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
        },
    )
    first_preview_handler._machine_configuration_update(execute=False)
    first_apply_handler = _MultiNamespaceHandler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
            "expected_plan_revision": first_preview_handler.responses[0][
                "plan_revision"
            ],
        },
    )
    first_apply_handler._machine_configuration_update(execute=True)

    second_preview_handler = _MultiNamespaceHandler(
        tmp_path,
        {
            "namespace": "search_defaults",
            "namespace_configuration": {
                "schema_version": "search_defaults_v0",
                "index": "public",
            },
        },
    )
    second_preview_handler._machine_configuration_update(execute=False)

    namespaces = second_preview_handler.responses[0]["machine_configuration"][
        "namespaces"
    ]
    assert namespaces["periodic_report"] == _namespace()
    assert namespaces["search_defaults"] == {
        "schema_version": "search_defaults_v0",
        "index": "public",
    }
