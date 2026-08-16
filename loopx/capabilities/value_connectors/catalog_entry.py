from __future__ import annotations

from typing import Any


VALUE_CONNECTORS_CATALOG_ENTRY: dict[str, Any] = {
    "id": "value-connectors",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/value_connectors",
        "site_root": "capabilities/value-connectors",
        "canonical": "README.md",
    },
    "title": "Value connector compatibility facade",
    "status": "compatibility-facade",
    "real_world_anchor": "external channel intake for revenue, cost, demand, and connector reuse",
    "user_value": (
        "Keep existing connector commands and packet schemas stable while "
        "each profile moves to the outcome capability that serves callers."
    ),
    "entry_command": "loopx value-connectors source-map --format json",
    "commands": [
        {
            "command": "loopx value-connectors install-check --format json",
            "purpose": "Show connector starter install/use commands and local dependency status.",
            "write_boundary": "local check only; no external read or write",
        },
        {
            "command": "loopx value-connectors source-map --format json",
            "purpose": "Give agents a read-first source-map packet for all currently surfaced connector profiles.",
            "write_boundary": "packet only; no external read, write, account setup, or raw payload capture",
        },
        {
            "command": "loopx value-connectors github-public-probe --url <github-issue-or-pr-url> --format json",
            "purpose": "Validate a public GitHub channel URL and build a connector call packet.",
            "write_boundary": "no network read unless --fetch-metadata is provided",
            "compatibility_for": "issue-fix",
        },
        {
            "command": "loopx value-connectors github-public-probe --url <github-issue-or-pr-url> --fetch-metadata --format json",
            "purpose": "Fetch allowlisted public GitHub metadata without body/comment/timeline content.",
            "write_boundary": "public metadata read only; no comments, PRs, account changes, or writes",
            "compatibility_for": "issue-fix",
        },
        {
            "command": "loopx value-connectors github-reply-monitor --issue-url <github-issue-or-pr-url> --after-comment-url <github-issue-comment-url> --fetch-metadata --format json",
            "purpose": "Detect public maintainer replies after a LoopX comment without capturing comment bodies.",
            "write_boundary": "public comment metadata read only; no comment bodies, thread bump, or external write",
            "compatibility_for": "issue-fix",
        },
        {
            "command": "loopx value-connectors plan --connector-id <id> ... --format json",
            "purpose": "Plan gated account setup, external replies, sends, or future connector calls.",
            "write_boundary": "plan-only; external writes and account setup require exact approval",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "value_connector_plan_v0",
            "module": "loopx.capabilities.value_connectors.planner",
            "doc": "docs/reference/protocols/value-connector-plan-v0.md",
        },
        {
            "schema_version": "connector_call_intent_v0",
            "module": "loopx.capabilities.value_connectors.planner",
            "doc": "docs/reference/protocols/value-connector-plan-v0.md",
        },
        {
            "schema_version": "connector_approval_gate_v0",
            "module": "loopx.capabilities.value_connectors.planner",
            "doc": "docs/reference/protocols/value-connector-plan-v0.md",
        },
        {
            "schema_version": "value_connector_install_check_packet_v0",
            "module": "loopx.capabilities.value_connectors.install_check",
            "doc": "docs/reference/protocols/value-connector-plan-v0.md",
        },
        {
            "schema_version": "value_connector_source_map_packet_v0",
            "module": "loopx.capabilities.value_connectors.source_map",
            "doc": "loopx/capabilities/value_connectors/docs/agent-reach-ops-source-map.md",
        },
    ],
    "smokes": [
        "python3 examples/value-connectors-github-public-probe-smoke.py",
    ],
    "docs": [
        "loopx/capabilities/value_connectors/README.md",
        "docs/reference/protocols/value-connector-plan-v0.md",
    ],
    "boundaries": [
        "The GitHub starter copies allowlisted public metadata only, not bodies, comments, timelines, raw provider payloads, auth material, or local paths.",
        "The reply monitor reads or accepts comment metadata only: author, association, timestamps, and URL; it never bumps a thread.",
        "Account signup, email sends, community posts, public replies, private reads, paid services, and production actions remain gated exact-call actions.",
        "Every connector call must include a money, cost, demand, or capability metric plus a kill condition.",
    ],
    "next_real_step": (
        "Move one mapped profile at a time to its declared outcome capability, "
        "keeping this CLI and its packet schemas stable until callers migrate."
    ),
}
