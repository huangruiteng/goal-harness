from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..capabilities.documentation import normalize_documentation_contract

EXTENSION_MANIFEST_SCHEMA_VERSION = "loopx_extension_manifest_v0"
EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION = (
    "loopx_external_domain_capability_profile_v0"
)
LOOPX_EXTENSION_API_VERSION = 1
MAX_EXTENSION_ID_LENGTH = 48
MAX_INTEGRATION_PROFILE_BYTES = 64 * 1024
_API_CLAUSE = re.compile(r"^(>=|<=|==|>|<)?\s*(\d+)$")
_EXTENSION_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_PROTOCOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}_v\d+$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PYTHON_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_EXTERNAL_CAPABILITY_EFFECT_CLASS = "read_only"
_PYTHON_CALLABLE_RE = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$"
)
_SURFACE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SURFACE_KIND_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_PRESENTATION_SURFACE_KEYS = {
    "id",
    "kind",
    "title",
    "view_schema",
    "view_validator",
    "visibility",
    "empty_state_title",
    "empty_state_detail",
}
_PRESENTATION_SURFACE_VISIBILITIES = {"public-safe", "owner-only"}
_UNSAFE_PRESENTATION_TEXT_RE = re.compile(
    r"(?:https?://|www\.|<[^>]*>|(?:^|\s)(?:~?/|[A-Za-z]:[\\/]))",
    re.IGNORECASE,
)


def validate_extension_id(value: str) -> str:
    extension_id = value.strip()
    if (
        not extension_id
        or len(extension_id) > MAX_EXTENSION_ID_LENGTH
        or _EXTENSION_ID_RE.fullmatch(extension_id) is None
    ):
        raise ValueError(
            "extension id must be a lower-kebab path segment up to 48 characters"
        )
    return extension_id


def _required_string(record: Mapping[str, Any], key: str, *, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty string `{key}`")
    return value.strip()


def _string_list(record: Mapping[str, Any], key: str, *, context: str) -> list[str]:
    value = record.get(key, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{context} requires `{key}` to be an array of strings")
    return [item.strip() for item in value]


def _documentation_contract(
    raw: Mapping[str, Any],
    *,
    context: str,
) -> dict[str, Any] | None:
    value = raw.get("documentation")
    if value is None:
        return None
    return normalize_documentation_contract(value, context=context)


def _presentation_text(
    record: Mapping[str, Any],
    key: str,
    *,
    context: str,
    max_length: int,
) -> str:
    value = _required_string(record, key, context=context)
    if len(value) > max_length:
        raise ValueError(
            f"{context} requires `{key}` to contain at most {max_length} characters"
        )
    if "\n" in value or "\r" in value or _UNSAFE_PRESENTATION_TEXT_RE.search(value):
        raise ValueError(f"{context} requires `{key}` to be bounded plain text")
    return value


def _presentation_surfaces(
    raw: Mapping[str, Any],
    *,
    runtime: Mapping[str, Any] | None,
    context: str,
) -> list[dict[str, Any]]:
    value = raw.get("presentation_surfaces", [])
    if not isinstance(value, list):
        raise ValueError(
            f"{context} requires `presentation_surfaces` to contain TOML tables"
        )
    if value and runtime is None:
        raise ValueError(
            f"{context} presentation surfaces require an executable runtime"
        )

    surfaces: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        item_context = f"{context} presentation_surfaces[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_context} must be a TOML table")
        unsupported = sorted(set(item) - _PRESENTATION_SURFACE_KEYS)
        if unsupported:
            raise ValueError(
                f"{item_context} contains unsupported keys {unsupported}"
            )
        surface_id = _required_string(item, "id", context=item_context)
        if not _SURFACE_ID_RE.fullmatch(surface_id):
            raise ValueError(
                f"{item_context} id must be a bounded lower-kebab token"
            )
        if surface_id in seen_ids:
            raise ValueError(
                f"{context} has duplicate presentation surface id `{surface_id}`"
            )
        seen_ids.add(surface_id)

        kind = _required_string(item, "kind", context=item_context)
        if not _SURFACE_KIND_RE.fullmatch(kind):
            raise ValueError(
                f"{item_context} kind must be a bounded lower_snake token"
            )
        view_schema = _required_string(item, "view_schema", context=item_context)
        if not _PROTOCOL_RE.fullmatch(view_schema):
            raise ValueError(
                f"{item_context} view_schema must be a `<name>_v<n>` token"
            )
        view_validator = _required_string(
            item,
            "view_validator",
            context=item_context,
        )
        if not _PYTHON_CALLABLE_RE.fullmatch(view_validator):
            raise ValueError(
                f"{item_context} view_validator must be a "
                "`<python.module>:<callable>` reference"
            )
        visibility = _required_string(item, "visibility", context=item_context)
        if visibility not in _PRESENTATION_SURFACE_VISIBILITIES:
            raise ValueError(
                f"{item_context} visibility must be public-safe or owner-only"
            )
        surfaces.append(
            {
                "id": surface_id,
                "kind": kind,
                "title": _presentation_text(
                    item,
                    "title",
                    context=item_context,
                    max_length=80,
                ),
                "view_schema": view_schema,
                "view_validator": view_validator,
                "visibility": visibility,
                "empty_state_title": _presentation_text(
                    item,
                    "empty_state_title",
                    context=item_context,
                    max_length=120,
                ),
                "empty_state_detail": _presentation_text(
                    item,
                    "empty_state_detail",
                    context=item_context,
                    max_length=240,
                ),
            }
        )
    return surfaces


def _runtime_contract(
    raw: Mapping[str, Any],
    *,
    permissions: list[str],
    context: str,
) -> dict[str, Any] | None:
    value = raw.get("runtime")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} requires `runtime` to be a TOML table")
    runtime_context = f"{context} runtime"
    protocol = _required_string(value, "protocol", context=runtime_context)
    if not _PROTOCOL_RE.fullmatch(protocol):
        raise ValueError(
            f"{runtime_context} protocol must be a versioned lower-snake token"
        )
    entrypoint_raw = value.get("entrypoint")
    python_module_raw = value.get("python_module")
    if (entrypoint_raw is None) == (python_module_raw is None):
        raise ValueError(
            f"{runtime_context} requires exactly one of `entrypoint` or `python_module`"
        )
    entrypoint: str | None = None
    python_module: str | None = None
    if entrypoint_raw is not None:
        entrypoint = _required_string(value, "entrypoint", context=runtime_context)
        if "\x00" in entrypoint:
            raise ValueError(f"{runtime_context} entrypoint contains an invalid byte")
    else:
        python_module = _required_string(
            value,
            "python_module",
            context=runtime_context,
        )
        if not _PYTHON_MODULE_RE.fullmatch(python_module):
            raise ValueError(
                f"{runtime_context} python_module must be a dotted Python module name"
            )
    args = _string_list(value, "args", context=runtime_context)
    doctor_args = _string_list(value, "doctor_args", context=runtime_context)
    required_permissions = _string_list(
        value,
        "required_permissions",
        context=runtime_context,
    )
    undeclared = sorted(set(required_permissions) - set(permissions))
    if undeclared:
        raise ValueError(
            f"{runtime_context} requires undeclared permissions {undeclared}"
        )
    timeout_seconds = value.get("timeout_seconds", 30)
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 120:
        raise ValueError(
            f"{runtime_context} timeout_seconds must be an integer from 1 to 120"
        )
    runtime = {
        "protocol": protocol,
        "args": args,
        "doctor_args": doctor_args,
        "required_permissions": required_permissions,
        "timeout_seconds": timeout_seconds,
    }
    runtime["entrypoint" if entrypoint is not None else "python_module"] = (
        entrypoint if entrypoint is not None else python_module
    )
    return runtime


def _integration_profile(
    manifest_path: Path,
    profile_ref: object,
    *,
    capability_id: str,
    runtime: Mapping[str, Any] | None,
    context: str,
) -> tuple[dict[str, Any], str]:
    if runtime is None:
        raise ValueError(f"{context} integration_profile requires an executable runtime")
    ref = str(profile_ref or "").strip()
    if not ref:
        raise ValueError(f"{context} integration_profile must be a relative JSON path")
    relative = Path(ref)
    if relative.is_absolute():
        raise ValueError(f"{context} integration_profile must be a relative JSON path")
    extension_root = manifest_path.resolve().parent
    profile_path = (extension_root / relative).resolve()
    try:
        profile_path.relative_to(extension_root)
    except ValueError as exc:
        raise ValueError(
            f"{context} integration_profile must stay inside the extension root"
        ) from exc
    try:
        raw_bytes = profile_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{context} integration_profile is unreadable") from exc
    if len(raw_bytes) > MAX_INTEGRATION_PROFILE_BYTES:
        raise ValueError(
            f"{context} integration_profile exceeds {MAX_INTEGRATION_PROFILE_BYTES} bytes"
        )
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} integration_profile must be a JSON object") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} integration_profile must be a JSON object")
    allowed_profile_fields = {
        "schema_version",
        "capability_id",
        "protocol",
        "operations",
    }
    unknown_profile_fields = sorted(set(value) - allowed_profile_fields)
    if unknown_profile_fields:
        raise ValueError(
            f"{context} integration_profile has unsupported fields "
            f"{unknown_profile_fields}"
        )
    if value.get("schema_version") != EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"{context} integration_profile must use "
            f"{EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION}"
        )
    if value.get("capability_id") != capability_id:
        raise ValueError(
            f"{context} integration_profile capability_id must match `{capability_id}`"
        )
    protocol = _required_string(value, "protocol", context=f"{context} profile")
    if protocol != runtime.get("protocol"):
        raise ValueError(
            f"{context} integration_profile protocol must match runtime protocol "
            f"`{runtime.get('protocol')}`"
        )
    operations = value.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        raise ValueError(
            f"{context} integration_profile operations must contain 1 to 32 objects"
        )
    normalized_operations: list[dict[str, Any]] = []
    operation_ids: set[str] = set()
    for index, item in enumerate(operations):
        operation_context = f"{context} integration_profile operations[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{operation_context} must be an object")
        allowed_operation_fields = {
            "id",
            "effect_class",
            "required_permission",
            "request_schema",
            "result_schema",
        }
        unknown_operation_fields = sorted(set(item) - allowed_operation_fields)
        if unknown_operation_fields:
            raise ValueError(
                f"{operation_context} has unsupported fields "
                f"{unknown_operation_fields}"
            )
        operation_id = _required_string(item, "id", context=operation_context)
        if not _OPERATION_RE.fullmatch(operation_id):
            raise ValueError(
                f"{operation_context} id must be a lower-snake operation token"
            )
        if operation_id in operation_ids:
            raise ValueError(
                f"{context} integration_profile has duplicate operation `{operation_id}`"
            )
        operation_ids.add(operation_id)
        effect_class = _required_string(
            item, "effect_class", context=operation_context
        )
        if effect_class != _EXTERNAL_CAPABILITY_EFFECT_CLASS:
            raise ValueError(
                f"{operation_context} effect_class must be "
                f"`{_EXTERNAL_CAPABILITY_EFFECT_CLASS}` in the v0 profile"
            )
        permission = _required_string(
            item, "required_permission", context=operation_context
        )
        if permission not in runtime.get("required_permissions", []):
            raise ValueError(
                f"{operation_context} required_permission must be declared by runtime"
            )
        request_schema = _required_string(
            item, "request_schema", context=operation_context
        )
        result_schema = _required_string(
            item, "result_schema", context=operation_context
        )
        if not _PROTOCOL_RE.fullmatch(request_schema) or not _PROTOCOL_RE.fullmatch(
            result_schema
        ):
            raise ValueError(
                f"{operation_context} request_schema and result_schema must be "
                "versioned lower-snake tokens"
            )
        normalized_operation = {
            "id": operation_id,
            "effect_class": effect_class,
            "required_permission": permission,
            "request_schema": request_schema,
            "result_schema": result_schema,
        }
        normalized_operations.append(normalized_operation)
    normalized = {
        "schema_version": EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION,
        "capability_id": capability_id,
        "protocol": protocol,
        "operations": normalized_operations,
    }
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(serialized).hexdigest()
    return normalized, digest


def _require_compatible_loopx_api(requirement: str, *, context: str) -> None:
    clauses = [clause.strip() for clause in requirement.split(",")]
    if not clauses or any(not clause for clause in clauses):
        raise ValueError(f"{context} has invalid `requires_loopx_api` `{requirement}`")
    comparisons = {
        ">=": lambda wanted: LOOPX_EXTENSION_API_VERSION >= wanted,
        "<=": lambda wanted: LOOPX_EXTENSION_API_VERSION <= wanted,
        "==": lambda wanted: LOOPX_EXTENSION_API_VERSION == wanted,
        ">": lambda wanted: LOOPX_EXTENSION_API_VERSION > wanted,
        "<": lambda wanted: LOOPX_EXTENSION_API_VERSION < wanted,
    }
    for clause in clauses:
        match = _API_CLAUSE.fullmatch(clause)
        if match is None:
            raise ValueError(
                f"{context} has invalid `requires_loopx_api` clause `{clause}`; "
                "expected integer constraints such as `>=1,<2`"
            )
        operator = match.group(1) or "=="
        wanted = int(match.group(2))
        if not comparisons[operator](wanted):
            raise ValueError(
                f"{context} requires LoopX extension API `{requirement}`, "
                f"but this runtime provides `{LOOPX_EXTENSION_API_VERSION}`"
            )


def load_extension_manifest(path: str | Path) -> dict[str, Any]:
    """Read one declarative manifest without importing extension code."""

    manifest_path = Path(path).expanduser()
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(
            f"cannot read extension manifest `{manifest_path}`: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"extension manifest `{manifest_path}` must contain a TOML table"
        )

    context = f"extension manifest `{manifest_path}`"
    schema_version = _required_string(raw, "schema_version", context=context)
    if schema_version != EXTENSION_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"{context} has unsupported schema_version `{schema_version}`; "
            f"expected `{EXTENSION_MANIFEST_SCHEMA_VERSION}`"
        )
    extension_id = validate_extension_id(
        _required_string(raw, "id", context=context)
    )
    version = _required_string(raw, "version", context=context)
    requires_loopx_api = _required_string(raw, "requires_loopx_api", context=context)
    _require_compatible_loopx_api(requires_loopx_api, context=context)
    permissions = _string_list(raw, "permissions", context=context)
    runtime = _runtime_contract(raw, permissions=permissions, context=context)
    presentation_surfaces = _presentation_surfaces(
        raw,
        runtime=runtime,
        context=context,
    )
    documentation = _documentation_contract(raw, context=context)
    provided = raw.get("provides", [])
    implemented = raw.get("implements", [])
    if not isinstance(provided, list):
        raise ValueError(f"{context} requires `provides` to contain TOML tables")
    if not isinstance(implemented, list):
        raise ValueError(f"{context} requires `implements` to contain TOML tables")
    if runtime is None and not provided and not implemented:
        raise ValueError(
            f"{context} requires an executable `runtime`, `[[provides]]`, "
            "or `[[implements]]`"
        )

    capabilities: list[dict[str, Any]] = []
    for index, item in enumerate(provided):
        item_context = f"{context} provides[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_context} must be a TOML table")
        capability = dict(item)
        capability["id"] = _required_string(item, "id", context=item_context)
        capability["capability_kind"] = _required_string(
            item,
            "kind",
            context=item_context,
        )
        capability["origin"] = "extension"
        capability["visibility"] = str(item.get("visibility", "public")).strip()
        capability["provider_id"] = extension_id
        capability["provider_version"] = version
        if documentation is not None:
            capability["documentation"] = {
                **documentation,
                "aliases": [dict(alias) for alias in documentation["aliases"]],
            }
        profile_ref = item.get("integration_profile")
        if profile_ref is not None:
            profile, profile_digest = _integration_profile(
                manifest_path,
                profile_ref,
                capability_id=str(capability["id"]),
                runtime=runtime,
                context=item_context,
            )
            capability["integration_profile"] = profile
            capability["integration_profile_digest"] = profile_digest
        capabilities.append(capability)

    implementations: list[dict[str, Any]] = []
    for index, item in enumerate(implemented):
        item_context = f"{context} implements[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_context} must be a TOML table")
        protocol = _required_string(item, "protocol", context=item_context)
        if not _PROTOCOL_RE.fullmatch(protocol):
            raise ValueError(
                f"{item_context} protocol must be a versioned lower-snake token"
            )
        if runtime is None:
            raise ValueError(f"{item_context} requires an executable runtime")
        if runtime["protocol"] != protocol:
            raise ValueError(
                f"{item_context} protocol must match runtime protocol "
                f"`{runtime['protocol']}`"
            )
        implementations.append(
            {
                "capability_id": _required_string(
                    item,
                    "capability_id",
                    context=item_context,
                ),
                "protocol": protocol,
                "provider_id": extension_id,
                "provider_version": version,
            }
        )

    return {
        "provider": {
            "id": extension_id,
            "origin": "extension",
            "declared": True,
            "installed": False,
            "enabled": False,
            "ready": False,
            "version": version,
            "requires_loopx_api": requires_loopx_api,
            "permissions": permissions,
        },
        "capabilities": capabilities,
        "implementations": implementations,
        "runtime": runtime,
        "presentation_surfaces": presentation_surfaces,
        "documentation": documentation,
    }
