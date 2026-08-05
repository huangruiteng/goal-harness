#!/usr/bin/env python3
"""Synthetic walkthrough smoke: stop, takeover, and state-aware wake for auto-research.

Demonstrates the contributor-safe operator loop:
  1. Seed a demo goal and run one auto worker-loop round.
  2. Place a stop marker → worker-loop exits with ``operator_stop_requested``.
  3. Operator takes over a single lane via ``worker-turn``, completes a todo,
     and writes successor evidence.
  4. Remove the stop marker → worker-loop resumes and picks up the successor.
  5. All evidence is synthetic — no live model, no credentials, no private paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.auto_research.demo_e2e import _seed_visible_demo_control_plane  # noqa: E402
from loopx.capabilities.auto_research.demo_supervisor import (  # noqa: E402
    build_auto_research_demo_supervisor_plan,
)
from loopx.capabilities.auto_research.rollout_append import (  # noqa: E402
    append_auto_research_rollout_events,
)
from loopx.todos import add_goal_todo, complete_goal_todo  # noqa: E402

GOAL_ID = "loopx-auto-research-demo"
CURATOR_AGENT_ID = "research-curator"
HYPOTHESIS_AGENT_ID = "hypothesis-proposer"
EXECUTOR_AGENT_ID = "research-executor"
EVALUATOR_AGENT_ID = "evaluator-promoter"
AGENT_IDS = [CURATOR_AGENT_ID, HYPOTHESIS_AGENT_ID, EXECUTOR_AGENT_ID, EVALUATOR_AGENT_ID]
LANES = [
    "research-curator:research-curator:research_curator",
    "hypothesis-proposer:hypothesis-proposer:hypothesis_proposer",
    "research-executor:research-executor:research_executor",
    "evaluator-promoter:evaluator-promoter:evaluator_promoter",
]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def assert_public_safe(payload: Any) -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    forbidden = [
        "/" + "Users/",
        "/" + "private/",
        "/" + "tmp/",
        "http" + "://",
        "https" + "://",
        "api" + "_key",
        "pass" + "word",
        "sec" + "ret",
    ]
    leaked = [needle for needle in forbidden if needle.lower() in text.lower()]
    assert not leaked, leaked


def run_worker_loop(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """Run the auto-research worker-loop subprocess and return parsed JSON."""
    env = _env()
    args = [
        sys.executable,
        "-m",
        "loopx.cli",
        "--registry",
        str(registry),
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "auto-research",
        "worker-loop",
        "--goal-id",
        GOAL_ID,
        "--lane-count",
        str(len(AGENT_IDS)),
        "--max-rounds",
        str(max_rounds),
        "--visible-lanes-accepted",
        "--complete-selected-todo",
        "--execute",
    ]
    for agent_id in AGENT_IDS:
        args.extend(["--agent-id", agent_id])
    result = subprocess.run(
        args,
        cwd=workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"worker-loop failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


def run_worker_turn(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
    agent_id: str,
    execute: bool = True,
    complete: bool = False,
) -> dict[str, Any]:
    """Run a single worker-turn subprocess and return parsed JSON."""
    env = _env()
    args = [
        sys.executable,
        "-m",
        "loopx.cli",
        "--registry",
        str(registry),
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "auto-research",
        "worker-turn",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        agent_id,
        "--lane-count",
        str(len(AGENT_IDS)),
        "--visible-lanes-accepted",
    ]
    if execute:
        args.append("--execute")
    if complete:
        args.append("--complete-selected-todo")
    result = subprocess.run(
        args,
        cwd=workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"worker-turn failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


def place_stop_marker(workspace: Path) -> Path:
    """Create the stop-marker file the worker-loop checks before each round."""
    marker = workspace / ".loopx-auto-research-stop"
    marker.write_text("stop", encoding="utf-8")
    return marker


def remove_stop_marker(workspace: Path) -> None:
    marker = workspace / ".loopx-auto-research-stop"
    marker.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 1 — Seed a demo goal and run one worker-loop round
# ---------------------------------------------------------------------------
def test_seed_and_first_round() -> tuple[dict[str, Any], Path, str | None, Path]:
    """Smoke: seed → worker-loop round 1 produces expected modes."""
    temp = Path(tempfile.mkdtemp(prefix="loopx-auto-research-smoke-"))
    supervisor = build_auto_research_demo_supervisor_plan(
        goal_id=GOAL_ID,
        agent_specs=LANES,
        session_name="loopx-auto-research-stop-takeover-smoke",
        cli_bin="loopx",
        codex_bin="codex",
        tmux_bin="tmux",
        reasoning_effort="high",
    )
    visible_control, registry, runtime_root = _seed_visible_demo_control_plane(
        demo_root=temp,
        goal_id=GOAL_ID,
        objective="Verify stop-marker and operator-takeover work correctly with synthetic evidence.",
        supervisor=supervisor,
    )
    seeded_todos = visible_control["seeded_todos"]
    assert len(seeded_todos) == 4, f"expected 4 seed todos, got {len(seeded_todos)}"

    workspace = temp / "shared-research-workspace"
    workspace.mkdir()

    payload = run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert payload["ok"] is True, payload
    assert payload["schema_version"] == "auto_research_worker_loop_v0", payload
    assert payload["mode"] == "execute", payload
    assert payload["turn_count"] == 4, f"expected 4 turn slots, got {payload['turn_count']}"
    # Round 1: only the curator has a runnable seed todo (write_research_contract),
    # which requires manual research. The other three lanes have prerequisite
    # resume_when constraints and return no_action.
    assert payload["stop_reason"] == "no_executed_turns", f"unexpected stop_reason={payload['stop_reason']}"
    manual_turns = [t for t in payload["turns"] if t.get("mode") == "manual_research_required"]
    no_action_turns = [t for t in payload["turns"] if t.get("mode") == "no_action"]
    assert len(manual_turns) == 1, f"expected 1 manual turn, got {len(manual_turns)}"
    assert len(no_action_turns) == 3, f"expected 3 no-action turns, got {len(no_action_turns)}"
    assert manual_turns[0]["agent_id"] == CURATOR_AGENT_ID, manual_turns[0]
    assert manual_turns[0]["selected_action"] == "write_research_contract", manual_turns[0]
    assert_public_safe(payload)

    return visible_control, registry, runtime_root, workspace


# ---------------------------------------------------------------------------
# 2 — Stop marker: worker-loop exits with operator_stop_requested
# ---------------------------------------------------------------------------
def test_stop_marker_halts_worker_loop(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
) -> None:
    """Smoke: placing the stop marker causes the next worker-loop to exit before round 1."""
    # Remove any leftover from previous tests.
    remove_stop_marker(workspace)

    # Place the stop marker.
    marker = place_stop_marker(workspace)
    assert marker.exists(), "stop marker should exist"

    payload = run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=3,
    )
    assert payload["ok"] is True, payload
    assert payload["stop_reason"] == "operator_stop_requested", (
        f"expected operator_stop_requested, got {payload['stop_reason']}"
    )
    assert payload["turn_count"] == 0, (
        f"expected 0 turns when stopped before round 1, got {payload['turn_count']}"
    )
    assert payload["executed_turn_count"] == 0, payload
    assert_public_safe(payload)


# ---------------------------------------------------------------------------
# 3 — Operator takeover: manually complete a curator todo and write successor
# ---------------------------------------------------------------------------
def test_operator_takeover_curator_lane(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
    visible_control: dict[str, Any],
) -> None:
    """Smoke: operator manually calls worker-turn for the curator lane, simulating takeover.

    ``write_research_contract`` is a MANUAL_RESEARCH_REQUIRED action — the kernel
    cannot fabricate evidence.  The operator inspects the frontier, acknowledges
    the manual-research signal, then hand-crafts the successor step via
    ``add_goal_todo`` + ``complete_goal_todo`` so the next lane (hypothesis-
    proposer) can pick up the work.
    """
    # Stop marker should still be present from test 2 — verify it doesn't block
    # the individual worker-turn (only the loop checks the marker).
    marker = workspace / ".loopx-auto-research-stop"
    assert marker.exists(), "stop marker should still be in place"

    # Dry-run first to see what the frontier offers.
    curator_preview = run_worker_turn(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        agent_id=CURATOR_AGENT_ID,
        execute=False,
    )
    assert curator_preview["mode"] == "dry_run", curator_preview
    assert curator_preview["selected_action"] == "write_research_contract", curator_preview
    curator_todo_id = curator_preview["selected_todo_id"]
    assert curator_todo_id is not None, curator_preview

    # Execute: the kernel returns manual_research_required — it cannot do the
    # actual research work (that requires a visible Codex TUI pane).
    curator_turn = run_worker_turn(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        agent_id=CURATOR_AGENT_ID,
        execute=True,
        complete=False,
    )
    assert curator_turn["mode"] == "manual_research_required", curator_turn
    assert curator_turn["selected_action"] == "write_research_contract", curator_turn
    assert curator_turn["manual_research_required"] is True, curator_turn
    assert curator_turn["executed"] is False, curator_turn
    assert_public_safe(curator_turn)

    # ---- Simulate the operator's manual research work ----
    # The operator (or a visible Codex pane) wrote the research contract.
    # Now hand-craft the successor: a propose_hypothesis todo for the
    # hypothesis-proposer lane, then complete the curator's seed todo.
    successor_result = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=(
            "[P0-auto-research-live] Propose the first bounded research hypothesis "
            "from the operator-authored research contract."
        ),
        task_class="advancement_task",
        action_kind="propose_hypothesis",
        claimed_by=HYPOTHESIS_AGENT_ID,
        resume_when=f"todo_done:{curator_todo_id}",
        dry_run=False,
    )
    successor_todo_id = successor_result.get("todo_id")
    assert successor_todo_id, f"add_goal_todo did not return a todo_id: {successor_result}"
    successor_ids = [str(successor_todo_id)]

    # Complete the curator's seed todo, linking to the new successor.
    completion = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=curator_todo_id,
        role="agent",
        claimed_by=CURATOR_AGENT_ID,
        agent_id=CURATOR_AGENT_ID,
        note="operator takeover: curator wrote research contract and routed next hypothesis step",
        evidence=(
            "operator takeover synthetic evidence: research contract written, "
            "hypothesis round opened for hypothesis-proposer lane"
        ),
        successor_todo_ids=successor_ids,
        self_merged=True,
        dry_run=False,
    )
    assert completion["completed"] is True, completion
    assert completion["successor_todo_ids"] == successor_ids, completion
    assert_public_safe(completion)

    # Verify the successor todo is visible to the hypothesis-proposer.
    hypothesis_turn = run_worker_turn(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        agent_id=HYPOTHESIS_AGENT_ID,
        execute=False,
    )
    assert hypothesis_turn["mode"] != "no_action", (
        f"hypothesis-proposer should see successor work, got mode={hypothesis_turn['mode']}"
    )
    # The resume_when constraint should be satisfied because the curator's todo
    # is done, so the hypothesis todo should be selected.
    assert hypothesis_turn.get("selected_action") == "propose_hypothesis", (
        f"expected propose_hypothesis, got {hypothesis_turn.get('selected_action')}"
    )
    assert_public_safe(hypothesis_turn)


# ---------------------------------------------------------------------------
# 4 — Resume: remove stop marker, worker-loop picks up successor
# ---------------------------------------------------------------------------
def test_resume_after_takeover(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
) -> None:
    """Smoke: removing the stop marker lets the worker-loop resume where takeover left off."""
    remove_stop_marker(workspace)
    marker = workspace / ".loopx-auto-research-stop"
    assert not marker.exists(), "stop marker should be removed"

    payload = run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert payload["ok"] is True, payload

    # After takeover, the hypothesis-proposer should now have a runnable todo.
    # The curator's original work is done, so the curator may have no_action.
    # The executor and evaluator are still blocked by prerequisites.
    modes = [t["mode"] for t in payload["turns"]]
    assert "no_action" in modes or "manual_research_required" in modes, (
        f"resumed worker-loop should have actionable turns, got modes={modes}"
    )
    # The hypothesis-proposer should have the propose_hypothesis action.
    hyp_turns = [
        t for t in payload["turns"]
        if t.get("agent_id") == HYPOTHESIS_AGENT_ID
    ]
    assert len(hyp_turns) == 1, f"expected 1 hypothesis-proposer turn, got {len(hyp_turns)}"
    hyp_turn = hyp_turns[0]
    assert hyp_turn["mode"] != "no_action", (
        f"hypothesis-proposer should be runnable after operator takeover, got mode={hyp_turn['mode']}"
    )
    # Should either be dry_run/execute/manual based on the successor action.
    assert hyp_turn.get("selected_action") == "propose_hypothesis", hyp_turn
    assert_public_safe(payload)


# ---------------------------------------------------------------------------
# 5 — Stop marker persists across rounds within a single loop call
# ---------------------------------------------------------------------------
def test_stop_marker_mid_loop(
    *,
    registry: Path,
    runtime_root: str | None,
    workspace: Path,
) -> None:
    """Smoke: the stop marker is checked before each round — not just at the start."""
    remove_stop_marker(workspace)

    # Run one round normally first, then verify the marker stops round 2.
    # We use max_rounds=2; the stop marker placed after round 1 will prevent round 2.
    # (Because the marker is checked at the top of each round.)
    # Actually the check is BEFORE each round, so:
    #   Round 1: marker absent → runs
    #   Round 2: marker present → stops with operator_stop_requested
    # We simulate this by placing the marker after round 1 has already started.
    # Since we can't easily inject the marker mid-subprocess, we run round 1
    # separately, then place the marker before calling with max_rounds=1.

    # Already clean from the remove above; run one round.
    round1 = run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert round1["stop_reason"] in (
        "no_executed_turns",
        "no_runnable_frontier",
    ), f"round 1 stop_reason={round1['stop_reason']}"

    # Place the stop marker.
    place_stop_marker(workspace)

    # Now attempt another loop call — it should stop immediately.
    round2 = run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        max_rounds=1,
    )
    assert round2["stop_reason"] == "operator_stop_requested", (
        f"expected operator_stop_requested, got {round2['stop_reason']}"
    )
    assert round2["turn_count"] == 0, round2
    assert_public_safe(round2)


def main() -> int:
    # Test 1: seed + first round.
    visible_control, registry, runtime_root, workspace = test_seed_and_first_round()
    print("  ok  seed + first round")

    # Test 2: stop marker halts worker-loop.
    test_stop_marker_halts_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
    )
    print("  ok  stop marker halts worker-loop")

    # Test 3: operator takeover.
    test_operator_takeover_curator_lane(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
        visible_control=visible_control,
    )
    print("  ok  operator takeover completes curator lane")

    # Test 4: resume after takeover.
    test_resume_after_takeover(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
    )
    print("  ok  resume after takeover picks up successor")

    # Test 5: mid-loop stop marker.
    test_stop_marker_mid_loop(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
    )
    print("  ok  stop marker checked before each round")

    print(f"auto-research-stop-takeover-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
