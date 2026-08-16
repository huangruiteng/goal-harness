from __future__ import annotations

from typing import Any


SEMANTIC_PREFERENCE_CATALOG_ENTRY: dict[str, Any] = {
    "id": "semantic-preference",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/semantic_preference",
        "site_root": "capabilities/semantic-preference",
        "canonical": "README.md",
    },
    "title": "Optional semantic preference hook",
    "status": "active-preview",
    "real_world_anchor": "provider-neutral preference recall before domain work",
    "user_value": (
        "Let any LoopX module recall provider-owned semantic preferences and "
        "record a compact application receipt without creating a second memory ledger."
    ),
    "entry_command": "loopx semantic-preference recall --config <ignored-config.json> --surface <module.surface> --format json",
    "commands": [
        {
            "command": "loopx semantic-preference doctor --config <ignored-config.json> --execute --format json",
            "purpose": "Check a configured provider entry point and optional read-only probe, then return explicit install/config guidance when unavailable.",
            "write_boundary": "read-only discovery; never installs packages, starts services, changes config, or writes credentials",
        },
        {
            "command": "loopx semantic-preference recall --config <ignored-config.json> --surface <module.surface> --execute --format json",
            "purpose": "Send one bounded recall request to a configured command_json_v0 provider.",
            "write_boundary": "provider read only; LoopX does not persist recalled semantic content",
        },
        {
            "command": "loopx semantic-preference receipt --surface <module.surface> --application-id <id> --outcome applied --format json",
            "purpose": "Build a compact receipt with hashed preference references for existing evidence/state writeback.",
            "write_boundary": "stateless output only; no provider, file, or external write",
        },
        {
            "command": "loopx semantic-preference maintenance-receipt --trigger explicit_feedback --outcome verified --corpus-id <id> --format json",
            "purpose": "Build a compact receipt after a provider-owned corpus maintenance decision and readback closure.",
            "write_boundary": "stateless output only; scope references are hashed and semantic content is excluded",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "semantic_preference_hook_config_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
        {
            "schema_version": "semantic_preference_provider_request_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
        {
            "schema_version": "semantic_preference_provider_doctor_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
        {
            "schema_version": "semantic_preference_application_receipt_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
        {
            "schema_version": "semantic_preference_maintenance_guidance_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
        {
            "schema_version": "semantic_preference_maintenance_receipt_v0",
            "module": "loopx.capabilities.semantic_preference.contract",
            "doc": "loopx/capabilities/semantic_preference/README.md",
        },
    ],
    "smokes": [
        "python3 examples/semantic-preference-hook-smoke.py",
        "python3 examples/openviking-extension-runtime-smoke.py",
    ],
    "docs": ["loopx/capabilities/semantic_preference/README.md"],
    "boundaries": [
        "The hook is disabled until an enabled local-private config is supplied.",
        "Surface ids and queries are domain-owned configuration; the runtime has no issue-fix branch.",
        "LoopX does not persist recalled semantic content, receipts, provider commands, config paths, or raw errors.",
        "Provider failures follow explicit fail-open/fail-closed policy and do not become user gates automatically.",
        "Provider setup remains guidance-only: package, service, config, and credential writes require an explicit operator action.",
    ],
    "next_real_step": (
        "Keep the hook opt-in until a second domain module proves useful recall and existing-state receipt writeback."
    ),
}
