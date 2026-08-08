#!/usr/bin/env python3
"""Exercise the shipped Auto Research terminal-result CLI lifecycle."""

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

from examples.auto_research_lightweight_fixture import (  # noqa: E402
    AGENT_ID,
    GOAL_ID,
    HYPOTHESIS_ID,
    HYPOTHESIS_TEXT,
    MECHANISM_FAMILY,
    TODO_ID,
    write_contract_and_results,
)


PROMOTER = "evaluator-promoter"
REVIEWER = "independent-reviewer"


def run_cli(
    registry: Path,
    *args: str,
    expect_ok: bool = True,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--registry",
            str(registry),
            "--format",
            "json",
            "auto-research",
            *args,
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)
    if expect_ok:
        assert result.returncode == 0 and payload["ok"] is True, (result, payload)
    else:
        assert result.returncode != 0 and payload["ok"] is False, (result, payload)
    return payload


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        runtime_root = temp / "runtime"
        project = temp / "project"
        project.mkdir()
        registry = temp / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "common_runtime_root": str(runtime_root),
                    "goals": [
                        {
                            "id": GOAL_ID,
                            "repo": str(project),
                            "state_file": "ACTIVE_GOAL_STATE.md",
                            "adapter": {
                                "kind": "fixture",
                                "status": "connected-read-only",
                            },
                            "coordination": {
                                "agent_model": "peer_v1",
                                "registered_agents": [
                                    AGENT_ID,
                                    PROMOTER,
                                    REVIEWER,
                                ],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        contract, dev, holdout = write_contract_and_results(temp)
        packet_path = temp / "packet.json"
        packet = run_cli(
            registry,
            "evidence",
            "--contract",
            str(contract),
            "--eval-result",
            str(dev),
            "--eval-result",
            str(holdout),
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--todo-id",
            TODO_ID,
            "--agent-id",
            AGENT_ID,
            "--claimed-by",
            AGENT_ID,
            "--mechanism-family",
            MECHANISM_FAMILY,
            "--hypothesis",
            HYPOTHESIS_TEXT,
        )
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        run_cli(
            registry,
            "append-evidence",
            "--packet",
            str(packet_path),
        )
        unregistered = run_cli(
            registry,
            "decide",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--outcome",
            "promoted",
            "--reason",
            "holdout_validated",
            "--agent-id",
            "unregistered-promoter",
            "--execute",
            expect_ok=False,
        )
        assert "not registered" in unregistered["error"], unregistered
        run_cli(
            registry,
            "decide",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--outcome",
            "promoted",
            "--reason",
            "holdout_validated",
            "--agent-id",
            PROMOTER,
            "--evidence-ref",
            "decision:heldout",
            "--execute",
        )
        self_review = run_cli(
            registry,
            "review",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--reviewer-agent-id",
            PROMOTER,
            "--verdict",
            "approve",
            "--execute",
        )
        assert self_review["review"]["independent"] is False, self_review
        run_cli(
            registry,
            "review",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--reviewer-agent-id",
            REVIEWER,
            "--verdict",
            "approve",
            "--require-independent",
            "--evidence-ref",
            "review:independent",
            "--execute",
        )
        result = run_cli(
            registry,
            "results",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
            "--include-history",
        )
        assert result["results"][0]["finding_status"] == "confirmed", result
        first = run_cli(
            registry,
            "project-results",
            "--goal-id",
            GOAL_ID,
            "--execute",
        )
        second = run_cli(
            registry,
            "project-results",
            "--goal-id",
            GOAL_ID,
            "--execute",
        )
        assert first["appended_count"] > 0, first
        assert second["appended_count"] == 0, second
        assert second["reused_count"] == second["event_count"], second
        readback = run_cli(
            registry,
            "results",
            "--goal-id",
            GOAL_ID,
            "--hypothesis-id",
            HYPOTHESIS_ID,
        )
        assert readback["explore_projection"]["state"] == "current", readback
    print("auto-research-terminal-results-cli-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
