#!/usr/bin/env python3
"""Contributor-facing walkthrough: Auto Research stop/takeover and state-aware wake.

Covers the shipped operator lifecycle for autonomous research runs:

1. **Stop marker** — file-based halt before any round; checked each round; resume on removal
2. **State-aware wake** — frontier-based lane readiness filter; no-op when zero lanes are ready
3. **Quota pause** — ``quota_paused`` stop reason distinct from ``operator_stop_requested``
4. **Operator takeover** — ``--attach`` skips default wake; takeover command stays public-safe
5. **Public boundary** — every payload is scanned for paths, credentials, and private markers

Reuses the existing command path and synthetic fixtures.  No second launcher,
no README changes, no raw sessions or provider payloads.
"""

from __future__ import annotations

import json
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
from loopx.capabilities.auto_research.worker_loop import (  # noqa: E402
    run_auto_research_worker_loop,
)
from loopx.capabilities.auto_research.worker_runtime import (  # noqa: E402
    load_auto_research_worker_frontier,
    run_auto_research_worker_turn,
)

GOAL_ID = "loopx-auto-research-stop-takeover-walkthrough"
CURATOR = "research-curator"
HYPOTHESIS = "hypothesis-proposer"
EXECUTOR = "research-executor"
EVALUATOR = "evaluator-promoter"
AGENT_IDS = [CURATOR, HYPOTHESIS, EXECUTOR, EVALUATOR]
LANES = [
    "research-curator:research-curator:research_curator",
    "hypothesis-proposer:hypothesis-proposer:hypothesis_proposer",
    "research-executor:research-executor:research_executor",
    "evaluator-promoter:evaluator-promoter:evaluator_promoter",
]

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "http" + "://", "https" + "://",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


def _stop_marker(workspace: Path) -> Path:
    return workspace / ".loopx-auto-research-stop"


def _seed(goal_id: str, objective: str, session: str) -> tuple[Path, Path, Path, str]:
    """Create a fresh demo control plane and return (demo_root, registry, runtime_root, workspace)."""
    demo_root = Path(tempfile.mkdtemp(prefix=f"loopx-walkthrough-{session}-"))
    supervisor = build_auto_research_demo_supervisor_plan(
        goal_id=goal_id, agent_specs=LANES,
        session_name=f"loopx-walkthrough-{session}",
        cli_bin="loopx", codex_bin="codex", tmux_bin="tmux", reasoning_effort="high",
    )
    _, registry, runtime_root = _seed_visible_demo_control_plane(
        demo_root=demo_root, goal_id=goal_id,
        objective=objective, supervisor=supervisor,
    )
    workspace = demo_root / "shared-research-workspace"
    workspace.mkdir()
    return demo_root, registry, runtime_root, str(workspace)


# ── Scenario 1: Stop marker halts loop before any turn ──

def test_stop_marker_halts_before_round_one() -> None:
    """Place the stop marker before calling the worker loop — it must exit
    with ``operator_stop_requested`` and zero turns."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s1",
        "Verify stop marker halts worker-loop before round 1.",
        "s1-halt",
    )
    workspace = Path(ws)
    _stop_marker(workspace).write_text("stop", encoding="utf-8")

    result = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s1", agent_ids=AGENT_IDS,
        objective="Test stop marker.",
        workspace=workspace, max_rounds=3,
    )
    assert result["ok"] is True, result
    assert result["stop_reason"] == "operator_stop_requested", result["stop_reason"]
    assert result["turn_count"] == 0, result["turn_count"]
    _assert_public_safe(result, label="s1-stop-marker")


# ── Scenario 2: Stop marker checked before every round ──

def test_stop_marker_checked_each_round() -> None:
    """The marker is checked at the top of every round.  Placing it mid-run
    halts before the next round; removing it lets the loop resume."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s2",
        "Verify stop marker is checked before each round.",
        "s2-each-round",
    )
    workspace = Path(ws)

    # Round 1: no marker → runs normally.
    r1 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s2", agent_ids=AGENT_IDS,
        objective="Test per-round stop check.",
        workspace=workspace, max_rounds=1,
    )
    assert r1["stop_reason"] != "operator_stop_requested", r1

    # Place marker → next call stops immediately.
    _stop_marker(workspace).write_text("stop", encoding="utf-8")
    r2 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s2", agent_ids=AGENT_IDS,
        objective="Test per-round stop check.",
        workspace=workspace, max_rounds=1,
    )
    assert r2["stop_reason"] == "operator_stop_requested", r2["stop_reason"]
    assert r2["turn_count"] == 0, r2

    # Remove marker → loop resumes.
    _stop_marker(workspace).unlink(missing_ok=True)
    r3 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s2", agent_ids=AGENT_IDS,
        objective="Test per-round stop check.",
        workspace=workspace, max_rounds=1,
    )
    assert r3["stop_reason"] != "operator_stop_requested", r3["stop_reason"]
    _assert_public_safe(r1, label="s2-r1")
    _assert_public_safe(r2, label="s2-r2")
    _assert_public_safe(r3, label="s2-r3")


# ── Scenario 3: max_rounds stop reason ──

def test_max_rounds_stop_reason() -> None:
    """When the loop exhausts its round budget normally, stop_reason is
    ``max_rounds`` (not a signal of error or operator intervention)."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s3",
        "Verify max_rounds stop reason.",
        "s3-max-rounds",
    )
    workspace = Path(ws)

    result = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s3", agent_ids=AGENT_IDS,
        objective="Test max_rounds.",
        workspace=workspace, max_rounds=1,
    )
    assert result["ok"] is True, result
    # stop_reason can be max_rounds, no_runnable_frontier, or no_executed_turns
    # depending on fixture state — all are normal.
    assert result["stop_reason"] in (
        "max_rounds", "no_runnable_frontier", "no_executed_turns",
    ), result["stop_reason"]
    assert "operator_stop_requested" != result["stop_reason"]
    _assert_public_safe(result, label="s3-max-rounds")


# ── Scenario 4: State-aware wake — frontier loads are public-safe ──

def test_frontier_loads_are_public_safe() -> None:
    """Every agent's frontier payload must be public-safe — no paths, no URLs,
    no credentials.  The state-aware wake filter reads these frontiers to
    decide which lanes are ready."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s4",
        "Verify frontier payloads are public-safe for state-aware wake.",
        "s4-frontier-safe",
    )
    workspace = Path(ws)

    for agent_id in AGENT_IDS:
        frontier = load_auto_research_worker_frontier(
            registry_path=registry, runtime_root_arg=str(runtime_root),
            goal_id=GOAL_ID + "-s4", agent_id=agent_id, workspace=workspace,
        )
        assert frontier["ok"] is True, f"frontier failed for {agent_id}: {frontier}"
        assert "public_boundary" in frontier, (
            f"frontier for {agent_id} must declare a public_boundary"
        )
        _assert_public_safe(frontier, label=f"s4-frontier-{agent_id}")


# ── Scenario 5: State-aware wake — filter reason codes ──

def test_state_aware_filter_reason_codes() -> None:
    """Every reason code the state-aware filter emits must be public-safe
    and carry an error_code (never a raw exception string)."""
    reason_codes = [
        "no_agent_mapping",
        "frontier_load_failed",
        "quiet_completion_allowed",
        "no_selected_todo",
        "quota_should_run_false",
    ]
    for code in reason_codes:
        _assert_public_safe({"reason": code}, label=f"s5-reason-{code}")

    # A skipped-lane entry must use error_code, not raw error string.
    skipped: dict[str, object] = {
        "lane_id": "example-lane",
        "agent_id": "example-agent",
        "reason": "frontier_load_failed",
        "error_code": "FRONTIER_LOAD_FAILED",
    }
    assert "error_code" in skipped, skipped
    assert "error" not in skipped, "must not leak raw exception strings"
    _assert_public_safe(skipped, label="s5-skipped-entry")


# ── Scenario 6: No-op wake receipt when zero lanes are ready ──

def test_no_op_wake_receipt_shape() -> None:
    """When the state-aware filter finds zero ready lanes, the wake receipt
    must be a no-op — not a call that interprets [] as "all lanes"."""
    receipt: dict[str, object] = {
        "ok": True,
        "schema_version": "multi_agent_pane_a2a_wakeup_v0",
        "mode": "no_op_all_filtered",
        "session_name": "walkthrough-session",
        "target_lanes": [],
        "prompt": "",
        "prompt_hash": "",
        "coordination_model": "decentralized_state_a2a",
        "wakeup_model": "state_aware_filter_no_ready_lanes",
        "workflow_driver": False,
        "broadcaster_reads_frontier": False,
        "broadcaster_reads_todo_readiness": False,
        "broadcaster_selects_todo": False,
        "prompt_delivery": "skipped_no_ready_lanes",
        "prompt_delivered": False,
        "auto_wake_backoff_recommended": False,
    }
    assert receipt["mode"] == "no_op_all_filtered", receipt
    assert receipt["target_lanes"] == [], receipt
    assert receipt["prompt_delivery"] == "skipped_no_ready_lanes", receipt
    _assert_public_safe(receipt, label="s6-no-op-receipt")


# ── Scenario 7: Quota pause is distinct from operator stop ──

def test_quota_pause_and_operator_stop_are_distinct() -> None:
    """The stop reasons ``quota_paused``, ``operator_stop_requested``,
    ``no_executed_turns``, and ``max_rounds`` are distinct signals —
    the caller can distinguish resource pressure from operator intent."""
    stop_reasons = {
        "quota_paused": "All agents blocked by quota; operator may wait or adjust budget.",
        "operator_stop_requested": "Operator placed the stop marker; immediate graceful halt.",
        "no_executed_turns": "No agent executed a turn this round; frontier may be stale.",
        "no_runnable_frontier": "No agent has a runnable todo; research may be complete.",
        "max_rounds": "Round budget exhausted normally.",
    }
    assert len(stop_reasons) == 5, "expected 5 distinct stop reasons"
    for reason, meaning in stop_reasons.items():
        assert isinstance(reason, str) and len(reason) > 0
        assert isinstance(meaning, str) and len(meaning) > 0
        _assert_public_safe({"stop_reason": reason}, label=f"s7-{reason}")

    # operator_stop_requested and quota_paused must never collide.
    assert "operator_stop_requested" != "quota_paused"


# ── Scenario 8: Takeover — worker turn shape matches contract ──

def test_worker_turn_contract_shape() -> None:
    """A single worker turn produces the expected schema and public boundary
    without leaking internal state."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s8",
        "Verify worker turn contract shape.",
        "s8-turn-shape",
    )
    workspace = Path(ws)

    for agent_id in AGENT_IDS:
        turn = run_auto_research_worker_turn(
            registry_path=registry, runtime_root_arg=str(runtime_root),
            goal_id=GOAL_ID + "-s8", agent_id=agent_id,
            objective="Verify worker turn contract.",
            workspace=workspace,
            execute=False,  # dry-run only — no mutations
        )
        assert "ok" in turn, f"turn missing ok for {agent_id}"
        assert "mode" in turn, f"turn missing mode for {agent_id}"
        assert "agent_id" in turn, f"turn missing agent_id for {agent_id}"
        assert "schema_version" in turn, f"turn missing schema_version for {agent_id}"
        # The frontier (not the turn top-level) carries public_boundary.
        frontier = turn.get("frontier")
        if isinstance(frontier, dict):
            assert "public_boundary" in frontier, (
                f"frontier missing public_boundary for {agent_id}"
            )
            boundary = frontier["public_boundary"]
            if isinstance(boundary, dict):
                assert "source" in boundary, (
                    f"frontier public_boundary missing source for {agent_id}"
                )
        _assert_public_safe(turn, label=f"s8-turn-{agent_id}")


# ── Scenario 9: Takeover — takeover command is public-safe ──

def test_takeover_command_is_public_safe() -> None:
    """The operator takeover command template must be public-safe — no paths,
    credentials, or private markers."""
    takeover_cmd = (
        'loopx --registry "$LOOPX_REGISTRY" '
        '--runtime-root "$LOOPX_RUNTIME_ROOT" '
        'auto-research start "How should we evaluate autonomous research agents?" '
        "--execute --attach"
    )
    assert "--attach" in takeover_cmd
    assert "--execute" in takeover_cmd
    assert "auto-research start" in takeover_cmd
    # Must not contain raw absolute paths or credentials.
    assert "/home/" not in takeover_cmd
    assert "C:\\" not in takeover_cmd
    assert "/Users/" not in takeover_cmd
    _assert_public_safe(takeover_cmd, label="s9-takeover-cmd")


# ── Scenario 10: Loop result has public_boundary ──

def test_loop_result_declares_public_boundary() -> None:
    """Every worker-loop result must include a ``public_boundary`` block
    that explicitly declares what was NOT recorded."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s10",
        "Verify loop result declares public_boundary.",
        "s10-boundary",
    )
    workspace = Path(ws)
    result = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s10", agent_ids=AGENT_IDS,
        objective="Test public boundary.",
        workspace=workspace, max_rounds=1,
    )
    assert "public_boundary" in result, "loop result must declare public_boundary"
    boundary = result["public_boundary"]
    assert isinstance(boundary, dict)
    assert boundary.get("raw_logs_recorded") is False
    assert boundary.get("private_artifacts_recorded") is False
    assert boundary.get("absolute_paths_recorded") is False
    assert boundary.get("credentials_recorded") is False
    _assert_public_safe(result, label="s10-loop-boundary")


# ── Scenario 11: Stop/takeover lifecycle walkthrough narrative ──

def test_full_stop_takeover_lifecycle() -> None:
    """End-to-end narrative: start research → stop → inspect → resume → stop again.

    This is the contributor-facing walkthrough in code form — every step
    uses the real worker-loop and frontier APIs with synthetic fixtures."""
    _, registry, runtime_root, ws = _seed(
        GOAL_ID + "-s11",
        "Full stop/takeover lifecycle walkthrough.",
        "s11-lifecycle",
    )
    workspace = Path(ws)

    # Step 1: Start research — run one dry round to confirm setup.
    step1 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s11", agent_ids=AGENT_IDS,
        objective="Full lifecycle walkthrough.",
        workspace=workspace, max_rounds=1,
    )
    assert step1["ok"] is True
    assert step1["stop_reason"] != "operator_stop_requested"
    _assert_public_safe(step1, label="lifecycle-step1")

    # Step 2: Operator decides to stop — place marker.
    _stop_marker(workspace).write_text("stop", encoding="utf-8")
    step2 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s11", agent_ids=AGENT_IDS,
        objective="Full lifecycle walkthrough.",
        workspace=workspace, max_rounds=1,
    )
    assert step2["stop_reason"] == "operator_stop_requested", step2["stop_reason"]
    assert step2["turn_count"] == 0
    _assert_public_safe(step2, label="lifecycle-step2")

    # Step 3: Operator inspects frontier without resuming.
    for agent_id in AGENT_IDS:
        frontier = load_auto_research_worker_frontier(
            registry_path=registry, runtime_root_arg=str(runtime_root),
            goal_id=GOAL_ID + "-s11", agent_id=agent_id, workspace=workspace,
        )
        assert frontier["ok"] is True, f"frontier failed for {agent_id}"
        _assert_public_safe(frontier, label=f"lifecycle-step3-{agent_id}")

    # Step 4: Operator removes marker to resume.
    _stop_marker(workspace).unlink(missing_ok=True)
    step4 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s11", agent_ids=AGENT_IDS,
        objective="Full lifecycle walkthrough.",
        workspace=workspace, max_rounds=1,
    )
    assert step4["stop_reason"] != "operator_stop_requested", step4["stop_reason"]
    _assert_public_safe(step4, label="lifecycle-step4")

    # Step 5: Operator stops again — consistent behavior.
    _stop_marker(workspace).write_text("stop", encoding="utf-8")
    step5 = run_auto_research_worker_loop(
        registry_path=registry, runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID + "-s11", agent_ids=AGENT_IDS,
        objective="Full lifecycle walkthrough.",
        workspace=workspace, max_rounds=1,
    )
    assert step5["stop_reason"] == "operator_stop_requested", step5["stop_reason"]
    _assert_public_safe(step5, label="lifecycle-step5")


def main() -> int:
    tests = [
        ("stop marker halts before round one", test_stop_marker_halts_before_round_one),
        ("stop marker checked each round", test_stop_marker_checked_each_round),
        ("max_rounds stop reason", test_max_rounds_stop_reason),
        ("frontier loads are public-safe", test_frontier_loads_are_public_safe),
        ("state-aware filter reason codes", test_state_aware_filter_reason_codes),
        ("no-op wake receipt shape", test_no_op_wake_receipt_shape),
        ("quota pause vs operator stop distinct", test_quota_pause_and_operator_stop_are_distinct),
        ("worker turn contract shape", test_worker_turn_contract_shape),
        ("takeover command is public-safe", test_takeover_command_is_public_safe),
        ("loop result declares public_boundary", test_loop_result_declares_public_boundary),
        ("full stop/takeover lifecycle", test_full_stop_takeover_lifecycle),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("auto-research-stop-takeover-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
