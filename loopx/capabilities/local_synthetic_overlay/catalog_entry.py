from __future__ import annotations

from typing import Any


LOCAL_SYNTHETIC_OVERLAY_CATALOG_ENTRY: dict[str, Any] = {
    "id": "local-synthetic-overlay",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/local_synthetic_overlay",
        "site_root": "capabilities/local-synthetic-overlay",
        "canonical": "README.md",
    },
    "title": "Task-bound local synthetic validation overlay",
    "status": "active-preview",
    "real_world_anchor": (
        "local disposable validation that needs containers and a synthetic database but no product write authority"
    ),
    "user_value": (
        "Issue one short-lived exact-candidate receipt for a strictly local synthetic validation task without using a legacy queue or granting product writes."
    ),
    "entry_command": (
        "loopx local-synthetic-overlay doctor --synthetic-database-image <digest-pinned-image> --format json"
    ),
    "commands": [
        {
            "command": "loopx local-synthetic-overlay doctor --synthetic-database-image <digest-pinned-image> --format json",
            "purpose": "Truthfully inspect the local Docker daemon and an already-local digest-pinned database image without pulling or creating anything.",
            "write_boundary": "read-only local runtime inspection",
        },
        {
            "command": "loopx local-synthetic-overlay issue [exact task and candidate bindings] --execute --format json",
            "purpose": "Persist one short-lived system-managed receipt for the exact Goal, Todo, candidate, and closed capability set.",
            "write_boundary": "LoopX runtime receipt directory only; product-write scope remains ZERO",
        },
        {
            "command": "loopx local-synthetic-overlay validate [receipt and exact bindings] --format json",
            "purpose": "Revalidate digest, task lifetime, active Goal/Todo, tracked-clean HEAD/tree, and the restrictive envelope.",
            "write_boundary": "read-only LoopX state and Git inspection",
        },
        {
            "command": "loopx local-synthetic-overlay cleanup-check [receipt and exact bindings] --compose-project <task-project> --format json",
            "purpose": "Prove the task-labelled Compose project has no remaining container, volume, or network.",
            "write_boundary": "read-only Docker metadata inspection",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "loopx_local_synthetic_overlay_receipt_v0",
            "module": "loopx.capabilities.local_synthetic_overlay.core",
            "doc": "loopx/capabilities/local_synthetic_overlay/README.md",
        },
        {
            "schema_version": "loopx_local_synthetic_overlay_provider_doctor_v0",
            "module": "loopx.capabilities.local_synthetic_overlay.core",
            "doc": "loopx/capabilities/local_synthetic_overlay/README.md",
        },
        {
            "schema_version": "loopx_local_synthetic_overlay_cleanup_v0",
            "module": "loopx.capabilities.local_synthetic_overlay.core",
            "doc": "loopx/capabilities/local_synthetic_overlay/README.md",
        },
    ],
    "smokes": [
        "python -m pytest tests/capabilities/test_local_synthetic_overlay.py -q"
    ],
    "docs": ["loopx/capabilities/local_synthetic_overlay/README.md"],
    "boundaries": [
        "The only allowed capabilities are the exact pair local_container and synthetic_database.",
        "Product-write scope is exactly ZERO; a non-empty file allowlist is neither accepted nor required.",
        "Every receipt is bound to one live Goal/Todo, exact tracked-clean candidate HEAD/tree, local repository, provider revision, and short expiry.",
        "Real customer or child data, real audio, real providers, hosted databases, production, cross-task reuse, network image pulls, arbitrary container commands, and deployment are rejected.",
        "Legacy Dispatcher schemas, queues, leases, grants, and databases are not read by this capability.",
        "The provider doctor reports unavailable runtimes as unavailable and never manufactures readiness.",
    ],
    "next_real_step": (
        "Issue one task-bound receipt for an exact local synthetic candidate, run the caller-owned validation, and prove Compose cleanup."
    ),
}
