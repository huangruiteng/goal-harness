from __future__ import annotations

from typing import Any


AUTO_RESEARCH_CATALOG_ENTRY: dict[str, Any] = {
    "id": "auto-research",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/auto_research",
        "site_root": "capabilities/auto-research",
        "canonical": "README.md",
        "aliases": [
            {
                "source": "README.md",
                "site": "guides/auto-research-command-path.md",
            },
        ],
    },
    "title": "Decentralized auto-research preset",
    "status": "experimental",
    "real_world_anchor": (
        "one-question research contracts with role-scoped workers, evidence packets, and a visible frontier"
    ),
    "user_value": (
        "Launch a thin multi-agent research recipe while reusing LoopX todo, quota, "
        "history, evidence, and continuation contracts."
    ),
    "entry_command": "loopx auto-research <open-question>",
    "commands": [
        {
            "command": "loopx auto-research <open-question>",
            "purpose": "Render the fixed one-question contract, bounded plan, and exact start command.",
            "write_boundary": "stateless contract output only",
        },
        {
            "command": "loopx auto-research start <open-question> --execute",
            "purpose": "Create an isolated goal and launch visible role-scoped workers through the shared multi-agent runtime.",
            "write_boundary": "local goal, workspace, and visible launcher state; no publication, benchmark submission, or protected external action",
        },
        {
            "command": "loopx auto-research decide --goal-id <goal-id> --hypothesis-id <id> --outcome <promoted|retired> --reason <reason> --agent-id <agent-id> --execute",
            "purpose": "Record one terminal research decision after current evidence satisfies the promotion or retirement contract.",
            "write_boundary": "one public-safe validation event bound to the current hypothesis evidence revision",
        },
        {
            "command": "loopx auto-research review --goal-id <goal-id> --hypothesis-id <id> --reviewer-agent-id <peer-id> --verdict <verdict> --require-independent --execute",
            "purpose": "Record a registered-peer review receipt without rewriting the research evidence or terminal decision.",
            "write_boundary": "one public-safe validation receipt; independent mode rejects producer and decision-agent self-review",
        },
        {
            "command": "loopx auto-research results --goal-id <goal-id> [--hypothesis-id <id>] [--include-history]",
            "purpose": "Read exact current and historical terminal outcomes, review state, and Explore readback.",
            "write_boundary": "read-only projection over rollout and Explore result events",
        },
        {
            "command": "loopx auto-research project-results --goal-id <goal-id> --execute",
            "purpose": "Project current terminal outcomes into deterministic existing Explore node and finding events.",
            "write_boundary": "goal-scoped Explore result log only; repeated projection is idempotent",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "auto_research_user_contract_v0",
            "module": "loopx.capabilities.auto_research.user_contract",
            "doc": "loopx/capabilities/auto_research/README.md",
        },
        {
            "schema_version": "decentralized_auto_research_projection_v0",
            "module": "loopx.capabilities.auto_research.research_state",
            "doc": "docs/reference/protocols/decentralized-auto-research-state-v0.md",
        },
        {
            "schema_version": "auto_research_terminal_decision_v0",
            "module": "loopx.capabilities.auto_research.terminal_result_contract",
            "doc": "docs/reference/protocols/decentralized-auto-research-state-v0.md",
        },
        {
            "schema_version": "auto_research_peer_review_v0",
            "module": "loopx.capabilities.auto_research.terminal_result_contract",
            "doc": "docs/reference/protocols/auto-research-lane-contract-v1.md",
        },
        {
            "schema_version": "auto_research_terminal_result_query_v0",
            "module": "loopx.capabilities.auto_research.terminal_result_query",
            "doc": "docs/reference/protocols/decentralized-auto-research-state-v0.md",
        },
        {
            "schema_version": "auto_research_terminal_result_projection_v0",
            "module": "loopx.capabilities.auto_research.terminal_results",
            "doc": "docs/reference/protocols/decentralized-auto-research-state-v0.md",
        },
    ],
    "smokes": [
        "python3 examples/auto-research-user-contract-entry-smoke.py",
        "python3 examples/auto-research-worker-turn-smoke.py",
        "python3 examples/auto-research-terminal-results-smoke.py",
        "python3 examples/auto-research-terminal-results-cli-smoke.py",
    ],
    "docs": [
        "loopx/capabilities/auto_research/README.md",
        "docs/product/use-cases/auto-research/decentralized-auto-research-showcase.md",
    ],
    "boundaries": [
        "The preset reuses shared control-plane and multi-agent contracts; it is not a second scheduler or runner.",
        "Completion and uplift require role-authored evidence and projected outcomes; the launcher does not manufacture research results.",
        "Promotion and retirement candidates are not terminal decisions; explicit decisions bind one hypothesis evidence revision.",
        "Same-agent review remains visible but cannot be labeled independent or upgrade a finding to confirmed or refuted.",
    ],
    "next_real_step": (
        "Use the one-question entrypoint for bounded research and preserve every promoted or rejected outcome in canonical evidence."
    ),
}
