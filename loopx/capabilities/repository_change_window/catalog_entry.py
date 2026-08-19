from __future__ import annotations

from typing import Any


REPOSITORY_CHANGE_WINDOW_CATALOG_ENTRY: dict[str, Any] = {
    "id": "repository-change-window",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/repository_change_window",
        "site_root": "capabilities/repository-change-window",
        "canonical": "README.md",
    },
    "title": "Repository change windows and pending-change continuity",
    "status": "active-preview",
    "real_world_anchor": (
        "repositories whose local commit or push operations must pause during a configured window"
    ),
    "user_value": (
        "Apply an explicit local repository change schedule while retaining a restart-safe global inventory of blocked unmerged work."
    ),
    "entry_command": "loopx change-window status --repo-path <repo> --format json",
    "commands": [
        {
            "command": "loopx change-window install --repo-path <repo> [policy options] [--enforcement-level hook_only|reference_guard] [--execute] --format json",
            "purpose": "Preview or install the bundled Git-hook provider for one repository.",
            "write_boundary": "repository-local Git config and private Git common-directory provider state only",
        },
        {
            "command": "loopx change-window status --repo-path <repo> --format json",
            "purpose": "Read provider health, the typed policy, and the trusted-clock decision.",
            "write_boundary": "read-only",
        },
        {
            "command": "loopx change-window verify --repo-path <repo> --format json",
            "purpose": "Verify managed hook bytes, executable modes, and the active repository hook route.",
            "write_boundary": "read-only",
        },
        {
            "command": "loopx change-window uninstall --repo-path <repo> [--execute] --format json",
            "purpose": "Preview or remove the provider while restoring the exact previous repository hook route.",
            "write_boundary": "repository-local Git config and managed provider state only",
        },
        {
            "command": "loopx change-window record --repo-path <repo> [metadata] [--execute] --format json",
            "purpose": "Register or refresh a public-safe reference to unmerged work in the shared runtime ledger.",
            "write_boundary": "shared runtime pending-change event ledger and machine-private locator sidecar",
        },
        {
            "command": "loopx change-window reconcile --repo-path <repo> [--all-linked-worktrees] [--execute] --format json",
            "purpose": "Repair the current dirty checkout, or explicitly sweep all linked and detached worktrees, during a blocked window.",
            "write_boundary": "shared runtime pending-change event ledger and machine-private locator path inventory",
        },
        {
            "command": "loopx change-window list [--state open|resolved|all] --format json",
            "purpose": "Read the cross-project pending-change projection after restart or handoff.",
            "write_boundary": "read-only",
        },
        {
            "command": "loopx change-window resolve --change-id <id> --resolution <kind> --evidence <ref> [--execute] --format json",
            "purpose": "Append an idempotent typed merged, superseded, or abandoned terminal transition.",
            "write_boundary": "shared runtime pending-change event ledger and machine-private locator cleanup",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "repository_change_window_policy_v0",
            "module": "loopx.capabilities.repository_change_window.policy",
            "doc": "loopx/capabilities/repository_change_window/README.md",
        },
        {
            "schema_version": "repository_change_window_git_hook_state_v2",
            "module": "loopx.capabilities.repository_change_window.git_hook",
            "doc": "loopx/capabilities/repository_change_window/README.md",
        },
        {
            "schema_version": "repository_pending_change_event_v0",
            "module": "loopx.capabilities.repository_change_window.ledger",
            "doc": "loopx/capabilities/repository_change_window/README.md",
        },
    ],
    "implementation_providers": [
        {
            "provider_id": "git-hook",
            "origin": "builtin",
            "protocol": "repository_change_window_git_hook_state_v2",
            "status": "available_default_off",
        }
    ],
    "smokes": [
        "python -m pytest tests/capabilities/test_repository_change_window.py -q"
    ],
    "docs": ["loopx/capabilities/repository_change_window/README.md"],
    "boundaries": [
        "The capability is disabled until an explicit executed install for a repository.",
        "The hook provider uses a trusted invocation clock; fake clocks exist only as an injected test seam.",
        "Pending-change events store references, digests, counts, and typed lifecycle data, never code bodies, diff bodies, credentials, or local absolute paths.",
        "A private locator sidecar may retain a local worktree path and repository-relative changed-path inventory for recovery, but those values are never copied into the shared projection or command result.",
        "The opt-in reference_guard blocks newly created commit ref updates that --no-verify cannot skip and guards the repository SSH command route; HTTPS, alternate Git configuration, another machine, and hosting APIs remain outside local authority.",
    ],
    "next_real_step": (
        "Install the provider in one non-production repository, trigger one blocked change with a fake-clock test, and verify the pending record from a linked worktree."
    ),
}
