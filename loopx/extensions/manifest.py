from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import tomllib
from typing import Any


EXTENSION_MANIFEST_SCHEMA_VERSION = "loopx_extension_manifest_v0"
LOOPX_EXTENSION_API_VERSION = 1
_API_CLAUSE = re.compile(r"^(>=|<=|==|>|<)?\s*(\d+)$")


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
    extension_id = _required_string(raw, "id", context=context)
    version = _required_string(raw, "version", context=context)
    requires_loopx_api = _required_string(raw, "requires_loopx_api", context=context)
    _require_compatible_loopx_api(requires_loopx_api, context=context)
    permissions = _string_list(raw, "permissions", context=context)
    provided = raw.get("provides")
    if not isinstance(provided, list) or not provided:
        raise ValueError(f"{context} requires at least one `[[provides]]` table")

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
        capabilities.append(capability)

    return {
        "provider": {
            "id": extension_id,
            "origin": "extension",
            "enabled": True,
            "version": version,
            "requires_loopx_api": requires_loopx_api,
            "permissions": permissions,
        },
        "capabilities": capabilities,
    }
