"""Split-root fence regressions for the monitor-poll and Turn writebacks.

A promotion engages the legacy writer fence under the CLI ``--runtime-root``
override.  Every Python Todo writeback of the same composition must resolve
its fence and mutex from that same override root, never from the registry's
``common_runtime_root``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.cli_commands.turn import (
    write_turn_repair_update,
    write_turn_validated_completion,
)
from loopx.control_plane.coordination.legacy_writer_fence import (
    LegacyCoordinationWriterFenced,
    legacy_coordination_writer_fence_path,
)
from loopx.control_plane.quota import monitor_poll
from loopx.control_plane.scheduler.monitor_poll_writeback import (
    write_monitor_poll_todo_state,
)

GOAL_ID = "split-root-writeback-goal"
AGENT_ID = "turn-writeback-author"
ADVANCE_ID = "todo_splitroot_advance"
MONITOR_ID = "todo_splitroot_monitor"
OVERRIDE_POLL_HASH = "split-v2"
LEGACY_POLL_HASH = "split-v1"


def _write_split_root_goal(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\n"
        f"goal_id: {GOAL_ID}\n"
        "updated_at: 2026-09-04T00:00:00+00:00\n"
        "---\n\n"
        "## Agent Todo\n\n"
        "- [ ] [P1] Advance the fenced writeback slice.\n"
        "  <!-- loopx:todo "
        f"todo_id={ADVANCE_ID} status=open task_class=advancement_task "
        f"claimed_by={AGENT_ID} -->\n"
        "- [ ] [P2] Watch the fenced writeback channel.\n"
        "  <!-- loopx:todo "
        f"todo_id={MONITOR_ID} status=open task_class=continuous_monitor "
        f"claimed_by={AGENT_ID} target_key=splitroot-review cadence=30m "
        f"result_hash={LEGACY_POLL_HASH} material_change=false -->\n",
        encoding="utf-8",
    )
    runtime_registry = tmp_path / "registry-runtime"
    runtime_override = tmp_path / "override-runtime"
    runtime_registry.mkdir()
    runtime_override.mkdir()
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime_registry),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state, runtime_registry, runtime_override


def _engage_fence_at(runtime_root: Path) -> None:
    fence = legacy_coordination_writer_fence_path(
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
    )
    fence.parent.mkdir(parents=True, exist_ok=True)
    fence.write_text(
        json.dumps({"state": "present", "engaged_by": "promotion"}),
        encoding="utf-8",
    )


def _fence_check_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "loopx.control_plane.coordination.legacy_writer_fence."
        "effect_runtime_result",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "reason_code": "legacy_coordination_writer_fenced",
            "authority_mode": "file_v0",
        },
    )


def _poll_kwargs(
    registry: Path,
    runtime_root: Path,
    *,
    result_hash: str = OVERRIDE_POLL_HASH,
) -> dict[str, Any]:
    return {
        "registry_path": registry,
        "runtime_root": runtime_root,
        "goal_id": GOAL_ID,
        "generated_at": "2026-09-04T01:00:00+00:00",
        "execute": True,
        "todo_id": MONITOR_ID,
        "result_hash": result_hash,
        "material_change": False,
        "next_due_at": "2026-09-04T02:00:00+00:00",
        "agent_id": AGENT_ID,
    }


def test_monitor_poll_writeback_blocked_when_override_root_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, state, _runtime_registry, runtime_override = (
        _write_split_root_goal(tmp_path)
    )
    _engage_fence_at(runtime_override)
    _fence_check_blocks(monkeypatch)
    state_before = state.read_text(encoding="utf-8")

    with pytest.raises(LegacyCoordinationWriterFenced):
        write_monitor_poll_todo_state(**_poll_kwargs(registry, runtime_override))

    assert LEGACY_POLL_HASH in state.read_text(encoding="utf-8")
    assert OVERRIDE_POLL_HASH not in state.read_text(encoding="utf-8")
    assert state.read_text(encoding="utf-8") == state_before


def test_monitor_poll_writeback_allows_when_only_registry_root_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The override root alone decides; a registry-root fence must not block."""

    registry, state, runtime_registry, runtime_override = (
        _write_split_root_goal(tmp_path)
    )
    _engage_fence_at(runtime_registry)
    monkeypatch.setattr(
        "loopx.control_plane.coordination.legacy_writer_fence."
        "effect_runtime_result",
        lambda *_args, **_kwargs: pytest.fail(
            "an override-root writeback must not consult another root's fence"
        ),
    )

    receipt = write_monitor_poll_todo_state(
        **_poll_kwargs(registry, runtime_override)
    )

    assert receipt is not None
    assert receipt["result_hash"] == OVERRIDE_POLL_HASH
    assert receipt["last_checked_at"] == "2026-09-04T01:00:00+00:00"
    active = state.read_text(encoding="utf-8")
    assert f"result_hash={OVERRIDE_POLL_HASH}" in active


def test_quota_monitor_poll_provider_writeback_blocked_under_override_fence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The record path must hand its effective root to the provider writeback."""

    registry, state, _runtime_registry, runtime_override = (
        _write_split_root_goal(tmp_path)
    )
    _engage_fence_at(runtime_override)
    _fence_check_blocks(monkeypatch)

    def native(_method: str, request: dict[str, Any]) -> dict[str, Any]:
        assert request["phase"] == "preflight"
        return {
            "schema_version": monitor_poll.QUOTA_MONITOR_POLL_COMMIT_RESULT_SCHEMA,
            "status": "provider_required",
            "provider_plan": {
                "goal_id": GOAL_ID,
                "generated_at": "2026-09-04T01:00:00+00:00",
                "execute": True,
                "todo_id": MONITOR_ID,
                "result_hash": OVERRIDE_POLL_HASH,
                "material_change": False,
                "next_due_at": "2026-09-04T02:00:00+00:00",
            },
        }

    monkeypatch.setattr(monitor_poll, "effect_runtime_result", native)
    before = {
        "goal_id": GOAL_ID,
        "should_run": False,
        "effective_action": "monitor_quiet_skip",
        "agent_identity": {"agent_id": AGENT_ID},
    }

    with pytest.raises(LegacyCoordinationWriterFenced):
        monitor_poll.record_quota_monitor_poll_for_decision(
            before,
            {"runtime_root": str(runtime_override)},
            goal_id=GOAL_ID,
            after_decision=lambda _status: before,
            render_markdown=lambda _record: "unused",
            registry_path=registry,
            execute=True,
            todo_id=MONITOR_ID,
            result_hash=OVERRIDE_POLL_HASH,
            agent_id=AGENT_ID,
        )

    assert OVERRIDE_POLL_HASH not in state.read_text(encoding="utf-8")


def test_turn_repair_update_blocked_when_override_root_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _state, _runtime_registry, runtime_override = (
        _write_split_root_goal(tmp_path)
    )
    _engage_fence_at(runtime_override)
    _fence_check_blocks(monkeypatch)

    with pytest.raises(LegacyCoordinationWriterFenced):
        write_turn_repair_update(
            registry_path=registry,
            runtime_root_arg=str(runtime_override),
            goal_id=GOAL_ID,
            todo_id=ADVANCE_ID,
            note="host repair reported a bounded retry",
            evidence="LoopX Turn repair_required: rerun the slice",
            agent_id=AGENT_ID,
        )


def test_turn_validated_completion_blocked_when_override_root_is_fenced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, _state, _runtime_registry, runtime_override = (
        _write_split_root_goal(tmp_path)
    )
    _engage_fence_at(runtime_override)
    _fence_check_blocks(monkeypatch)

    with pytest.raises(LegacyCoordinationWriterFenced):
        write_turn_validated_completion(
            registry_path=registry,
            runtime_root_arg=str(runtime_override),
            goal_id=GOAL_ID,
            todo_id=ADVANCE_ID,
            completion_turn_key="turn_splitroot_0001",
            evidence="LoopX Turn validated completion: slice merged",
            note="advance to the next bounded slice",
            agent_id=AGENT_ID,
        )
