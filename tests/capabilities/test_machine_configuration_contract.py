from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from loopx.capabilities.machine_configuration.contract import (
    MachineConfigurationNamespace,
    MachineConfigurationRegistry,
    normalize_machine_configuration,
    project_machine_configuration,
    remove_machine_configuration_namespace,
)


def _normalize_example(value: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - {"schema_version", "enabled", "secret"})
    if unknown:
        raise ValueError("example contains unsupported fields: " + ", ".join(unknown))
    if not isinstance(value.get("enabled"), bool):
        raise TypeError("example.enabled must be a boolean")
    return dict(value)


def _registry() -> MachineConfigurationRegistry:
    return MachineConfigurationRegistry().register(
        MachineConfigurationNamespace(
            namespace="example",
            schema_versions=frozenset({"example_v0"}),
            normalize=_normalize_example,
            project_public=lambda value: {
                key: item for key, item in value.items() if key != "secret"
            },
        )
    )


def _config() -> dict[str, Any]:
    return {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {
            "example": {
                "schema_version": "example_v0",
                "enabled": True,
                "secret": "redacted",
            }
        },
    }


def test_registered_namespace_is_normalized_and_publicly_projected() -> None:
    assert normalize_machine_configuration(_config(), registry=_registry()) == _config()
    assert project_machine_configuration(_config(), registry=_registry()) == {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {"example": {"schema_version": "example_v0", "enabled": True}},
    }


def test_unknown_namespace_and_unknown_envelope_field_fail_closed() -> None:
    config = _config()
    config["namespaces"] = {"unknown": {"schema_version": "unknown_v0"}}
    with pytest.raises(ValueError, match="unsupported machine-configuration namespace"):
        normalize_machine_configuration(config, registry=_registry())

    config = _config()
    config["arbitrary"] = True
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_machine_configuration(config, registry=_registry())


def test_consumer_schema_version_and_fields_are_enforced() -> None:
    config = _config()
    config["namespaces"]["example"]["schema_version"] = "example_v1"
    with pytest.raises(ValueError, match="unsupported schema_version"):
        normalize_machine_configuration(config, registry=_registry())

    config = _config()
    config["namespaces"]["example"]["surprise"] = True
    with pytest.raises(ValueError, match="example contains unsupported fields"):
        normalize_machine_configuration(config, registry=_registry())


def test_removing_the_last_namespace_returns_document_absence() -> None:
    assert (
        remove_machine_configuration_namespace(
            _config(), namespace="example", registry=_registry()
        )
        is None
    )


def test_removing_an_unknown_namespace_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported machine-configuration namespace"):
        remove_machine_configuration_namespace(
            _config(), namespace="unknown", registry=_registry()
        )
