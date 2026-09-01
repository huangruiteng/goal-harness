"""Offline smoke for the public-safe Codex provider routing extension."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

cli = importlib.import_module("loopx_codex_provider_routing.cli")
contract = importlib.import_module("loopx_codex_provider_routing.contract")
_run_request = cli._run_request
REQUEST_SCHEMA_VERSION = contract.REQUEST_SCHEMA_VERSION
build_upgrade_plan = contract.build_upgrade_plan
compile_catalog = contract.compile_catalog
qualify_snapshot = contract.qualify_snapshot


def _source() -> dict:
    return json.loads((PACKAGE_ROOT / "examples" / "request.json").read_text())[
        "source"
    ]


def _valid_snapshot() -> dict:
    return {
        "visible_models": [
            "auto/gpt-5.6-sol",
            "codex-a/gpt-5.6-sol",
            "codex-b/gpt-5.6-sol",
            "gpt-5.6-luna",
            "ark/deepseek-v4-flash",
        ],
        "hidden_models": ["gpt-5.6-sol"],
        "input_modalities": {
            "auto/gpt-5.6-sol": ["text", "image"],
            "codex-a/gpt-5.6-sol": ["text", "image"],
            "codex-b/gpt-5.6-sol": ["text", "image"],
            "gpt-5.6-luna": ["text", "image"],
            "ark/deepseek-v4-flash": ["text"],
        },
        "fast_models": [
            "auto/gpt-5.6-sol",
            "codex-a/gpt-5.6-sol",
            "codex-b/gpt-5.6-sol",
            "gpt-5.6-luna",
        ],
        "default_service_tier": "default",
        "endpoint_host": "127.0.0.1",
        "affinity_policy": "hint_revalidated_per_attempt",
        "route_traversal": {
            "auto/gpt-5.6-sol": {
                "entrypoint": "affinity_then_first",
                "ordered_candidates": ["codex-a", "codex-b", "ark-text"],
                "fallback_tail": ["ark-text"],
                "max_cycles": 1,
            },
            "codex-a/gpt-5.6-sol": {
                "entrypoint": "codex-a",
                "ordered_candidates": ["codex-a", "codex-b", "ark-text"],
                "fallback_tail": ["ark-text"],
                "max_cycles": 1,
            },
            "codex-b/gpt-5.6-sol": {
                "entrypoint": "codex-b",
                "ordered_candidates": ["codex-b", "codex-a", "ark-text"],
                "fallback_tail": ["ark-text"],
                "max_cycles": 1,
            },
            "gpt-5.6-luna": {
                "entrypoint": "affinity_then_first",
                "ordered_candidates": ["codex-a", "codex-b"],
                "fallback_tail": [],
                "max_cycles": 1,
            },
        },
        "settings_revision_durable": True,
        "turn_revision_matches": True,
        "commit_barrier": "before_first_visible_output_or_tool_call",
    }


def expect_error(action, message: str) -> None:
    try:
        action()
    except (TypeError, ValueError):
        return
    raise AssertionError(message)


def main() -> int:
    catalog = compile_catalog(_source())
    assert catalog["credential_free"] is True
    auto = next(
        route for route in catalog["routes"] if route["slug"].startswith("auto/")
    )
    assert auto["eligible_candidates"]["image"] == ["codex-a", "codex-b"]
    assert auto["eligible_candidates"]["text"] == ["codex-a", "codex-b", "ark-text"]
    assert auto["fast_candidates"] == ["codex-a", "codex-b"]
    assert auto["routing_policy"]["session_affinity"] == "hint_revalidated_per_attempt"
    assert auto["ring_id"] == "codex-accounts"
    assert auto["entrypoint"] == "affinity_then_first"
    assert auto["routing_policy"]["max_cycles"] == 1
    prefer_a = next(
        route for route in catalog["routes"] if route["slug"].startswith("codex-a/")
    )
    prefer_b = next(
        route for route in catalog["routes"] if route["slug"].startswith("codex-b/")
    )
    assert prefer_a["candidates"] == ["codex-a", "codex-b", "ark-text"]
    assert prefer_b["candidates"] == ["codex-b", "codex-a", "ark-text"]
    assert prefer_a["routing_mode"] == prefer_b["routing_mode"] == "preferred"
    luna = next(route for route in catalog["routes"] if route["slug"] == "gpt-5.6-luna")
    assert luna["candidates"] == ["codex-a", "codex-b"]
    assert luna["eligible_candidates"]["image"] == ["codex-a", "codex-b"]
    assert luna["reasoning_levels"] == ["low", "medium", "high", "xhigh", "max"]
    assert luna["fast_candidates"] == ["codex-a", "codex-b"]

    repeated_ring = copy.deepcopy(_source())
    repeated_ring["rings"][0]["max_cycles"] = 2
    expect_error(
        lambda: compile_catalog(repeated_ring), "multi-cycle fallback ring was accepted"
    )

    overlapping_tail = copy.deepcopy(_source())
    overlapping_tail["routes"][1]["fallback_tail"] = ["codex-b"]
    expect_error(
        lambda: compile_catalog(overlapping_tail),
        "fallback tail overlapping the account ring was accepted",
    )

    leaked = copy.deepcopy(_source())
    leaked["profiles"][0]["access_token"] = "example-sensitive-value"
    expect_error(
        lambda: compile_catalog(leaked), "credential-shaped field was accepted"
    )

    identified = copy.deepcopy(_source())
    identified["profiles"][0]["id"] = "operator" + "@" + "example.invalid"
    expect_error(lambda: compile_catalog(identified), "account identity was accepted")

    ambiguous_boolean = copy.deepcopy(_source())
    ambiguous_boolean["profiles"][0]["supports_fast"] = "false"
    expect_error(
        lambda: compile_catalog(ambiguous_boolean), "string boolean was accepted"
    )

    no_image_provider = copy.deepcopy(_source())
    no_image_provider["profiles"][0]["input_modalities"] = ["text"]
    no_image_provider["profiles"][1]["input_modalities"] = ["text"]
    expect_error(
        lambda: compile_catalog(no_image_provider),
        "image route without an eligible image provider was accepted",
    )

    divergent_alias = copy.deepcopy(_source())
    divergent_alias["routes"][-1]["supports_fast"] = False
    expect_error(
        lambda: compile_catalog(divergent_alias), "divergent alias was accepted"
    )

    snapshot = qualify_snapshot(_valid_snapshot())
    assert snapshot["qualified"] is True
    stale = _valid_snapshot()
    stale["affinity_policy"] = "sticky_without_revalidation"
    stale["turn_revision_matches"] = False
    failed = qualify_snapshot(stale)
    assert failed["qualified"] is False
    assert {item["id"] for item in failed["checks"] if not item["passed"]} == {
        "modality_aware_affinity",
        "settings_revision",
    }

    wrong_prefer_b = _valid_snapshot()
    wrong_prefer_b["route_traversal"]["codex-b/gpt-5.6-sol"]["ordered_candidates"] = [
        "codex-a",
        "codex-b",
        "ark-text",
    ]
    failed = qualify_snapshot(wrong_prefer_b)
    assert failed["qualified"] is False
    assert "preferred_route_order" in {
        item["id"] for item in failed["checks"] if not item["passed"]
    }

    luna_with_ark = _valid_snapshot()
    luna_with_ark["route_traversal"]["gpt-5.6-luna"]["ordered_candidates"] = [
        "codex-a",
        "codex-b",
        "ark-text",
    ]
    luna_with_ark["route_traversal"]["gpt-5.6-luna"]["fallback_tail"] = ["ark-text"]
    failed = qualify_snapshot(luna_with_ark)
    assert failed["qualified"] is False
    assert {
        "preferred_route_order",
        "terminal_fallback_tail",
    } <= {item["id"] for item in failed["checks"] if not item["passed"]}

    plan = build_upgrade_plan(
        {
            "current_ref": "public-current-ref",
            "target_ref": "public-target-ref",
            "changed_seams": [
                "transport_pool",
                "modality_routing",
                "settings_revision",
            ],
        }
    )
    assert "h2_reuse" in plan["required_checks"]
    assert "no_eligible_fail_closed" in plan["required_checks"]
    assert "turn_revision_match" in plan["required_checks"]

    response = _run_request(
        {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "operation": "qualify_snapshot",
            "snapshot": _valid_snapshot(),
        }
    )
    assert response["ok"] is True and response["result"]["qualified"] is True
    for example_name in (
        "request.json",
        "qualification-snapshot.json",
        "upgrade-request.json",
    ):
        example_request = json.loads(
            (PACKAGE_ROOT / "examples" / example_name).read_text()
        )
        example_response = _run_request(example_request)
        assert example_response["ok"] is True, example_name
    expect_error(
        lambda: _run_request(
            {
                "schema_version": REQUEST_SCHEMA_VERSION,
                "operation": "qualify_snapshot",
                "snapshot": _valid_snapshot(),
                "source": {},
            }
        ),
        "operation accepted an unrelated payload field",
    )
    print("ok: codex provider routing extension smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
