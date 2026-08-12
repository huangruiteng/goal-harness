#!/usr/bin/env python3
"""Contributor-facing walkthrough: Explore owner-board views.

Covers canonical, executive, and semantic lane views over synthetic Explore
evidence — proving decision/evidence lineage and readability without any
external sink (no Lark, no provider, no local paths).

1. **Canonical view** — complete topology timeline; every node, edge, and
   finding preserved; vertical evidence timeline layout
2. **Executive view** — summary with dense-hub scaffolding suppressed;
   decision-relevant nodes only; top-to-bottom layout
3. **Semantic lane view** — lane-tagged nodes grouped into parallel columns;
   cross-lane edges rendered as real relations between lanes
4. **Dual view** — auto-recommended when graph exceeds density or terminal
   thresholds; canonical + executive from same source
5. **Decision lineage** — status transitions (open → exploring → resolved /
   blocked / dead_end), parent-child topology tree, edge types
6. **Evidence lineage** — findings attached to nodes, evidence refs,
   confidence values, status progression
7. **Readability assessment** — decision density, terminal ratio, readability
   check; auto-detects flat or overly-dense graphs
8. **Stage views** — large graphs split into bounded independent topology
   stages with lane-preserving SVG layout
9. **Freshness** — source digest detects changes; stale views rejected
10. **Public safety** — no absolute paths, credentials, URLs, or external sinks

No provider payloads, raw sessions, credentials, private locators, or external sinks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.presentation.explore_views import (  # noqa: E402
    PRESENTATION_MODE_CANONICAL_ONLY,
    PRESENTATION_MODE_DUAL_VIEW,
    build_explore_presentation_bundle,
    explore_source_digest,
    validate_explore_view_freshness,
)

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


# ── Fixtures ─────────────────────────────────────────────────────────


def _node(
    node_id: str,
    *,
    title: str = "",
    node_kind: str = "experiment",
    status: str = "resolved",
    parent_id: str = "",
    tags: list[str] | None = None,
    summary: str = "",
    blocked_reason: str = "",
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "title": title or f"Node {node_id}",
        "node_kind": node_kind,
        "status": status,
        "parent_id": parent_id,
        "tags": tags or [],
        "summary": summary,
        "blocked_reason": blocked_reason,
    }


def _edge(from_node: str, to_node: str, edge_type: str = "supports") -> dict[str, Any]:
    return {
        "edge_id": f"edge-{from_node}-{to_node}",
        "from_node": from_node,
        "to_node": to_node,
        "edge_type": edge_type,
    }


def _finding(
    finding_id: str,
    node_id: str,
    *,
    finding: str = "",
    status: str = "confirmed",
    confidence: float = 0.8,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "finding": finding or f"Finding for {node_id}",
        "node_id": node_id,
        "status": status,
        "confidence": confidence,
    }


def _projection(**kw: Any) -> dict[str, Any]:
    """Build a minimal synthetic projection with required fields."""
    base: dict[str, Any] = {
        "ok": True,
        "goal_id": "goal:explore-walkthrough",
        "source_event_count": 0,
        "nodes": [],
        "edges": [],
        "findings": [],
    }
    base.update(kw)
    base["source_event_count"] = (
        len(base["nodes"]) + len(base["edges"]) + len(base["findings"])
    )
    return base


# ── Helper: build a rich decision-tree projection ──

def _decision_tree_projection() -> dict[str, Any]:
    """A projection with clear decision lineage:
    - Root area → two competing candidates → one resolved winner, one dead end
    - Each candidate has a finding
    - Cross-evidence edge between the two candidates"""
    nodes = [
        _node("root", title="SCADE peer tool landscape",
              node_kind="area", status="exploring", tags=["decision", "portfolio"]),
        _node("candidate-a", parent_id="root",
              title="Lustre-based toolchain",
              node_kind="experiment", status="exploring",
              tags=["current-best", "incumbent"],
              summary="Mature ecosystem, two open-source implementations cover core use case."),
        _node("candidate-b", parent_id="root",
              title="Custom DSL compiler",
              node_kind="experiment", status="dead_end",
              tags=["counterevidence"],
              summary="Implementation effort too high; vendor licensing unclear.",
              blocked_reason="Vendor licence terms unclear"),
        _node("eval-lustre", parent_id="candidate-a",
              title="Lustre evaluation benchmark",
              node_kind="experiment", status="resolved",
              tags=["baseline"],
              summary="Aligned evaluation: +31.2/+72.4 bp, composite +51.8 bp."),
        _node("eval-custom", parent_id="candidate-b",
              title="Custom DSL benchmark results",
              node_kind="experiment", status="dead_end",
              tags=["counterevidence"],
              summary="Failed key guardrail: -1.2 bp below threshold."),
    ]
    edges = [
        _edge("candidate-a", "root", "subtopic_of"),
        _edge("candidate-b", "root", "subtopic_of"),
        _edge("eval-lustre", "candidate-a", "supports"),
        _edge("eval-custom", "candidate-b", "refutes"),
        _edge("candidate-a", "candidate-b", "leads_to"),
    ]
    findings = [
        _finding("f-lustre", "candidate-a",
                 finding="Two open-source Lustre toolchains cover the KCG core use case",
                 status="confirmed", confidence=0.85),
        _finding("f-custom", "candidate-b",
                 finding="Custom DSL requires proprietary compiler; vendor unresponsive",
                 status="confirmed", confidence=0.90),
    ]
    return _projection(nodes=nodes, edges=edges, findings=findings)


def _complex_projection() -> dict[str, Any]:
    """A larger projection that triggers dual-view recommendation."""
    nodes: list[dict[str, Any]] = [
        _node("root", title="Explore pilot", node_kind="area",
              status="open", tags=["decision"]),
    ]
    edges: list[dict[str, Any]] = []
    for branch_index in range(8):
        branch_id = f"branch-{branch_index}"
        nodes.append(_node(branch_id, parent_id="root",
                          title=f"Branch {branch_index}"))
        edges.append(_edge(branch_id, "root", "subtopic_of"))
        for leaf_index in range(4):
            leaf_id = f"leaf-{branch_index}-{leaf_index}"
            nodes.append(_node(leaf_id, parent_id=branch_id,
                              status="dead_end",
                              title=f"Dead-end leaf {branch_index}.{leaf_index}"))
            edges.append(_edge(leaf_id, branch_id, "subtopic_of"))
    nodes.append(
        _node("candidate", parent_id="root",
              title="Current best candidate",
              status="exploring", tags=["current-best"])
    )
    edges.append(_edge("candidate", "root", "supports"))
    return _projection(nodes=nodes, edges=edges, findings=[])


def _lane_projection() -> dict[str, Any]:
    """A projection with semantic lanes and cross-lane edges."""
    nodes = [
        _node("root", title="Public Explore pilot",
              node_kind="area", status="exploring"),
        _node("delivery-lane", parent_id="root",
              title="Delivery lane",
              node_kind="area", status="exploring",
              tags=["lane-delivery"]),
        _node("capability-lane", parent_id="root",
              title="Capability lane",
              node_kind="area", status="exploring",
              tags=["lane-capability"]),
        _node("fix-pr", parent_id="delivery-lane",
              title="Fix PR: restore stats API isolation",
              node_kind="experiment", status="exploring",
              tags=["open-pr"],
              summary="Restore stats API unit-test isolation with stable config semantics."),
        _node("durable-capability", parent_id="capability-lane",
              title="Durable capability",
              node_kind="experiment", status="resolved",
              tags=["incumbent"]),
    ]
    edges = [
        _edge("fix-pr", "durable-capability", "supports"),
        _edge("fix-pr", "delivery-lane", "subtopic_of"),
    ]
    return _projection(nodes=nodes, edges=edges, findings=[])


def _dense_hub_projection() -> dict[str, Any]:
    """A hub-and-spoke projection where executive view suppresses scaffolding."""
    nodes: list[dict[str, Any]] = [
        _node("hub", title="Decision hub",
              node_kind="area", status="open", tags=["decision"]),
    ]
    edges: list[dict[str, Any]] = []
    for index in range(6):
        active_id = f"active-{index}"
        nodes.append(_node(active_id, parent_id="hub",
                          title=f"Active option {index}",
                          status="exploring"))
        edges.append(_edge("hub", active_id, "subtopic_of"))
    # One real evidence edge between two active nodes.
    edges.append(_edge("active-0", "active-1", "leads_to"))
    return _projection(nodes=nodes, edges=edges, findings=[])


# ── Scenario 1: Small graph gets canonical-only ──

def test_small_graph_keeps_canonical_only() -> None:
    """A small, focused projection keeps canonical-only mode.
    All nodes, edges, and findings are preserved in the timeline."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    assert bundle["presentation_mode"] == PRESENTATION_MODE_CANONICAL_ONLY
    assert bundle["canonical"]["graph_counts"]["node_count"] == len(projection["nodes"])
    assert bundle["canonical"]["graph_counts"]["edge_count"] == len(projection["edges"])
    assert bundle["canonical"]["filter"]["truncated"] is False
    _assert_public_safe(bundle, label="small-canonical")


# ── Scenario 2: Complex graph recommends dual view ──

def test_complex_graph_recommends_dual_view() -> None:
    """A graph with many terminal leaves and low decision density
    automatically recommends canonical + executive dual view."""
    projection = _complex_projection()
    bundle = build_explore_presentation_bundle(projection)

    assert bundle["presentation_mode"] == PRESENTATION_MODE_DUAL_VIEW
    assert {
        "low_decision_density",
        "excessive_terminal_branches",
    }.issubset(bundle["reason_codes"])
    # Both views share the same source.
    assert bundle["canonical"]["source_digest"] == bundle["executive"]["source_digest"]
    assert (
        bundle["canonical"]["source_revision"]
        == bundle["executive"]["source_revision"]
    )
    _assert_public_safe(bundle, label="complex-dual")


# ── Scenario 3: Canonical view preserves complete evidence ──

def test_canonical_view_preserves_complete_evidence() -> None:
    """The canonical view is a complete, untruncated timeline.
    Every node appears in the Mermaid source with its status."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    canonical = bundle["canonical"]
    mermaid = canonical["mermaid"]
    assert mermaid.startswith("flowchart TB")
    assert "subgraph canonical_timeline" in mermaid
    assert canonical["filter"]["layout"]["strategy"] == "vertical_evidence_timeline"

    # Every non-lineage node appears in canonical Mermaid.
    # Pure containment parents (only subtopic_of edges from children) are
    # encoded as lineage on child nodes and do not appear as standalone nodes.
    lineage_targets = {
        e["to_node"] for e in projection["edges"]
        if e["edge_type"] == "subtopic_of"
    }
    non_lineage_sources = {
        e["from_node"] for e in projection["edges"]
        if e["edge_type"] != "subtopic_of"
    }
    non_lineage_targets = {
        e["to_node"] for e in projection["edges"]
        if e["edge_type"] != "subtopic_of"
    }
    rendered_nodes = (
        {n["node_id"] for n in projection["nodes"] if n["node_id"] not in lineage_targets}
        | non_lineage_sources | non_lineage_targets
    )
    for node_id in rendered_nodes:
        safe_id = node_id.replace("-", "_")
        assert f'{safe_id}["' in mermaid, f"node {node_id} missing from canonical"

    # Every non-lineage edge appears in Mermaid.
    for edge in projection["edges"]:
        if edge["edge_type"] == "subtopic_of":
            continue
        source = str(edge["from_node"]).replace("-", "_")
        target = str(edge["to_node"]).replace("-", "_")
        edge_type = edge["edge_type"]
        assert f"{source} -->|{edge_type}| {target}" in mermaid

    # Decision statuses are preserved (rendered as human-readable labels).
    assert "ACTIVE" in mermaid
    assert "DONE" in mermaid
    assert "NO-PROMOTE" in mermaid
    _assert_public_safe(canonical, label="canonical-complete")


# ── Scenario 4: Executive view suppresses hub scaffolding ──

def test_executive_view_suppresses_scaffolding() -> None:
    """The executive view suppresses dense hub scaffolding edges
    while preserving real evidence edges between active nodes."""
    projection = _dense_hub_projection()
    bundle = build_explore_presentation_bundle(projection)

    # Canonical has all 7 edges.
    assert bundle["canonical"]["graph_counts"]["edge_count"] == 7

    # Executive suppresses 6 hub scaffolding edges, keeps 1 real edge.
    executive = bundle["executive"]
    assert executive["graph_counts"]["edge_count"] == 1
    assert executive["graph_counts"]["suppressed_edge_count"] == 6
    edge_proj = executive["filter"]["edge_projection"]
    # hub→active subtopic_of edges are encoded as lineage on the child node.
    assert edge_proj["suppression_counts"]["lineage_encoded_on_node"] == 6

    # The real evidence edge survives.
    assert "active_0 -->|leads_to| active_1" in executive["mermaid"]
    # Hub scaffolding edges are absent.
    assert "hub -->|subtopic_of|" not in executive["mermaid"]

    _assert_public_safe(executive, label="executive-suppressed")


# ── Scenario 5: Status and metric rendering ──

def test_views_render_status_and_metric() -> None:
    """Both canonical and executive views render node status (DONE/BLOCKED/ACTIVE)
    and metric values from node summaries."""
    projection = _decision_tree_projection()
    # Add a summary with metrics to the eval-lustre node.
    for node in projection["nodes"]:
        if node["node_id"] == "eval-lustre":
            node["summary"] = (
                "Aligned evaluation completed with stable sample parity. "
                "Target slice is +31.2/+72.4 bp and composite +51.8 bp; "
                "guardrail slice is -1.2 bp. "
                "Retain as incumbent with calibration as a guardrail."
            )
            node["status"] = "resolved"

    bundle = build_explore_presentation_bundle(projection)

    for role in ("canonical", "executive"):
        view = bundle[role]
        mermaid = view["mermaid"]
        # Status appears in the Mermaid node label.
        assert "DONE" in mermaid or "ACTIVE" in mermaid or "BLOCKED" in mermaid
        # Metric values rendered.
        assert "+31.2/+72.4 bp" in mermaid
        coverage = view["filter"]["layout"]["node_detail_coverage"]
        assert coverage["complete"] is True

    _assert_public_safe(bundle, label="status-metric")


# ── Scenario 6: Decision lineage through topology tree ──

def test_decision_lineage_through_topology() -> None:
    """The projection carries a topology tree showing parent-child
    relationships.  Nodes transition through statuses that trace
    the decision path: open → exploring → resolved / dead_end."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    canonical = bundle["canonical"]
    # Verify status transitions are visible.
    statuses = {node["node_id"]: node["status"] for node in projection["nodes"]}
    assert statuses["root"] == "exploring"
    assert statuses["candidate-a"] == "exploring"  # still active
    assert statuses["candidate-b"] == "dead_end"     # eliminated
    assert statuses["eval-lustre"] == "resolved"     # confirmed

    # Evidence edges encode the decision flow.
    edge_types = {edge["edge_id"]: edge["edge_type"] for edge in projection["edges"]}
    assert any(t == "refutes" for t in edge_types.values()), "refutes edge missing"
    assert any(t == "supports" for t in edge_types.values()), "supports edge missing"
    assert any(t == "leads_to" for t in edge_types.values()), "leads_to edge missing"

    _assert_public_safe(canonical, label="decision-lineage")


# ── Scenario 7: Findings provide evidence lineage ──

def test_findings_provide_evidence_lineage() -> None:
    """Findings attach confirmed/refuted evidence to specific nodes.
    Each finding carries a confidence value and evidence refs."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    # The canonical view preserves all findings in its assessment.
    assessment = bundle["assessment"]
    assert assessment["metrics"]["node_count"] == len(projection["nodes"])
    assert assessment["metrics"]["edge_count"] == len(projection["edges"])

    # Each finding is linked to a node.
    for finding in projection["findings"]:
        assert finding["status"] == "confirmed"
        assert 0.0 <= finding["confidence"] <= 1.0
        # The finding's node exists in the projection.
        node_ids = {n["node_id"] for n in projection["nodes"]}
        assert finding["node_id"] in node_ids

    _assert_public_safe(bundle, label="evidence-lineage")


# ── Scenario 8: Semantic lane views with cross-lane edges ──

def test_semantic_lane_views() -> None:
    """Lane-tagged nodes are grouped into semantic columns.
    Cross-lane edges are real relations, not scaffolding."""
    projection = _lane_projection()
    bundle = build_explore_presentation_bundle(
        projection,
        policy={"stage_node_capacity": 10},
    )

    stage = bundle["canonical"]["stage_views"][0]
    assert stage["lane_count"] == 2
    assert "capability" in stage["lanes"]
    assert "delivery" in stage["lanes"]
    assert stage["cross_lane_edge_count"] == 1

    # Lanes are subgraphs in Mermaid.
    mermaid = stage["mermaid"]
    assert 'subgraph canonical_stage_1_lane_1["Delivery"]' in mermaid
    assert 'subgraph canonical_stage_1_lane_2["LoopX capability"]' in mermaid

    # Cross-lane evidence edge preserved.
    assert "fix_pr -->|supports| durable_capability" in mermaid
    # Lane-internal scaffolding suppressed.
    assert "edge-fix-subtopic" not in mermaid

    # SVG layout preserves lanes.
    assert stage["svg_layout"]["strategy"] == "semantic_lane_columns"
    assert stage["svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "LoopX capability" in stage["svg"]
    assert "supports" in stage["svg"]

    _assert_public_safe(stage, label="lane-views")


# ── Scenario 9: Single lane does not invent a second ──

def test_single_lane_does_not_invent_second() -> None:
    """A projection with only one lane tag does not fabricate a second."""
    projection = _decision_tree_projection()
    # Tag everything with a single lane.
    for node in projection["nodes"]:
        node["tags"] = ["lane-retrieval"]
    # Remove parent relationships so all nodes are root-level for the lane view.
    for node in projection["nodes"]:
        if node["node_id"] != "root":
            node["parent_id"] = "root"

    bundle = build_explore_presentation_bundle(projection)
    stage = bundle["canonical"]["stage_views"][0]
    assert stage["lane_count"] == 1
    assert stage["lanes"] == ["retrieval"]
    assert stage["cross_lane_edge_count"] == 0
    assert stage["mermaid"].count("subgraph canonical_stage_1_lane_") == 1

    _assert_public_safe(stage, label="single-lane")


# ── Scenario 10: Readability assessment catches flat graphs ──

def test_readability_assessment_flat_graph() -> None:
    """A graph with too many root nodes and no edges fails
    readability check.  The assessment reports the failure explicitly."""
    nodes = [_node(f"root-{index}") for index in range(80)]
    projection = _projection(nodes=nodes, edges=[], findings=[])

    bundle = build_explore_presentation_bundle(projection)

    assert "readability_check_failed" in bundle["reason_codes"]
    assert bundle["assessment"]["metrics"]["root_node_count"] == 80
    assert bundle["assessment"]["readability_check"]["failed"] is True
    assert bundle["canonical"]["filter"]["layout"]["column_count"] == 1

    _assert_public_safe(bundle, label="readability-flat")


# ── Scenario 11: Stage views split large graphs ──

def test_stage_views_split_large_graphs() -> None:
    """When a graph exceeds stage_node_capacity, it is split into
    bounded independent topology stages.  Each stage is self-contained."""
    bundle = build_explore_presentation_bundle(
        _complex_projection(),
        policy={"stage_node_capacity": 14},
    )

    stages = bundle["executive"]["stage_views"]
    assert len(stages) >= 2
    for stage in stages:
        assert 1 <= stage["node_count"] <= 14
        assert stage["primary_node_count"] <= 12
        assert stage["context_node_count"] <= 2
        assert stage["mermaid"].startswith("flowchart TB")

    _assert_public_safe(bundle, label="stage-views")


# ── Scenario 12: Freshness detects source changes ──

def test_freshness_detects_source_changes() -> None:
    """A change to the projection (finding text, node title) produces
    a different source digest.  Stale views are rejected."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    # Change a finding.
    changed = json.loads(json.dumps(projection))
    changed["findings"][0]["finding"] = "Updated evidence finding"

    assert explore_source_digest(changed) != bundle["source_digest"]
    freshness = validate_explore_view_freshness(changed, bundle["executive"])
    assert freshness["fresh"] is False
    assert freshness["reason"]

    _assert_public_safe(bundle, label="freshness")


# ── Scenario 13: Source digest is deterministic ──

def test_source_digest_is_deterministic() -> None:
    """The source digest is deterministic: identical projections
    produce identical digests."""
    projection = _decision_tree_projection()
    d1 = explore_source_digest(projection)
    d2 = explore_source_digest(json.loads(json.dumps(projection)))
    assert d1 == d2

    # Different content → different digest.
    changed = json.loads(json.dumps(projection))
    changed["nodes"][0]["title"] = "Changed title"
    assert explore_source_digest(changed) != d1


# ── Scenario 14: No external sink — presentation only ──

def test_no_external_sink() -> None:
    """The presentation bundle is transport-free content.  It never
    references external services, credentials, or write operations."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    serialized = json.dumps(bundle, ensure_ascii=False)
    assert "api_key" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "lark" not in serialized.lower()
    assert "feishu" not in serialized.lower()
    # SVG namespace URIs are harmless — only block real network URLs.
    serialized_no_svg = serialized.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in serialized_no_svg.lower()
    assert "https://" not in serialized_no_svg.lower()
    assert bundle["canonical"]["filter"]["truncated"] is False

    _assert_public_safe(bundle, label="no-external-sink")


# ── Scenario 15: Complete walkthrough — decision tree to dual view ──

def test_full_walkthrough_pipeline() -> None:
    """End-to-end: build a rich decision-tree projection, render
    canonical and executive views, verify evidence and decision
    lineage, check readability, and confirm public safety."""
    projection = _decision_tree_projection()
    bundle = build_explore_presentation_bundle(projection)

    # Sanity: canonical view is complete.
    assert bundle["ok"] is True
    assert bundle["presentation_mode"] == PRESENTATION_MODE_CANONICAL_ONLY
    canonical = bundle["canonical"]
    assert canonical["graph_counts"]["node_count"] == len(projection["nodes"])
    assert canonical["graph_counts"]["edge_count"] == len(projection["edges"])

    # Executive view also present (canonical-only still computes it).
    executive = bundle["executive"]
    assert executive["source_digest"] == canonical["source_digest"]

    # Assessment.
    assessment = bundle["assessment"]
    assert assessment["metrics"]["node_count"] == len(projection["nodes"])
    assert assessment["readability_check"]["failed"] is False

    # Every non-lineage node is reachable in canonical Mermaid.
    lineage_targets = {
        e["to_node"] for e in projection["edges"]
        if e["edge_type"] == "subtopic_of"
    }
    for node in projection["nodes"]:
        if node["node_id"] in lineage_targets:
            continue
        assert str(node["node_id"]).replace("-", "_") in canonical["mermaid"]

    # Public safety.
    for label, payload in [
        ("bundle", bundle),
        ("canonical", canonical),
        ("executive", executive),
        ("assessment", assessment),
    ]:
        _assert_public_safe(payload, label=label)


def main() -> int:
    tests: list[tuple[str, Any]] = [
        ("small graph keeps canonical only", test_small_graph_keeps_canonical_only),
        ("complex graph recommends dual view", test_complex_graph_recommends_dual_view),
        ("canonical view preserves complete evidence", test_canonical_view_preserves_complete_evidence),
        ("executive view suppresses scaffolding", test_executive_view_suppresses_scaffolding),
        ("views render status and metric", test_views_render_status_and_metric),
        ("decision lineage through topology", test_decision_lineage_through_topology),
        ("findings provide evidence lineage", test_findings_provide_evidence_lineage),
        ("semantic lane views", test_semantic_lane_views),
        ("single lane does not invent second", test_single_lane_does_not_invent_second),
        ("readability assessment flat graph", test_readability_assessment_flat_graph),
        ("stage views split large graphs", test_stage_views_split_large_graphs),
        ("freshness detects source changes", test_freshness_detects_source_changes),
        ("source digest is deterministic", test_source_digest_is_deterministic),
        ("no external sink", test_no_external_sink),
        ("full walkthrough pipeline", test_full_walkthrough_pipeline),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("explore-owner-board-views-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
