#!/usr/bin/env python3
"""Smoke-test structured benchmark run permission policy projection."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.benchmark_toolkit import (  # noqa: E402
    RUN_PERMISSION_POLICY_SCHEMA_VERSION,
    RUN_PERMISSION_QUOTA_PROJECTION_SCHEMA_VERSION,
    RunPermissionAction,
    build_run_permission_policy,
    compact_run_permission_policy_for_quota,
    validate_run_permission_policy,
)


def assert_default_policy_is_quota_readable() -> None:
    policy = build_run_permission_policy(max_wall_time_minutes=90)
    validation = validate_run_permission_policy(policy)
    projection = compact_run_permission_policy_for_quota(policy)

    assert policy["schema_version"] == RUN_PERMISSION_POLICY_SCHEMA_VERSION, policy
    assert validation["ok"] is True, validation
    assert projection is not None, policy
    assert projection["schema_version"] == RUN_PERMISSION_QUOTA_PROJECTION_SCHEMA_VERSION
    assert projection["delivery_allowed"] is True, projection
    assert projection["no_upload_required"] is True, projection
    assert projection["submit_allowed"] is False, projection
    assert projection["leaderboard_claim_allowed"] is False, projection
    assert projection["public_benchmark_claim_allowed"] is False, projection
    assert projection["production_cloud_allowed"] is False, projection
    assert projection["compact_observation_only"] is True, projection
    assert projection["max_wall_time_minutes"] == 90, projection
    assert RunPermissionAction.CODEX_MODEL_INVOCATION.value in projection["allowed_actions"]
    assert RunPermissionAction.PUBLIC_RESULT_UPLOAD.value in projection["forbidden_actions"]


def assert_policy_rejects_narrative_widening() -> None:
    policy = build_run_permission_policy()
    widened = dict(policy)
    widened["allowed_actions"] = [
        *policy["allowed_actions"],
        RunPermissionAction.PUBLIC_RESULT_UPLOAD.value,
    ]
    widened["submit_allowed"] = True
    widened["observation_boundary"] = {
        **policy["observation_boundary"],
        "compact_only": False,
    }

    validation = validate_run_permission_policy(widened)
    projection = compact_run_permission_policy_for_quota(widened)

    assert validation["ok"] is False, validation
    assert "run_permission_policy_allowed_forbidden_overlap" in validation["blockers"]
    assert "run_permission_policy_submit_allowed" in validation["blockers"]
    assert "run_permission_policy_compact_only_not_required" in validation["blockers"]
    assert projection is not None
    assert projection["delivery_allowed"] is False, projection
    assert projection["first_blocker"], projection


def main() -> int:
    assert_default_policy_is_quota_readable()
    assert_policy_rejects_narrative_widening()
    print("benchmark-run-permission-policy-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
