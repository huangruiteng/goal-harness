from __future__ import annotations

from typing import Any


CHANGE_QUALITY_CATALOG_ENTRY: dict[str, Any] = {
    "id": "change-quality-qualification",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/change_quality",
        "site_root": "capabilities/change-quality",
        "canonical": "README.md",
    },
    "title": "Exact-scope change quality qualification",
    "status": "active-preview",
    "default_enabled": False,
    "real_world_anchor": (
        "provider-neutral final-diff review with bounded repair and merge evidence"
    ),
    "user_value": (
        "Give every managed project the same compact engineering-quality "
        "contract without assuming its language, framework, or agent host."
    ),
    "entry_command": (
        "loopx change-quality prepare --goal-id <goal-id> "
        "--repo-path <repo> --format json"
    ),
    "workflow_skill": {
        "name": "loopx-change-quality",
        "delivery": "project_managed_copy",
        "activation": "explicit_project_install_plus_goal_policy",
        "project_copy_required": True,
        "install_command": (
            "loopx project-skill install --project . --skill "
            "loopx-change-quality --surface codex --execute"
        ),
    },
    "commands": [
        {
            "command": (
                "loopx change-quality prepare --goal-id <goal-id> "
                "--repo-path <repo> --format json"
            ),
            "purpose": "Build a self-contained review contract for the exact final diff.",
            "write_boundary": "read-only git and registry projection; no code or receipt write",
        },
        {
            "command": (
                "loopx change-quality record --goal-id <goal-id> "
                "--repo-path <repo> --result-json <result.json> --execute --format json"
            ),
            "purpose": "Validate a provider result against the exact diff and store its receipt.",
            "write_boundary": "atomic goal-runtime receipt only; no repository or external write",
        },
        {
            "command": (
                "loopx change-quality verify --goal-id <goal-id> "
                "--repo-path <repo> --format json"
            ),
            "purpose": "Verify goal policy and the current exact-diff receipt.",
            "write_boundary": "read-only registry, git, and runtime receipt verification",
        },
        {
            "command": (
                "loopx canary premerge --from-git-diff --goal-id <goal-id>"
            ),
            "purpose": "Apply strict receipt policy inside the authoritative premerge gate.",
            "write_boundary": "validation only; no merge, push, or external action",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "change_quality_scope_v0",
            "module": "loopx.capabilities.change_quality.scope",
            "doc": "loopx/capabilities/change_quality/README.md",
        },
        {
            "schema_version": "change_quality_prepare_packet_v2",
            "module": "loopx.capabilities.change_quality.receipt",
            "doc": "loopx/capabilities/change_quality/README.md",
        },
        {
            "schema_version": "change_quality_agent_result_v2",
            "module": "loopx.capabilities.change_quality.result",
            "doc": "loopx/capabilities/change_quality/README.md",
        },
        {
            "schema_version": "change_quality_receipt_v2",
            "module": "loopx.capabilities.change_quality.receipt",
            "doc": "loopx/capabilities/change_quality/README.md",
        },
        {
            "schema_version": "change_quality_receipt_verification_v2",
            "module": "loopx.capabilities.change_quality.receipt",
            "doc": "loopx/capabilities/change_quality/README.md",
        },
    ],
    "smokes": ["python3 examples/change-quality-qualification-smoke.py"],
    "docs": ["loopx/capabilities/change_quality/README.md"],
    "boundaries": [
        "The capability is default-off and activates only through explicit per-goal policy; managed skill discovery is a separate project-level choice.",
        "safe_fix permits at most one bounded repair pass; it grants no destructive git, permission expansion, or unrelated refactor authority.",
        "strict_receipt is an exact-diff premerge evidence gate and does not itself permit code mutation.",
        "Subjective style advice stays nonblocking; only concrete correctness, security, privacy, contract, or required-validation failures may block.",
        "Turn may transport a packet or receipt reference, but premerge remains the enforcement authority.",
        "The canonical workflow skill is release-owned and project-delivered; the global installer does not publish it into every agent configuration.",
        "Receipts stay in local runtime state; raw model transcripts, private context, and credentials are not persisted.",
        "Agents write only grounded reuse and simplification conclusions, sparse triggered risks, and validation evidence; LoopX derives guardrail states.",
        "Existing v1 receipts remain verifiable read-only for their exact scope; new receipts use v2.",
        "The first version is single-level: it qualifies one final diff and does not recursively review reviews.",
    ],
    "next_real_step": (
        "Enable it on an explicit goal, qualify one final diff, and verify "
        "that safe-fix and strict-receipt policies remain independently enforced."
    ),
}
