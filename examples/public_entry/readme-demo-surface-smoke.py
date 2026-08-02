#!/usr/bin/env python3
"""Validate the public README and cross-runtime demo surface."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def compact(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    readme = read("README.md")
    readme_zh = read("README.zh-CN.md")
    demo = read("docs/product/cross-runtime-impl-review-demo.md")
    product_index = read("docs/product/README.md")
    getting_started = read("docs/guides/getting-started.md")
    compact_readme = compact(readme)
    compact_demo = compact(demo)

    for required in [
        '<div align="center">',
        "docs/assets/loopx-social-preview.png",
        "LoopX loop engineering social preview banner",
        "Loop engineering for long-running AI agents and peer agent teams.",
        "A lightweight state kernel and agent-agnostic local control plane for",
        "Keep objectives, gates, todos, evidence, quota, and handoffs stable",
        "## Why LoopX",
        "objective / issue / project",
        "LoopX state: objective + gates + todos + scope + evidence + quota",
        "## Try LoopX",
        "### Start From Your Agent",
        "Codex App",
        "Codex CLI",
        "Claude Code",
        "Cursor, shell, or custom runner",
        "Claude implements and Codex reviews",
        "docs/product/cross-runtime-impl-review-demo.md",
        "## Advanced Paths",
        "200+ hours of elapsed loop lifetime",
        "200+ hour public contribution arc",
        "200+ hour owner-run experiment arc",
        "not 200 hours of continuous model execution",
        "docs/assets/long-running-loop-openviking-trajectory.png",
        "docs/assets/long-running-loop-ml-experiment-trajectory.png",
        "### Presets and Auto Research",
        "### Review Agent Work",
        "### App and Projection Paths",
        '<a id="how-it-works"></a>',
        '<a id="quick-start"></a>',
        '<a id="see-it-in-action"></a>',
        '<a id="capability-surface"></a>',
        '<a id="community--feedback"></a>',
        "The v0.4.x line is an early but usable local control plane",
        "docs/assets/loopx-lark-developer-group.png",
        "docs/assets/loopx-wechat-contact.png",
        "WeChat: <code>huangrt00</code>",
        "loopx configure-goal --goal-id <goal-id>",
        "loopx preset show daily-triage",
    ]:
        assert required in readme, required

    for required in [
        '<a id="快速开始"></a>',
        '<a id="看几个例子"></a>',
        "200+ 小时自然时长",
        "超过 200 小时的公开贡献轨迹",
        "超过 200 小时的 owner-run 实验轨迹",
        "不等于 200 小时连续模型执行",
        "`0.4.x` 已经是一套可用、但仍处于早期的长程 Agent 本地控制面",
        "docs/assets/loopx-lark-developer-group.png",
        "docs/assets/loopx-wechat-contact.png",
        "微信：<code>huangrt00</code>",
        "loopx configure-goal --goal-id <goal-id>",
        "loopx preset show daily-triage",
    ]:
        assert required in readme_zh, required

    first_screen = readme.split("## Why LoopX", 1)[0]
    assert "docs/assets/loopx-logo.png" not in first_screen

    for required in [
        "`$loopx <complex task>`",
        "`loopx todo claim`",
        "`loopx review-packet`",
    ]:
        assert required in compact_readme, required

    for required in [
        "# Cross-Runtime Implement/Review Demo",
        "Claude Code owns an implementation todo",
        "Codex owns a review todo",
        "LoopX owns todo claims, gates, evidence, quota, and the next handoff",
        "loopx todo add --goal-id <goal> --role agent",
        "loopx demo impl-review --preset claude-codex --dry-run",
        "loopx --format json quota should-run --goal-id <goal> --agent-id claude-code-impl",
        "loopx review-packet --goal-id <goal>",
        "cross_runtime_impl_review_demo_packet_v0",
        "Review Verdict Contract",
        "Forbidden evidence",
        "raw Claude or Codex transcripts",
    ]:
        assert required in demo, required

    for required in [
        "verdict",
        "blockers",
        "suggestions",
        "verifier",
        "handoff",
        "docs plus fixture validation",
    ]:
        assert required in compact_demo, required

    assert "Cross-runtime implement/review demo" in product_index
    assert "cross-runtime-impl-review-demo.md" in product_index
    assert "### Recover History Index Collisions" in getting_started
    assert "history rebuild-index-collisions" in getting_started
    assert "--review-plan-json reviewed-plan.json" in getting_started

    print("readme-demo-surface-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
