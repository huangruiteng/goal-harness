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
    luna = next(route for route in catalog["routes"] if route["slug"] == "gpt-5.6-luna")
    assert luna["candidates"] == ["codex-a", "codex-b"]
    assert luna["eligible_candidates"]["image"] == ["codex-a", "codex-b"]
    assert luna["reasoning_levels"] == ["low", "medium", "high", "xhigh", "max"]
    assert luna["fast_candidates"] == ["codex-a", "codex-b"]

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
