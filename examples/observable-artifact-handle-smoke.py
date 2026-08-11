#!/usr/bin/env python3
"""Smoke-test the generic ``observable_artifact_handle_v0`` capability.

Builds one synthetic handle per allowed kind, validates each, projects
first-screen status, and renders a markdown summary.  All assertions are
public-safe — no raw paths, credentials, or private payloads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.observable_artifact_handle import (  # noqa: E402
    ALLOWED_HANDLE_KINDS,
    build_observable_artifact_handle,
    build_observable_artifact_handle_fixture,
    build_observable_artifact_handle_policy,
    project_observable_artifact_handle,
    render_observable_artifact_handle_markdown,
    validate_observable_artifact_handle,
)


def _assert_public_safe_payload(payload: dict, *, label: str) -> None:
    """Verify a payload contains no raw paths, URLs, or credential markers."""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    assert "/Users/" not in text, f"{label}: absolute path leak"
    assert "https://" not in text, f"{label}: URL leak"
    assert "password" not in text.lower(), f"{label}: credential leak"
    assert "api_key" not in text.lower(), f"{label}: API key leak"
    assert "bearer " not in text.lower(), f"{label}: bearer token leak"
    assert "C:\\" not in text, f"{label}: Windows path leak"


def main() -> None:
    print("=== Observable Artifact Handle Smoke ===\n")

    # ── Build one handle per kind ──
    for kind in sorted(ALLOWED_HANDLE_KINDS):
        result = build_observable_artifact_handle_fixture(handle_kind=kind)
        assert result["ok"] is True, f"fixture {kind} not ok"
        assert result["schema_version"] == "observable_artifact_handle_v0"
        assert result["handle_kind"] == kind
        assert result["launch_actions_enabled"] is False
        assert result["production_actions_enabled"] is False
        _assert_public_safe_payload(result, label=f"fixture/{kind}")
        print(f"  [OK] fixture {kind}: {result['handle_id']} [{result['state']}]")

    print()

    # ── Terminal marker exercise ──
    for state in ("queued", "running", "completed", "failed", "cancelled"):
        handle = build_observable_artifact_handle_fixture(state=state)
        is_terminal = handle["is_terminal"]
        policy = build_observable_artifact_handle_policy(handle)
        proj = project_observable_artifact_handle(handle)
        expected_poll = (
            not is_terminal and state in {"queued", "starting", "running"}
        )
        assert policy["poll_allowed"] == expected_poll, (
            f"poll mismatch for {state}"
        )
        print(
            f"  [OK] state {state}: terminal={is_terminal} "
            f"poll={policy['poll_allowed']} "
            f"next={policy['next_action']}"
        )

    print()

    # ── Read boundary defaults ──
    handle = build_observable_artifact_handle_fixture()
    boundary = handle["read_boundary"]
    assert boundary["compact_only"] is True
    assert boundary["raw_logs_allowed"] is False
    assert boundary["raw_command_allowed"] is False
    assert boundary["raw_env_allowed"] is False
    for key in boundary:
        print(f"  [OK] read_boundary.{key} = {boundary[key]}")

    print()

    # ── Validation ──
    for kind in sorted(ALLOWED_HANDLE_KINDS):
        handle = build_observable_artifact_handle_fixture(handle_kind=kind)
        validation = validate_observable_artifact_handle(handle)
        assert validation["ok"] is True, (
            f"validation failed for {kind}: {validation['errors']}"
        )
        assert validation["errors"] == []
    print("  [OK] all fixture validations pass")

    # ── Rejection of unsafe inputs ──
    rejections = 0
    unsafe_cases: list[dict] = [
        {"handle_id": "/Users/alice/test", "display_name": "Bad path in id"},
        {"handle_id": "bad-path", "display_name": "C:\\Users\\alice\\test"},
        {
            "handle_id": "bad-url",
            "display_name": "OK name",
            "artifact_refs": ["https://evil.com/logs"],
        },
        {
            "handle_id": "bad-cred",
            "display_name": "Run with password=secret123",
        },
    ]
    for case in unsafe_cases:
        try:
            build_observable_artifact_handle(**case)
            print(f"  [FAIL] should have rejected: {case}")
        except ValueError:
            rejections += 1
    assert rejections == len(unsafe_cases), (
        f"expected {len(unsafe_cases)} rejections, got {rejections}"
    )
    print(f"  [OK] all {rejections} unsafe inputs rejected")

    print()

    # ── Markdown rendering ──
    handle = build_observable_artifact_handle_fixture(
        handle_kind="benchmark_attempt",
        state="completed",
    )
    markdown = render_observable_artifact_handle_markdown(handle)
    assert "demo-handle-001" in markdown
    assert "benchmark_attempt" in markdown
    assert "completed" in markdown
    assert "terminal: `True`" in markdown
    assert "Read Boundary" in markdown
    print("  [OK] markdown render includes key fields")

    print()

    # ── Projection truth contract ──
    proj = project_observable_artifact_handle(handle)
    truth = proj["truth_contract"]
    assert truth["projection_is_writable"] is False
    assert truth["launch_actions_enabled"] is False
    assert truth["compact_observation_only"] is True
    print("  [OK] projection truth contract is read-only")

    print()

    # ── Deploy-specific terminal markers ──
    deploy_handle = build_observable_artifact_handle_fixture(handle_kind="deploy")
    assert "rolled_back" in deploy_handle["terminal_markers"]
    print("  [OK] deploy fixture includes rolled_back terminal marker")

    print()

    # ── Custom handle ──
    custom = build_observable_artifact_handle(
        handle_id="custom-smoke-001",
        handle_kind="evaluation",
        display_name="Custom Smoke Evaluation",
        state="running",
        allowed_poll_command="eval poll --id custom-smoke-001",
        artifact_refs=["eval/metrics.json"],
        terminal_markers=["timed_out"],
        poll_observations=["task_state", "done_marker"],
    )
    assert custom["ok"] is True
    assert custom["handle_id"] == "custom-smoke-001"
    assert custom["handle_kind"] == "evaluation"
    assert "timed_out" in custom["terminal_markers"]
    _assert_public_safe_payload(custom, label="custom")
    print(f"  [OK] custom handle ok: {custom['handle_id']}")

    print(f"\n=== {len(ALLOWED_HANDLE_KINDS) * 2 + 4 + 3 + 1} checks passed ===")


if __name__ == "__main__":
    main()
