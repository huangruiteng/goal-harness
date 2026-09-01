#!/usr/bin/env python3
"""Walkthrough smoke: documented start identity → stop → resume continuity.

Drives the shipped CLI with the same explicit arguments the contributor
walkthrough documents (docs/guides/auto-research-stop-takeover-wake-
walkthrough.md): one exported goal/workspace identity, ``start`` targeting
that identity, the stop marker placed in that workspace, and ``worker-loop``
run from that workspace with the same goal. Marker halting, visible launch
policy, state-aware wake, and quota-pause output shapes stay covered by their
own smokes; this file only proves identity continuity across the cycle.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.auto_research.demo_e2e import (  # noqa: E402
    _seed_visible_demo_control_plane,
)
from demo.auto_research.demo_supervisor import (  # noqa: E402
    build_auto_research_demo_supervisor_plan,
)


def _load_stop_marker_smoke() -> ModuleType:
    path = REPO_ROOT / "examples" / "auto-research-stop-marker-smoke.py"
    spec = importlib.util.spec_from_file_location("ar_stop_marker_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load stop-marker smoke from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STOP = _load_stop_marker_smoke()
GOAL_ID = _STOP.GOAL_ID
AGENT_IDS = _STOP.AGENT_IDS
LANES = _STOP.LANES
assert_public_safe = _STOP.assert_public_safe
_stop_marker = _STOP._stop_marker
_env = _STOP._env

QUESTION = "How should we evaluate autonomous research agents?"


def _seed_demo() -> tuple[Path, Path, str | None, Path]:
    temp = Path(tempfile.mkdtemp(prefix="loopx-smoke-stop-takeover-walkthrough-"))
    supervisor = build_auto_research_demo_supervisor_plan(
        goal_id=GOAL_ID,
        agent_specs=LANES,
        session_name="loopx-smoke-stop-takeover-walkthrough",
        cli_bin="loopx",
        codex_bin="codex",
        tmux_bin="tmux",
        reasoning_effort="high",
    )
    _, registry, runtime_root = _seed_visible_demo_control_plane(
        demo_root=temp,
        goal_id=GOAL_ID,
        objective="Prove stop, takeover command, resume, and state-aware wake.",
        supervisor=supervisor,
    )
    workspace = temp / "shared-research-workspace"
    workspace.mkdir()
    return temp, registry, runtime_root, workspace


def _cli_command(
    registry: Path, runtime_root: str | None, *command: str
) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "loopx.cli",
        "--registry",
        str(registry),
    ]
    if runtime_root:
        args.extend(["--runtime-root", str(runtime_root)])
    args.extend(["--format", "json", *command])
    return args


def _run_documented_start(
    *, registry: Path, runtime_root: str | None, workspace: Path
) -> dict[str, Any]:
    """Run the documented start path in dry-run mode (no visible lanes)."""
    result = subprocess.run(
        [
            *_cli_command(registry, runtime_root, "auto-research", "start", QUESTION),
            "--goal-id",
            GOAL_ID,
            "--workspace",
            str(workspace),
            "--create-workspace",
        ],
        cwd=workspace,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"documented start failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return json.loads(result.stdout)


def _run_worker_loop(
    *, registry: Path, runtime_root: str | None, cwd: Path, max_rounds: int
) -> dict[str, Any]:
    """Run the documented worker-loop CLI from an explicit working directory."""
    args = [
        *_cli_command(
            registry,
            runtime_root,
            "auto-research",
            "worker-loop",
            "--goal-id",
            GOAL_ID,
        ),
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
        cwd=cwd,
        env=_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"worker-loop failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return json.loads(result.stdout)


def test_documented_identity_continuity() -> None:
    """The documented start, stop, and resume commands share one identity."""
    _, registry, runtime_root, workspace = _seed_demo()

    # 1) start with the documented explicit flags targets the walkthrough goal.
    started = _run_documented_start(
        registry=registry,
        runtime_root=runtime_root,
        workspace=workspace,
    )
    assert started["ok"] is True, started
    assert started["goal_id"] == GOAL_ID, started
    route = started["route_contract"]
    assert route["goal_surface_mode"] == "explicit_goal", route
    assert route["visible_lanes_read_goal_id"] == GOAL_ID, route
    assert_public_safe(started)

    # 2) worker-loop runs on the same goal from the same workspace directory.
    baseline = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        cwd=workspace,
        max_rounds=1,
    )
    assert baseline["ok"] is True, baseline
    assert baseline["stop_reason"] != "operator_stop_requested", baseline
    assert_public_safe(baseline)

    # 3) The marker in the documented workspace halts that loop before round 1.
    _stop_marker(workspace).write_text("stop", encoding="utf-8")
    stopped = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        cwd=workspace,
        max_rounds=2,
    )
    assert stopped["ok"] is True, stopped
    assert stopped["stop_reason"] == "operator_stop_requested", stopped
    assert stopped["turn_count"] == 0, stopped
    assert_public_safe(stopped)

    # 4) The same marker cannot stop a loop running from another directory;
    #    this is why the walkthrough requires cd "$WORKSPACE" before resuming.
    elsewhere = Path(tempfile.mkdtemp(prefix="loopx-smoke-walkthrough-other-cwd-"))
    from_elsewhere = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        cwd=elsewhere,
        max_rounds=1,
    )
    assert from_elsewhere["ok"] is True, from_elsewhere
    assert from_elsewhere["stop_reason"] != "operator_stop_requested", from_elsewhere
    assert_public_safe(from_elsewhere)

    # 5) Resume: removing the marker lets the loop proceed from $WORKSPACE.
    _stop_marker(workspace).unlink(missing_ok=True)
    resumed = _run_worker_loop(
        registry=registry,
        runtime_root=runtime_root,
        cwd=workspace,
        max_rounds=1,
    )
    assert resumed["ok"] is True, resumed
    assert resumed["stop_reason"] != "operator_stop_requested", resumed
    assert_public_safe(resumed)


def main() -> int:
    test_documented_identity_continuity()
    print("  ok  documented start identity → stop → resume continuity")
    print("auto-research-stop-takeover-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
