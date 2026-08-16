from __future__ import annotations

from typing import Any


INTEGRATION_BRANCH_CATALOG_ENTRY: dict[str, Any] = {
    "id": "integration-branch-reconcile",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/integration_branch",
        "site_root": "capabilities/integration-branch",
        "canonical": "README.md",
    },
    "title": "Local integration branch reconciliation",
    "status": "active-preview",
    "real_world_anchor": (
        "long-running repository work with independently reviewed feature branches"
    ),
    "user_value": (
        "Keep one local integration branch aligned with the latest ordered "
        "feature and fix heads without mutating or pushing those source branches."
    ),
    "entry_command": (
        "loopx integration-branch status --repo-path <repo> --format json"
    ),
    "commands": [
        {
            "command": (
                "loopx integration-branch configure --repo-path <repo> "
                "--base-ref <base> --integration-branch <branch> "
                "--source-branch <branch>... --execute --format json"
            ),
            "purpose": "Write one ordered project-local branch plan with no sync receipt.",
            "write_boundary": "ignored local plan only; no git ref or remote write",
        },
        {
            "command": (
                "loopx integration-branch status --repo-path <repo> "
                "[--refresh-remotes] --format json"
            ),
            "purpose": "Optionally refresh remote-tracking refs, then compare exact base, source, and integration heads with the last successful sync.",
            "write_boundary": "remote-read-only inputs; optional fetch updates configured local remote-tracking refs only",
        },
        {
            "command": (
                "loopx integration-branch sync --repo-path <repo> "
                "[--refresh-remotes] [--execute] --format json"
            ),
            "purpose": "Preview or atomically publish an ordered merge candidate to the local integration branch.",
            "write_boundary": "local integration branch, ignored receipt, and optional configured remote-tracking refs only; no source-branch or remote-repository write",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "loopx_integration_branch_plan_v0",
            "module": "loopx.capabilities.integration_branch.core",
            "doc": "loopx/capabilities/integration_branch/README.md",
        },
        {
            "schema_version": "loopx_integration_branch_status_v0",
            "module": "loopx.capabilities.integration_branch.core",
            "doc": "loopx/capabilities/integration_branch/README.md",
        },
        {
            "schema_version": "loopx_integration_branch_sync_v0",
            "module": "loopx.capabilities.integration_branch.core",
            "doc": "loopx/capabilities/integration_branch/README.md",
        },
    ],
    "smokes": ["python -m pytest tests/capabilities/test_integration_branch.py -q"],
    "docs": ["loopx/capabilities/integration_branch/README.md"],
    "boundaries": [
        "The plan is project-local and ignored; it records refs and sync receipts, not credentials, review bodies, or private evidence.",
        "Sync uses exact resolved source heads and updates only the configured local integration branch after every ordered merge succeeds.",
        "Dirty checked-out integration worktrees, merge conflicts, missing refs, and concurrent plan/input/integration movement fail closed before publication.",
        "Remote refresh is explicit and remote-read-only; it updates only configured local remote-tracking refs and never pushes, force-pushes, retargets PRs, merges protected branches, or changes source branches.",
        "v0 uses ordered merge commits; it does not rewrite or squash source history.",
    ],
    "next_real_step": (
        "Configure one local feature stack, change a source head after review, "
        "and verify status reports drift before sync restores an exact readback."
    ),
}
