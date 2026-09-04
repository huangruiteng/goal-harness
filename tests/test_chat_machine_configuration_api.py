from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loopx.capabilities.machine_configuration.contract import (
    MachineConfigurationNamespace,
    MachineConfigurationRegistry,
)
from loopx.capabilities.machine_configuration.store import (
    configure_machine_configuration,
    read_machine_configuration,
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
                "inheritance": "live_machine_default",
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
                apply_public_update=lambda _current, update: dict(update),
            )
        )


def _normalize_private_namespace(value: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - {"schema_version", "enabled", "secret"})
    if unknown:
        raise ValueError("private namespace contains unsupported fields")
    if not isinstance(value.get("enabled"), bool):
        raise TypeError("private namespace enabled must be a boolean")
    return dict(value)


def _apply_private_namespace_public_update(
    current: Mapping[str, Any] | None,
    update: Mapping[str, Any],
) -> dict[str, Any]:
    unknown = sorted(set(update) - {"schema_version", "enabled"})
    if unknown:
        raise ValueError("private namespace public update contains unsupported fields")
    return {**dict(current or {}), **dict(update)}


class _PrivateNamespaceHandler(_Handler):
    def _machine_configuration_registry(self) -> MachineConfigurationRegistry:
        return MachineConfigurationRegistry().register(
            MachineConfigurationNamespace(
                namespace="private_defaults",
                schema_versions=frozenset({"private_defaults_v0"}),
                normalize=_normalize_private_namespace,
                project_public=lambda value: {
                    key: item for key, item in value.items() if key != "secret"
                },
                apply_public_update=_apply_private_namespace_public_update,
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
    assert response["namespace_catalog"] == {
        "schema_version": "machine_configuration_catalog_v0",
        "namespaces": [
            {
                "namespace": "periodic_report",
                "title": "Periodic reports",
                "description": (
                    "Live default for Goals without an explicit periodic-report "
                    "override. Goal overrides remain fixed; changing or removing "
                    "this policy updates inherited behavior on the next plan."
                ),
                "schema_versions": ["periodic_report_machine_defaults_v0"],
                "configuration_template": {
                    "schema_version": "periodic_report_machine_defaults_v0",
                    "enabled": False,
                    "inheritance": "live_machine_default",
                    "timezone": "UTC",
                },
                "template_status": "ready",
            }
        ],
    }
    capability_catalog = response["capability_catalog"]
    assert capability_catalog["schema_version"] == "capability_configuration_catalog_v0"
    capability = capability_catalog["capabilities"][0]
    assert capability["capability_id"] == "periodic_report"
    assert capability["available_scopes"] == ["machine"]
    assert capability["machine_namespace"] == "periodic_report"
    assert capability["default"] == response["namespace_catalog"]["namespaces"][0][
        "configuration_template"
    ]
    assert capability["configuration_editor"]["supported_scopes"] == [
        "machine",
        "goal",
    ]
    assert [field["key"] for field in capability["configuration_editor"]["fields"]] == [
        "enabled",
        "profile_preset",
        "route_ref",
        "timezone",
    ]
    effective = capability["effective_configuration"]
    assert effective["source"] == "capability_default"
    assert effective["configuration"] == capability["default"]
    assert effective["goal_override_present"] is False
    assert effective["machine_default_present"] is False
    assert str(effective["effective_revision"]).startswith("sha256:")
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


def test_namespace_removal_uses_the_same_preview_and_revision_fence(
    tmp_path: Path,
) -> None:
    create_preview = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
        },
    )
    create_preview._machine_configuration_update(execute=False)
    create = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "namespace_configuration": _namespace(),
            "expected_plan_revision": create_preview.responses[0]["plan_revision"],
        },
    )
    create._machine_configuration_update(execute=True)

    remove_preview = _Handler(
        tmp_path,
        {"namespace": "periodic_report", "operation": "remove"},
    )
    remove_preview._machine_configuration_update(execute=False)
    preview = remove_preview.responses[0]
    assert preview["action"] == "delete"
    assert preview["machine_configuration"] is None

    remove = _Handler(
        tmp_path,
        {
            "namespace": "periodic_report",
            "operation": "remove",
            "expected_plan_revision": preview["plan_revision"],
        },
    )
    remove._machine_configuration_update(execute=True)
    assert remove.responses[0]["status"] == "applied"
    assert remove.responses[0]["machine_configuration"] is None

    inspection = _Handler(tmp_path)
    inspection._machine_configuration_inspect()
    assert inspection.responses[0]["status"] == "absent"


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


def test_public_api_update_preserves_provider_private_namespace_state(
    tmp_path: Path,
) -> None:
    registry = _PrivateNamespaceHandler(tmp_path)._machine_configuration_registry()
    initial = {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {
            "private_defaults": {
                "schema_version": "private_defaults_v0",
                "enabled": False,
                "secret": "keep-me",
            }
        },
    }
    seed_plan = configure_machine_configuration(
        runtime_root=tmp_path,
        configuration=initial,
        registry=registry,
    )
    configure_machine_configuration(
        runtime_root=tmp_path,
        configuration=initial,
        registry=registry,
        execute=True,
        expected_plan_revision=seed_plan["plan_revision"],
    )

    preview_handler = _PrivateNamespaceHandler(
        tmp_path,
        {
            "namespace": "private_defaults",
            "namespace_configuration": {
                "schema_version": "private_defaults_v0",
                "enabled": True,
            },
        },
    )
    preview_handler._machine_configuration_update(execute=False)
    preview = preview_handler.responses[0]
    assert preview["machine_configuration"]["namespaces"]["private_defaults"] == {
        "schema_version": "private_defaults_v0",
        "enabled": True,
    }

    apply_handler = _PrivateNamespaceHandler(
        tmp_path,
        {
            "namespace": "private_defaults",
            "namespace_configuration": {
                "schema_version": "private_defaults_v0",
                "enabled": True,
            },
            "expected_plan_revision": preview["plan_revision"],
        },
    )
    apply_handler._machine_configuration_update(execute=True)

    persisted = read_machine_configuration(tmp_path, registry=registry)
    assert persisted is not None
    assert persisted["namespaces"]["private_defaults"] == {
        "schema_version": "private_defaults_v0",
        "enabled": True,
        "secret": "keep-me",
    }
