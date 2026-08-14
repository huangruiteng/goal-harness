from __future__ import annotations

from typing import Any

PROJECT_BINDING_FIELDS = (
    "repository_bindings",
    "external_locator_bindings",
)


def validate_project_record_bindings(
    project: dict[str, Any],
    *,
    source: str,
) -> None:
    for field in PROJECT_BINDING_FIELDS:
        if field not in project:
            continue
        values = project[field]
        if not isinstance(values, list):
            raise TypeError(f"{source} ProjectRecord {field} must be a list")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(
                f"{source} ProjectRecord {field} entries must be non-empty strings"
            )
