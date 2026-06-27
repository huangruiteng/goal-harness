#!/usr/bin/env python3
"""Validate the public rollout projection bundle used by frontstage."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT
    / "examples"
    / "fixtures"
    / "frontstage-rollout-projections.public.json"
)

PRIVATE_PATTERNS = [
    re.compile(r"/" + r"Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/" + "private/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b" + "depart" + "ment" + r"\b", re.IGNORECASE),
    re.compile("\u90e8\u95e8"),
    re.compile("\u6c47\u62a5"),
]

REQUIRED_BOUNDARY_FALSE = {
    "raw_task_text_recorded",
    "raw_logs_recorded",
    "raw_trajectory_recorded",
    "raw_session_transcript_recorded",
    "credential_values_recorded",
    "absolute_paths_recorded",
    "private_material_body_recorded",
}

REQUIRED_MODEL_SECTIONS = {"metrics", "stages", "lanes", "nodes", "edges"}
REQUIRED_RICH_SECTIONS = {
    "timeline",
    "rollout_sequence",
    "mapping_layers",
    "flow_signals",
    "relationship_summaries",
    "attention_hotspots",
}
ALLOWED_CONFIDENCE = {
    "observed",
    "observed_public_metadata",
    "inferred_high",
}


def assert_public_safe(text: str) -> None:
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise AssertionError(f"fixture matched private pattern {pattern.pattern!r}")


def main() -> int:
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert_public_safe(fixture_text)
    payload = json.loads(fixture_text)

    assert payload["schema_version"] == "frontstage_rollout_projection_bundle_v0", payload
    assert payload["truth_contract"]["projection_is_writable"] is False, payload
    assert payload["truth_contract"]["write_authority"] == "none", payload
    assert "public GitHub PR metadata" in payload["truth_contract"]["evidence_floor"], payload
    for key in REQUIRED_BOUNDARY_FALSE:
        assert payload["public_boundary"].get(key) is False, (key, payload["public_boundary"])

    model = payload["projection_model"]
    assert model["schema_version"] == "frontstage_rollout_projection_model_v0", model
    assert set(model["required_sections"]) == REQUIRED_MODEL_SECTIONS, model
    assert set(model["optional_rich_sections"]) == REQUIRED_RICH_SECTIONS, model
    assert "frontstage renderer consumes this model" in model["description"], model

    projections = payload["projections"]
    assert len(projections) == 1, projections
    projection = projections[0]
    assert projection["projection_id"] == "overnight_pr_batch_20260627", projection
    assert projection["projection_kind"] == "pr_batch_rollout", projection
    assert projection["source_contract"]["sample_window"] == "#746-#775", projection
    assert projection["source_contract"]["anchor_node_id"] == "pr_674", projection
    assert projection["scene"]["confidence"] == "observed_public_metadata", projection

    metrics = {metric["metric_id"]: metric for metric in projection["metrics"]}
    assert metrics["public_sample"]["value"] == "30 PRs", metrics
    assert metrics["merged"]["value"] == "29", metrics
    assert metrics["open_review"]["value"] == "1", metrics
    assert metrics["review_edges"]["value"] == "10", metrics

    stages = projection["stages"]
    assert len(stages) >= 6, stages
    assert sum(1 for stage in stages if stage["current"]) == 1, stages
    for stage in stages:
        assert stage["confidence"] in ALLOWED_CONFIDENCE, stage
        assert stage["stage_id"], stage
        assert stage["actor_scope"], stage

    nodes = projection["nodes"]
    node_ids = [node["node_id"] for node in nodes]
    assert len(node_ids) == len(set(node_ids)), node_ids
    node_by_id = {node["node_id"]: node for node in nodes}
    pr_batch_nodes = [
        node
        for node in nodes
        if re.fullmatch(r"pr_7(?:4[6-9]|5[0-9]|6[0-9]|7[0-5])", node["node_id"])
    ]
    assert len(pr_batch_nodes) == 30, pr_batch_nodes
    assert sum(1 for node in pr_batch_nodes if node["state"] == "merged") == 29, pr_batch_nodes
    assert sum(1 for node in pr_batch_nodes if node["state"] == "open") == 0, pr_batch_nodes
    assert sum(1 for node in pr_batch_nodes if node["state"] == "closed") == 1, pr_batch_nodes
    for node in nodes:
        assert node["confidence"] in ALLOWED_CONFIDENCE, node
        assert node["url"].startswith("https://github.com/huangruiteng/loopx/pull/"), node
    for node in pr_batch_nodes:
        assert node["started_at"].startswith("2026-06-27T"), node
        assert node["completed_at"].startswith("2026-06-27T"), node
        assert node["occurred_at"] == node["started_at"], node
        assert node["display_time"], node
        assert node["duration_label"], node
        assert node["timezone"] == "Asia/Shanghai", node

    lanes = projection["lanes"]
    lane_ids = {lane["lane_id"] for lane in lanes}
    assert {
        "kernel_runtime",
        "product_frontstage",
        "benchmark_interface",
        "public_docs_showcase",
        "open_review",
    } <= lane_ids, lanes
    for lane in lanes:
        assert lane["node_ids"], lane
        for node_id in lane["node_ids"]:
            assert node_id in node_by_id, (lane["lane_id"], node_id)

    edges = projection["edges"]
    assert len(edges) == 10, edges
    assert any(edge["from_node_id"] == "pr_674" for edge in edges), edges
    assert any(edge["edge_kind"] == "review_revert" for edge in edges), edges
    assert any(edge["edge_kind"] == "review_command_followup" for edge in edges), edges
    for edge in edges:
        assert edge["from_node_id"] in node_by_id, edge
        assert edge["to_node_id"] in node_by_id, edge
        assert edge["confidence"] in ALLOWED_CONFIDENCE, edge
        assert edge.get("label"), edge

    edge_by_id = {edge["edge_id"]: edge for edge in edges}
    mapping_layers = projection["mapping_layers"]
    assert len(mapping_layers) >= 5, mapping_layers
    assert {layer["layer_id"] for layer in mapping_layers} >= {
        "source_intake",
        "state_projection",
        "lane_routing",
        "edge_reasoning",
        "operator_readout",
    }, mapping_layers
    for layer in mapping_layers:
        assert layer["input"], layer
        assert layer["output"], layer
        for node_id in layer["node_ids"]:
            assert node_id in node_by_id, (layer["layer_id"], node_id)
        for edge_id in layer["edge_ids"]:
            assert edge_id in edge_by_id, (layer["layer_id"], edge_id)

    flow_signals = projection["flow_signals"]
    assert len(flow_signals) >= 4, flow_signals
    assert {signal["signal_id"] for signal in flow_signals} >= {
        "throughput",
        "active_review",
        "cross_lane_edges",
        "reusable_model",
    }, flow_signals
    for signal in flow_signals:
        for node_id in signal["source_node_ids"]:
            assert node_id in node_by_id, (signal["signal_id"], node_id)

    relationship_summaries = projection["relationship_summaries"]
    assert len(relationship_summaries) >= 5, relationship_summaries
    assert any(summary["kind"] == "runtime_followup" for summary in relationship_summaries), relationship_summaries

    hotspots = projection["attention_hotspots"]
    assert len(hotspots) >= 3, hotspots
    for hotspot in hotspots:
        assert hotspot["severity"] in {"low", "medium", "high"}, hotspot
        for node_id in hotspot["node_ids"]:
            assert node_id in node_by_id, (hotspot["hotspot_id"], node_id)
        for edge_id in hotspot["edge_ids"]:
            assert edge_id in edge_by_id, (hotspot["hotspot_id"], edge_id)

    timeline = projection["timeline"]
    assert timeline["axis_kind"] == "wall_clock", timeline
    assert timeline["unit_label"] == "PR nodes", timeline
    assert timeline["timezone"] == "Asia/Shanghai", timeline
    assert timeline["start_at"] == "2026-06-27T13:24:51+08:00", timeline
    assert timeline["end_at"] == "2026-06-27T21:30:06+08:00", timeline
    assert "13:24-21:30 Asia/Shanghai" in timeline["window_label"], timeline
    assert "node.started_at" in timeline["time_basis"], timeline
    assert len(timeline["ticks"]) >= 8, timeline
    assert len(timeline["item_node_ids"]) == 30, timeline
    assert timeline["item_node_ids"][0] == "pr_746", timeline
    assert timeline["item_node_ids"][-1] == "pr_775", timeline
    for node_id in timeline["item_node_ids"]:
        assert node_id in node_by_id, node_id

    sequence = projection["rollout_sequence"]
    assert sequence["sequence_id"] == "overnight_requirement_rollout_spine", sequence
    assert "One demand unlocks the next" in sequence["description"], sequence
    units = sequence["units"]
    assert len(units) >= 7, units
    assert [unit["order"] for unit in units] == list(range(1, len(units) + 1)), units
    unit_ids = {unit["unit_id"] for unit in units}
    assert "req_frontstage_projection" in unit_ids, unit_ids
    assert "req_monitor_scheduler_due_work" in unit_ids, unit_ids
    assert any(unit["state"] == "open" for unit in units), units
    assert any(unit["state"] == "merged" for unit in units), units
    for unit in units:
        assert unit["requirement"], unit
        assert unit["triggered_by"], unit
        assert unit["outcome"], unit
        assert unit["lane_id"] in lane_ids, unit
        assert unit["stage_steps"], unit
        for node_id in unit["node_ids"]:
            assert node_id in node_by_id, (unit["unit_id"], node_id)
        for unlock in unit["unlocks"]:
            assert unlock in unit_ids, (unit["unit_id"], unlock)
        for step in unit["stage_steps"]:
            assert step["status"] in {"done", "active", "queued", "planned"}, step
            for node_id in step["node_ids"]:
                assert node_id in node_by_id, (unit["unit_id"], step["step_id"], node_id)

    acceptance = set(projection["frontend_acceptance"]["must_render"])
    assert {
        "generic projection model contract",
        "30 PR relationship mesh",
        "timeline axis",
        "wall-clock timeline ticks",
        "node time and duration hover details",
        "hoverable node and edge details",
        "sequential requirement rollout",
        "rollout requirement spine",
        "projection capability map",
        "30 public PR nodes",
        "single-agent stage flow",
        "multi-agent lane graph",
        "review edge mesh",
        "flow signals",
        "attention hotspots",
        "public evidence boundary",
    } <= acceptance, acceptance

    planned = {item["projection_id"]: item for item in payload.get("planned_projections", [])}
    assert planned["loopx_overall_iteration"]["status"] == "planned", planned

    print("frontstage-rollout-projections fixture smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
