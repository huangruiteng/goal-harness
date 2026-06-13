#!/usr/bin/env python3
"""Smoke-test benchmark adapter kwarg absorption review."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.benchmark import (  # noqa: E402
    TERMINAL_BENCH_MANAGED_CODEX_GOAL_HARNESS_KWARGS,
    agent_kwargs_from_invocation,
    build_benchmark_adapter_kwarg_absorption_review,
    build_terminal_bench_managed_harbor_command,
)


def terminal_bench_command() -> list[str]:
    return build_terminal_bench_managed_harbor_command(
        dataset="terminal-bench@2.0",
        task_id="public-fixture-task",
        jobs_dir="/tmp/private/jobs",
        job_name="adapter-kwarg-absorption-fixture",
        goal_harness_mode="codex_goal_harness",
        goal_harness_goal_id="goal-harness-meta",
        goal_harness_cli_bridge_enabled=True,
        goal_harness_active_user_intervention_enabled=True,
        goal_harness_project_root="/tmp/private/project",
        goal_harness_runtime_root="/tmp/private/runtime",
        goal_harness_classification="adapter_kwarg_absorption_fixture",
    )


def assert_no_private_surface(text: str) -> None:
    for forbidden in (
        "/tmp/private",
        "CODEX_FORCE_AUTH_JSON",
        "goal_harness_command_prefix=",
        "goal_harness_runtime_preflight_command=",
    ):
        assert forbidden not in text, text


def test_terminal_bench_generated_kwargs_are_absorbed() -> None:
    kwargs = agent_kwargs_from_invocation(terminal_bench_command())
    payload = build_benchmark_adapter_kwarg_absorption_review(
        adapter_label="terminal-bench-managed-codex",
        agent_kwargs=kwargs,
        accepted_goal_harness_kwargs=TERMINAL_BENCH_MANAGED_CODEX_GOAL_HARNESS_KWARGS,
    )

    assert payload["schema_version"] == "benchmark_adapter_kwarg_absorption_review_v0", payload
    assert payload["classification"] == "adapter_kwargs_absorbed", payload
    assert payload["clean"] is True, payload
    assert payload["leaked_goal_harness_kwarg_keys"] == [], payload
    assert payload["generated_goal_harness_kwarg_count"] >= 10, payload
    assert payload["claim_boundary"]["kwarg_values_recorded"] is False, payload
    assert_no_private_surface(json.dumps(payload, sort_keys=True))


def test_unknown_goal_harness_kwarg_is_leak_risk() -> None:
    kwargs = agent_kwargs_from_invocation(terminal_bench_command())
    kwargs["goal_harness_new_unabsorbed_key"] = "/tmp/private/should-not-print"
    payload = build_benchmark_adapter_kwarg_absorption_review(
        adapter_label="terminal-bench-managed-codex",
        agent_kwargs=kwargs,
        accepted_goal_harness_kwargs=TERMINAL_BENCH_MANAGED_CODEX_GOAL_HARNESS_KWARGS,
    )

    assert payload["classification"] == "adapter_kwarg_leak_risk", payload
    assert payload["clean"] is False, payload
    assert payload["leaked_goal_harness_kwarg_keys"] == [
        "goal_harness_new_unabsorbed_key"
    ], payload
    assert (
        payload["next_required_action"]
        == "consume_or_reject_generated_goal_harness_kwargs_before_worker_start"
    ), payload
    assert_no_private_surface(json.dumps(payload, sort_keys=True))


def test_cli_review_adapter_kwargs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        command_path = root / "command.json"
        command_path.write_text(json.dumps(terminal_bench_command()), encoding="utf-8")

        clean = subprocess.run(
            [
                sys.executable,
                "-m",
                "goal_harness.cli",
                "--format",
                "json",
                "benchmark",
                "review-adapter-kwargs",
                "--adapter-label",
                "terminal-bench-managed-codex",
                "--command-json",
                str(command_path),
                "--terminal-bench-managed-codex",
                "--require-clean",
            ],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        clean_payload = json.loads(clean.stdout)
        assert clean_payload["ok"] is True, clean_payload
        assert clean_payload["clean"] is True, clean_payload
        assert str(root) not in clean.stdout, clean.stdout
        assert_no_private_surface(clean.stdout)

        leak = subprocess.run(
            [
                sys.executable,
                "-m",
                "goal_harness.cli",
                "--format",
                "json",
                "benchmark",
                "review-adapter-kwargs",
                "--adapter-label",
                "terminal-bench-managed-codex",
                "--command-json",
                str(command_path),
                "--agent-kwarg",
                "goal_harness_new_unabsorbed_key=/tmp/private/should-not-print",
                "--terminal-bench-managed-codex",
                "--require-clean",
            ],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        assert leak.returncode == 1, leak.stdout
        leak_payload = json.loads(leak.stdout)
        assert leak_payload["ok"] is False, leak_payload
        assert leak_payload["classification"] == "adapter_kwarg_leak_risk", leak_payload
        assert leak_payload["leaked_goal_harness_kwarg_keys"] == [
            "goal_harness_new_unabsorbed_key"
        ], leak_payload
        assert str(root) not in leak.stdout, leak.stdout
        assert_no_private_surface(leak.stdout)


def main() -> int:
    test_terminal_bench_generated_kwargs_are_absorbed()
    test_unknown_goal_harness_kwarg_is_leak_risk()
    test_cli_review_adapter_kwargs()
    print("benchmark-adapter-kwarg-absorption-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
