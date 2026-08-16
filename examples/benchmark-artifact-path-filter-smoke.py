#!/usr/bin/env python3
"""Smoke-test public-safe benchmark artifact path classification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.benchmark_toolkit import (  # noqa: E402
    filter_public_benchmark_artifact_paths,
)


PRIVATE_ROOT = "/private/example/project/.local/private-benchmark-jobs/job-a"
PATHS = [
    f"{PRIVATE_ROOT}/paired_comparison.compact.json",
    f"{PRIVATE_ROOT}/launch_status.public.json",
    f"{PRIVATE_ROOT}/treatment/active-user-feed/loopx-active-user-observation.json",
    f"{PRIVATE_ROOT}/agent/trajectory.json",
    f"{PRIVATE_ROOT}/launch_private_manifest.local.json",
    f"{PRIVATE_ROOT}/tasks/demo/instruction.md",
]
CUSTOM_POLICY_PATHS = [
    f"{PRIVATE_ROOT}/custom-observation-proof.json",
    f"{PRIVATE_ROOT}/custom-observation-proof.private.json",
]


def assert_no_path_leak(payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    forbidden = [
        "/private/example",
        ".local/private-benchmark-jobs",
        "job-a/agent",
        "tasks/demo",
    ]
    leaked = [item for item in forbidden if item in rendered]
    assert not leaked, leaked


def main() -> None:
    payload = filter_public_benchmark_artifact_paths(PATHS)
    assert payload["schema_version"] == "benchmark_artifact_path_filter_v0", payload
    assert payload["artifact_policy"]["adapter_kind"] == "default", payload
    assert payload["path_recorded"] is False, payload
    assert payload["allowed_to_read_count"] == 3, payload
    assert payload["blocked_count"] == 3, payload
    assert payload["allowed_artifact_basenames"] == [
        "paired_comparison.compact.json",
        "launch_status.public.json",
        "loopx-active-user-observation.json",
    ], payload
    assert payload["blocked_reasons"]["raw_private_surface"] == 2, payload
    assert payload["blocked_reasons"]["private_or_local_manifest"] == 1, payload
    assert_no_path_leak(payload)

    custom_payload = filter_public_benchmark_artifact_paths(
        CUSTOM_POLICY_PATHS,
        extra_public_filenames=["custom-observation-proof.json"],
    )
    assert custom_payload["allowed_artifact_basenames"] == [
        "custom-observation-proof.json"
    ], custom_payload
    assert custom_payload["blocked_reasons"]["private_or_local_manifest"] == 1, custom_payload
    assert_no_path_leak(custom_payload)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--format",
            "json",
            "benchmark",
            "classify-artifacts",
            "--allow-public-filename",
            "custom-observation-proof.json",
            *PATHS,
            *CUSTOM_POLICY_PATHS,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    cli_payload = json.loads(result.stdout)
    assert cli_payload["artifact_policy"]["adapter_kind"] == "default", cli_payload
    assert cli_payload["allowed_to_read_count"] == 4, cli_payload
    assert cli_payload["blocked_count"] == 4, cli_payload
    assert "custom-observation-proof.json" in cli_payload["allowed_artifact_basenames"], cli_payload
    assert_no_path_leak(cli_payload)
    print("ok")


if __name__ == "__main__":
    main()
