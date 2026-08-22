from __future__ import annotations

from typing import Any


CONNECTOR_REGISTRY_CATALOG_ENTRY: dict[str, Any] = {
    "id": "connector-registry",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/connector_registry",
        "site_root": "capabilities/connector-registry",
        "canonical": "README.md",
    },
    "title": "Unified public-connector registry with value-priority ranking",
    "status": "active-preview",
    "real_world_anchor": (
        "the set of public connectors (market data, announcements, capital flow, "
        "financials, news/alt, paid) that LoopX consumers like finance can use"
    ),
    "user_value": (
        "One place to see which connectors are supported vs pending/blocked, "
        "their layer (L0-L5), and a usage-driven value-priority ranking."
    ),
    "next_real_step": (
        "run `loopx connector list --format json` to see the catalog and ranking; "
        "record each real call with `loopx connector use <id>`."
    ),
    "entry_command": "loopx connector list --format json",
    "commands": [
        {
            "command": "loopx connector list --format json",
            "purpose": "List all public connectors with status, layer, value tier, usage, and priority.",
            "write_boundary": "read-only",
        },
        {
            "command": "loopx connector register <id> --status supported --value-tier P1 ...",
            "purpose": "Register or update a connector in the local registry.",
            "write_boundary": "local registry write only",
        },
        {
            "command": "loopx connector use <id> --ok --ms <elapsed-ms>",
            "purpose": "Record a real connector call so the value-priority ranking evolves.",
            "write_boundary": "local registry write only",
        },
        {
            "command": "loopx connector rank --format json",
            "purpose": "Show the value-priority ranking across all connectors.",
            "write_boundary": "read-only",
        },
    ],
}
