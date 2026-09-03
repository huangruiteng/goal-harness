from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


MACHINE_CONFIGURATION_SCHEMA = "loopx_machine_configuration_v0"
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
Normalizer = Callable[[Mapping[str, Any]], dict[str, Any]]
Projector = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class MachineConfigurationNamespace:
    """One typed owner of a machine-configuration namespace."""

    namespace: str
    schema_versions: frozenset[str]
    normalize: Normalizer
    project_public: Projector

    def __post_init__(self) -> None:
        if not _NAMESPACE_RE.fullmatch(self.namespace):
            raise ValueError("machine-configuration namespace is invalid")
        if not self.schema_versions or any(
            not str(version).strip() for version in self.schema_versions
        ):
            raise ValueError("machine-configuration schema versions are required")


class MachineConfigurationRegistry:
    """Fail-closed registry shared by CLI, Dashboard, and other effect owners."""

    def __init__(self) -> None:
        self._namespaces: dict[str, MachineConfigurationNamespace] = {}

    def register(
        self, contract: MachineConfigurationNamespace
    ) -> MachineConfigurationRegistry:
        if contract.namespace in self._namespaces:
            raise ValueError(
                "machine-configuration namespace is already registered: "
                + contract.namespace
            )
        self._namespaces[contract.namespace] = contract
        return self

    def resolve(self, namespace: str) -> MachineConfigurationNamespace:
        try:
            return self._namespaces[namespace]
        except KeyError as exc:
            raise ValueError(
                f"unsupported machine-configuration namespace: {namespace}"
            ) from exc

    @property
    def namespace_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._namespaces))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def normalize_machine_configuration(
    raw: object, *, registry: MachineConfigurationRegistry
) -> dict[str, Any]:
    payload = _mapping(raw, "machine_configuration")
    unknown = sorted(set(payload) - {"schema_version", "namespaces"})
    if unknown:
        raise ValueError(
            "machine_configuration contains unsupported fields: " + ", ".join(unknown)
        )
    if payload.get("schema_version") != MACHINE_CONFIGURATION_SCHEMA:
        raise ValueError(
            f"machine_configuration must use {MACHINE_CONFIGURATION_SCHEMA}"
        )
    namespaces = _mapping(payload.get("namespaces"), "machine_configuration.namespaces")
    if not namespaces:
        raise ValueError("machine_configuration.namespaces must not be empty")
    normalized: dict[str, Any] = {}
    for namespace in sorted(namespaces):
        contract = registry.resolve(namespace)
        candidate = _mapping(
            namespaces[namespace], f"machine_configuration.namespaces.{namespace}"
        )
        schema_version = str(candidate.get("schema_version") or "").strip()
        if schema_version not in contract.schema_versions:
            raise ValueError(
                f"machine_configuration namespace {namespace} has unsupported "
                f"schema_version: {schema_version or 'missing'}"
            )
        value = contract.normalize(candidate)
        if value.get("schema_version") != schema_version:
            raise ValueError(
                f"machine-configuration normalizer changed {namespace} schema_version"
            )
        normalized[namespace] = value
    return {
        "schema_version": MACHINE_CONFIGURATION_SCHEMA,
        "namespaces": normalized,
    }


def machine_configuration_revision(configuration: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        configuration, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def project_machine_configuration(
    configuration: object, *, registry: MachineConfigurationRegistry
) -> dict[str, Any]:
    normalized = normalize_machine_configuration(configuration, registry=registry)
    projected: dict[str, Any] = {}
    for namespace, value in normalized["namespaces"].items():
        contract = registry.resolve(namespace)
        public_value = contract.project_public(value)
        if public_value.get("schema_version") != value.get("schema_version"):
            raise ValueError(
                f"machine-configuration public projection changed {namespace} schema_version"
            )
        projected[namespace] = public_value
    return {
        "schema_version": MACHINE_CONFIGURATION_SCHEMA,
        "namespaces": projected,
    }


def remove_machine_configuration_namespace(
    current: Mapping[str, Any] | None,
    *,
    namespace: str,
    registry: MachineConfigurationRegistry,
) -> dict[str, Any] | None:
    """Remove one typed namespace, returning absence for an empty document."""

    registry.resolve(namespace)
    if current is None:
        return None
    normalized = normalize_machine_configuration(current, registry=registry)
    namespaces = dict(normalized["namespaces"])
    namespaces.pop(namespace, None)
    if not namespaces:
        return None
    return normalize_machine_configuration(
        {
            "schema_version": MACHINE_CONFIGURATION_SCHEMA,
            "namespaces": namespaces,
        },
        registry=registry,
    )


__all__ = [
    "MACHINE_CONFIGURATION_SCHEMA",
    "MachineConfigurationNamespace",
    "MachineConfigurationRegistry",
    "machine_configuration_revision",
    "normalize_machine_configuration",
    "project_machine_configuration",
    "remove_machine_configuration_namespace",
]
