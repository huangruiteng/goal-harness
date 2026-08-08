#!/usr/bin/env python3
"""Smoke-test the public docs information architecture."""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

ROOT_DOCS = {
    "README.md",
    "architecture.md",
    "heartbeat-automation-prompt.md",
    "index.md",
    "integration.md",
    "project-agent-todo-contract.md",
    "public-private-boundary.md",
    "quota-allocation.md",
    "state-interaction-model.md",
    "status-data-contract.md",
}

PRODUCT_ROOT_DOCS = {
    "README.md",
    "domain-capability-packs.md",
    "public-adoption-loop.md",
    "release-note-template.md",
    "release-readiness.md",
    "scenario-capability-gap-map.md",
    "vision.md",
}

LOCAL_LINK_PATTERNS = (
    re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)"),
    re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE),
    re.compile(r"\b(?:href|src)=[\"']([^\"']+)[\"']"),
)


MOVED_PATHS = {
    "docs/commit-readiness-manifest-20260603.md": (
        "docs/archive/release-readiness/commit-readiness-manifest-20260603.md"
    ),
    "docs/commit-readiness-manifest-20260606.md": (
        "docs/archive/release-readiness/commit-readiness-manifest-20260606.md"
    ),
    "docs/outcome-floor-safe-bypass-incident-20260606.md": (
        "docs/archive/incidents/outcome-floor-safe-bypass-incident-20260606.md"
    ),
    "docs/protocol-action-packet-codex-cli-wrapper-v0.md": (
        "docs/reference/protocols/protocol-action-packet-codex-cli-wrapper-v0.md"
    ),
    "docs/protocol-action-packet-decision-v0.md": (
        "docs/reference/protocols/protocol-action-packet-decision-v0.md"
    ),
    "docs/protocol-action-packet-router-comparison-v0.md": (
        "docs/reference/protocols/protocol-action-packet-router-comparison-v0.md"
    ),
    "docs/codex-cli-long-run-benchmark-design.md": (
        "docs/research/long-horizon-agent-benchmarks/"
        "codex-cli-long-run-benchmark-design.md"
    ),
    "docs/codex-cli-long-run-regression.md": (
        "docs/research/long-horizon-agent-benchmarks/"
        "codex-cli-long-run-regression.md"
    ),
    "docs/project-skill-delivery.md": (
        "docs/reference/project-skill-delivery.md"
    ),
}


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def compact(text: str) -> str:
    return " ".join(text.split())


def subsection(text: str, heading: str) -> str:
    marker = f"### {heading}"
    assert marker in text, marker
    body = text.split(marker, 1)[1]
    return body.split("\n### ", 1)[0].split("\n## ", 1)[0]


def assert_local_doc_links_resolve() -> None:
    for source in DOCS.rglob("*"):
        if source.suffix.lower() not in {".md", ".html"}:
            continue
        text = source.read_text(encoding="utf-8")
        for pattern in LOCAL_LINK_PATTERNS:
            for match in pattern.finditer(text):
                raw_target = match.group(1)
                if raw_target.startswith("<") and raw_target.endswith(">"):
                    raw_target = raw_target[1:-1]
                if not raw_target or raw_target.startswith(
                    (
                        "#",
                        "/",
                        "http://",
                        "https://",
                        "mailto:",
                        "data:",
                        "javascript:",
                    )
                ):
                    continue
                relative_target = raw_target.split("#", 1)[0].split("?", 1)[0]
                if not relative_target:
                    continue
                resolved = (source.parent / relative_target).resolve()
                assert resolved.exists(), (
                    f"broken local docs link: {source.relative_to(REPO_ROOT)} "
                    f"-> {raw_target}"
                )


def assert_effect_interpreter_docs_are_canonical() -> None:
    public_lecture_url_fragments = (
        "6a01d501000000003700c5de",
        "6a02f388000000003502b2d6",
        "6a057524000000003701f6aa",
    )
    packet_doc = compact(read("docs/reference/effect-interpreter-packet.md"))
    for required in (
        "EffectRequest",
        "EffectInterpretation",
        "EffectObservation",
        "EffectNext",
        "EffectTurn",
        "Around Semantics",
        "execution_mode",
        "interpret_turn_result_packet",
    ):
        assert required in packet_doc, required

    rfc = compact(read("docs/architecture/rfcs/agent-loop-effect-interpreter-v0.md"))
    for required in (
        "Composition And Around Semantics",
        "Handler Is Data, Not a Callable",
        "General Effect-Program Abstraction",
        "M6: General Effect-Program Abstraction",
        "Milestone Status",
    ):
        assert required in rfc, required

    architecture = compact(read("docs/architecture.md"))
    assert "Control Plane As Effect Interpreter" in architecture

    lecture = compact(
        read("docs/development/control-plane-course/01-agent-loop-effectful-program.md")
    )
    assert "Around 是数据，不是回调" in lecture
    assert "CLI 是更高密度的 effect" in lecture
    for fragment in public_lecture_url_fragments:
        assert fragment in rfc, fragment
        assert fragment in lecture, fragment


def main() -> int:
    docs_index = read("docs/README.md")
    root_readme = read("README.md")
    root_readme_zh = read("README.zh-CN.md")
    auto_research_command_path = read("docs/guides/auto-research-command-path.md")
    codex_cli_tui_loop = read("docs/product/runtimes/codex-cli/codex-cli-tui-loop.md")
    project_agent_contract = read("docs/project-agent-todo-contract.md")
    status_contract = read("docs/status-data-contract.md")
    compact_auto_research_command_path = compact(auto_research_command_path)
    compact_codex_cli_tui_loop = compact(codex_cli_tui_loop)
    compact_project_agent_contract = compact(project_agent_contract)
    compact_status_contract = compact(status_contract)

    for required in [
        "## Choose Your Path",
        "## Core References",
        "## Browse By Subject",
        "## Documentation Policy",
        "architecture/README.md",
        "concepts/README.md",
        "operations/README.md",
        "integrations/README.md",
        "product/README.md",
        "development/README.md",
        "reference/README.md",
        "showcases/README.md",
        "development/testing-and-quality.md",
    ]:
        assert required in docs_index, required

    navigation_contracts = {
        "Use and Operate": [
            "docs/operations/README.md",
            "docs/quota-allocation.md",
            "docs/heartbeat-automation-prompt.md",
            "docs/status-data-contract.md",
        ],
        "Understand the Control Plane": [
            "docs/concepts/README.md",
            "docs/product/foundations/README.md",
            "docs/product/vision.md",
        ],
        "Integrate and Extend": [
            "docs/integration.md",
            "docs/integrations/README.md",
        ],
        "Build and Review LoopX": [
            "docs/development/README.md",
            "docs/reference/README.md",
            "docs/development/control-plane-course/README.md",
            "docs/development/testing-and-quality.md",
            "docs/public-private-boundary.md",
        ],
        "Inspect Outcomes": [
            "docs/showcases/README.md",
            "docs/research/README.md",
            "docs/update-notes/README.md",
        ],
        "Project and Community": [
            "GOVERNANCE.md",
            "CONTRIBUTING.md",
            "CONTRIBUTOR_TASKS.md",
            "AUTHORS.md",
            "docs/project/history.md",
            "TRADEMARKS.md",
        ],
    }
    navigation_contracts_zh = {
        "使用与运维": navigation_contracts["Use and Operate"],
        "理解控制面": navigation_contracts["Understand the Control Plane"],
        "集成与扩展": navigation_contracts["Integrate and Extend"],
        "构建与评审 LoopX": navigation_contracts["Build and Review LoopX"],
        "查看结果与证据": navigation_contracts["Inspect Outcomes"],
        "项目与社区": navigation_contracts["Project and Community"],
    }
    for readme, contracts in (
        (root_readme, navigation_contracts),
        (root_readme_zh, navigation_contracts_zh),
    ):
        for heading, required_links in contracts.items():
            section = subsection(readme, heading)
            for required in required_links:
                assert required in section, f"{heading}: {required}"

    assert "### Validate and Govern" not in root_readme
    assert "### 验证与治理" not in root_readme_zh
    advanced_docs = root_readme.split("## Advanced Documentation", 1)[1].split(
        "\n## ", 1
    )[0]
    advanced_docs_zh = root_readme_zh.split("## 进阶文档", 1)[1].split(
        "\n## ", 1
    )[0]
    for deep_link in [
        "docs/development/benchmark-developer-workflow.md",
        "docs/product/foundations/project-level-reward-model.md",
        "docs/reference/protocols/reward-memory-architecture-v0.md",
        "docs/reference/protocols/reward-memory-architecture-v0.zh-CN.md",
    ]:
        assert deep_link not in advanced_docs
        assert deep_link not in advanced_docs_zh

    for path in [
        "docs/archive/README.md",
        "docs/archive/incidents/README.md",
        "docs/archive/release-readiness/README.md",
        "docs/architecture/README.md",
        "docs/architecture/rfcs/README.md",
        "docs/architecture/rfcs/agent-im-openviking-collaboration-v0.md",
        "docs/concepts/README.md",
        "docs/operations/README.md",
        "docs/product/README.md",
        "docs/product/release-note-template.md",
        "docs/product/foundations/README.md",
        "docs/product/migrations/README.md",
        "docs/product/roadmaps/README.md",
        "docs/product/runtimes/README.md",
        "docs/product/runtimes/codex-app/README.md",
        "docs/product/runtimes/codex-cli/README.md",
        "docs/product/surfaces/README.md",
        "docs/product/use-cases/README.md",
        "docs/development/README.md",
        "docs/development/documentation-layout.md",
        "docs/development/testing-and-quality.md",
        "docs/guides/README.md",
        "docs/guides/auto-research-command-path.md",
        "docs/guides/multi-agent-product-recipe.md",
        "docs/integrations/README.md",
        "docs/reference/README.md",
        "docs/reference/contracts/README.md",
        "docs/reference/protocols/README.md",
        "docs/research/README.md",
        "docs/research/long-horizon-agent-benchmarks/README.md",
        "docs/showcases/README.md",
        "docs/product/runtimes/codex-cli/codex-cli-tui-loop.md",
    ]:
        assert (REPO_ROOT / path).is_file(), path

    developer_index = read("docs/development/README.md")
    quality_guide = read("docs/development/testing-and-quality.md")
    for required in [
        "testing-and-quality.md",
        "Model behavior qualification v0",
        "Release outcome baseline v0",
    ]:
        assert required in developer_index, required
    for required in [
        "Quality Layers",
        "Agent-Facing Output Budgets",
        "Decision Replay And Issue #2191",
        "Doubao Model-Behavior Gate",
        "Release Outcome Baseline",
    ]:
        assert required in quality_guide, required

    root_markdown = {path.name for path in DOCS.glob("*.md")}
    assert root_markdown == ROOT_DOCS, sorted(root_markdown)

    product_root_markdown = {
        path.name for path in (DOCS / "product").glob("*.md")
    }
    assert product_root_markdown == PRODUCT_ROOT_DOCS, sorted(product_root_markdown)

    assert not (DOCS / "outreach").exists(), (
        "retired marketing and launch drafts must stay out of the active docs tree"
    )

    assert_local_doc_links_resolve()
    assert_effect_interpreter_docs_are_canonical()

    collaboration_rfc = read(
        "docs/architecture/rfcs/agent-im-openviking-collaboration-v0.md"
    )
    for forbidden in [
        "/Users/",
        ".local/research/",
        "source-synthesis.md",
        "minutes scopes",
        "目标群完整消息",
        "逐字稿",
    ]:
        assert forbidden not in collaboration_rfc, forbidden
    for required in [
        "The direct runtime-to-LoopX path is primary",
        "OpenViking receives scoped resources",
        "Public References",
    ]:
        assert required in collaboration_rfc, required

    for old_path, new_path in MOVED_PATHS.items():
        assert not (REPO_ROOT / old_path).exists(), old_path
        assert (REPO_ROOT / new_path).is_file(), new_path

    combined_public_indexes = "\n".join(
        [
            read("README.md"),
            read("CONTRIBUTOR_TASKS.md"),
            read("docs/README.md"),
            read("docs/archive/README.md"),
            read("docs/product/README.md"),
            read("docs/product/runtimes/codex-cli/README.md"),
            read("docs/reference/README.md"),
            read("docs/reference/protocols/README.md"),
            read("docs/research/README.md"),
            read("docs/research/long-horizon-agent-benchmarks/README.md"),
            read("docs/showcases/README.md"),
        ]
    )
    for old_path in MOVED_PATHS:
        assert old_path not in combined_public_indexes, old_path
    for new_path in MOVED_PATHS.values():
        basename = Path(new_path).name
        assert (
            new_path in combined_public_indexes
            or basename in combined_public_indexes
            or new_path.startswith("docs/archive/")
        ), new_path

    for required in [
        "Do not append a follow-up goal-level `surface_only` sync",
        "--delivery-outcome outcome_progress",
    ]:
        assert required in compact_project_agent_contract, required

    for required in [
        "The best first-run experience is one TUI setup message",
        "Session-Attached Automation",
        "Headless Disabled Boundary",
    ]:
        assert required in compact_codex_cli_tui_loop, required

    for required in [
        "A later `surface_only` project-level sync will become the latest non-agent-lane run",
        "agent_lane_recommendation",
    ]:
        assert required in compact_status_contract, required

    for required in [
        "Start From A Clean Workspace",
        "loopx-auto-research-demo",
        "auto-research demo-e2e",
        "auto-research demo-supervisor",
        "auto-research worker-loop",
        "research-curator",
        "hypothesis-proposer",
        "research-executor",
        "evaluator-promoter",
        "tmux attach -t loopx-auto-research",
        "tmux kill-session -t loopx-auto-research",
        "not a leader agent",
    ]:
        assert required in compact_auto_research_command_path, required

    multi_agent_product_recipe = read("docs/guides/multi-agent-product-recipe.md")
    compact_multi_agent_product_recipe = compact(multi_agent_product_recipe)
    for required in [
        "Multi-Agent Product Recipe",
        "Product preset",
        "Multi-agent kernel",
        "role list",
        "agent scope",
        "worker-local skill snippet",
        "handoff/todo hints",
        "One-Command Launch",
        "Attach, Stop, Retry",
        "Auto-research should stay a reference preset, not the kernel",
    ]:
        assert required in compact_multi_agent_product_recipe, required

    print("docs-governance-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
