"""Per-goal handoff-mode gate over the soft-claim / hard-lease split brain.

Modes (goal front-matter ``handoff_mode``):

* absent / ``legacy``: today's dual behavior, byte-for-byte. The split-brain
  hole stays open BY DESIGN; the legacy tests below are characterization pins
  that document it, not aspirations.
* ``soft_claim``: markdown claim is the only ownership record; task-lease
  acquire/renew/transfer are typed-rejected, release/inspect stay allowed.
* ``hard_lease``: ownership changes on an existing todo require the actor to
  hold that todo's time-active lease; completion fence is mandatory and the
  legacy self-disarm state becomes a loud typed error. The delegated
  ``todo_lifecycle_authority`` override is the one audited door through the
  gate.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane.todos.handoff_mode import (
    HANDOFF_MODE_HARD_LEASE,
    HANDOFF_MODE_LEGACY,
    HANDOFF_MODE_SOFT_CLAIM,
    HandoffModeError,
    goal_handoff_mode,
)
from loopx.control_plane.work_items import task_lease
from loopx.control_plane.work_items.task_lease import (
    TaskLeaseError,
    acquire_task_lease,
    build_lease,
    hold_handoff_lease_holder_gate,
    inspect_task_lease,
    release_task_lease,
    renew_task_lease,
    task_lease_path,
    transfer_task_lease,
    write_lease,
)
from loopx.status import parse_active_state_todos
from loopx.todos import add_goal_todo, complete_goal_todo, update_goal_todo

GOAL_ID = "handoff-mode-gate"
AGENT_A = "agent-a"
AGENT_B = "agent-b"
ORCHESTRATOR = "agent-orchestrator"


def _write_workspace(
    tmp_path: Path,
    *,
    handoff_mode: str | None = None,
    lifecycle_authority: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    state = repo / "ACTIVE_GOAL_STATE.md"
    front_matter = [
        "---",
        f"goal_id: {GOAL_ID}",
        "updated_at: 2026-08-01T00:00:00+00:00",
    ]
    if handoff_mode is not None:
        front_matter.append(f"handoff_mode: {handoff_mode}")
    front_matter.append("---")
    state.write_text(
        "\n".join([*front_matter, "", "## Agent Todo", ""]) + "\n",
        encoding="utf-8",
    )
    coordination: dict[str, Any] = {
        "agent_model": "peer_v1",
        "registered_agents": [AGENT_A, AGENT_B, ORCHESTRATOR],
    }
    if lifecycle_authority is not None:
        coordination["todo_lifecycle_authority"] = lifecycle_authority
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": coordination,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state


def _set_frontmatter_mode(state: Path, mode: str) -> None:
    """Hand-edit the front-matter mode (simulates the out-of-contract path)."""

    lines = state.read_text(encoding="utf-8").splitlines()
    close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    for index in range(1, close):
        if lines[index].split(":", 1)[0].strip() == "handoff_mode":
            lines[index] = f"handoff_mode: {mode}"
            break
    else:
        lines.insert(close, f"handoff_mode: {mode}")
    state.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_todo(registry: Path, *, claimed_by: str | None = None) -> dict[str, Any]:
    return add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Deliver one bounded control-plane change.",
        task_class="advancement_task",
        claimed_by=claimed_by,
    )


def _agent_todo(state: Path, todo_id: str) -> dict[str, Any]:
    todos = parse_active_state_todos(state.read_text(encoding="utf-8"))
    return next(
        item
        for item in todos["agent_todos"]["items"]
        if item["todo_id"] == todo_id
    )


def _acquire(
    registry: Path,
    tmp_path: Path,
    todo_id: str,
    *,
    owner: str,
    key: str = "turn-lease-1",
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    return acquire_task_lease(
        registry_path=registry,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo_id,
        owner=owner,
        idempotency_key=key,
        ttl_seconds=ttl_seconds,
    )


def _claim(registry: Path, todo_id: str, agent: str, **kwargs: Any) -> dict[str, Any]:
    return update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo_id,
        claimed_by=agent,
        agent_id=agent,
        claim_only=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Mode reader
# ---------------------------------------------------------------------------


def test_goal_handoff_mode_defaults_to_legacy_when_absent() -> None:
    text = "---\ngoal_id: g\n---\n\n## Agent Todo\n"
    assert goal_handoff_mode(text) == HANDOFF_MODE_LEGACY


def test_goal_handoff_mode_reads_explicit_values() -> None:
    for mode in (HANDOFF_MODE_LEGACY, HANDOFF_MODE_SOFT_CLAIM, HANDOFF_MODE_HARD_LEASE):
        text = f"---\ngoal_id: g\nhandoff_mode: {mode}\n---\n"
        assert goal_handoff_mode(text) == mode


def test_goal_handoff_mode_rejects_unknown_value_loudly() -> None:
    with pytest.raises(HandoffModeError) as error:
        goal_handoff_mode("---\ngoal_id: g\nhandoff_mode: banana\n---\n")

    assert error.value.code == "invalid_handoff_mode"


def test_goal_handoff_mode_without_frontmatter_is_legacy() -> None:
    assert goal_handoff_mode("## Agent Todo\n") == HANDOFF_MODE_LEGACY


# ---------------------------------------------------------------------------
# (a) Legacy characterization pins: the split-brain hole stays open, loudly.
# ---------------------------------------------------------------------------


def test_legacy_pin_claim_over_foreign_active_lease_silently_succeeds(
    tmp_path: Path,
) -> None:
    """S1 pin: soft claim never reads the lease store, so two owners coexist."""

    registry, state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    result = _claim(registry, todo["todo_id"], AGENT_B)

    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_LEGACY
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_B
    lease_file = task_lease_path(
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    lease = json.loads(lease_file.read_text(encoding="utf-8"))
    assert lease["owner"] == AGENT_A
    assert lease["status"] == "active"


def test_legacy_pin_foreign_claim_makes_lease_renew_fail_typed(
    tmp_path: Path,
) -> None:
    registry, _state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _claim(registry, todo["todo_id"], AGENT_B)

    with pytest.raises(TaskLeaseError) as error:
        renew_task_lease(
            registry_path=registry,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            owner=AGENT_A,
            idempotency_key="turn-lease-1",
        )

    assert error.value.code == "owner_conflicts_with_claim"


def test_legacy_pin_fence_self_disarms_and_claimant_completes_keyless(
    tmp_path: Path,
) -> None:
    """The completion fence disarms itself in the split-brain state: the
    markdown claimant completes WITHOUT any lease credentials while the
    foreign lease sits on disk status=active."""

    registry, _state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _claim(registry, todo["todo_id"], AGENT_B)

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_B,
        evidence="done without lease credentials",
    )

    assert result["ok"] is True
    assert result["task_lease_fence"] == {
        "schema_version": "task_lease_v0",
        "required": False,
        "active": False,
    }
    assert result["handoff_mode"] == HANDOFF_MODE_LEGACY
    lease_file = task_lease_path(
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    assert json.loads(lease_file.read_text(encoding="utf-8"))["status"] == "active"


def test_legacy_pin_lease_holder_cannot_complete_after_foreign_claim(
    tmp_path: Path,
) -> None:
    registry, _state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _claim(registry, todo["todo_id"], AGENT_B)

    with pytest.raises(ValueError, match="cannot complete"):
        complete_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            agent_id=AGENT_A,
            task_lease_idempotency_key="turn-lease-1",
        )


def test_legacy_lease_verbs_report_handoff_mode(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path)
    todo = _add_todo(registry)

    acquired = _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    assert acquired["handoff_mode"] == HANDOFF_MODE_LEGACY

    inspected = inspect_task_lease(
        registry_path=registry,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    assert inspected["handoff_mode"] == HANDOFF_MODE_LEGACY


# ---------------------------------------------------------------------------
# (b) soft_claim: markdown claim only; lease mutations typed-rejected.
# ---------------------------------------------------------------------------


def test_soft_claim_rejects_lease_acquire(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_SOFT_CLAIM)
    todo = _add_todo(registry)

    with pytest.raises(TaskLeaseError) as error:
        _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    assert error.value.code == "handoff_mode_forbids_lease"
    assert error.value.payload["handoff_mode"] == HANDOFF_MODE_SOFT_CLAIM


def test_soft_claim_rejects_renew_and_transfer_of_legacy_leftover(
    tmp_path: Path,
) -> None:
    registry, state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _set_frontmatter_mode(state, HANDOFF_MODE_SOFT_CLAIM)

    with pytest.raises(TaskLeaseError) as renew_error:
        renew_task_lease(
            registry_path=registry,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            owner=AGENT_A,
            idempotency_key="turn-lease-1",
        )
    assert renew_error.value.code == "handoff_mode_forbids_lease"

    with pytest.raises(TaskLeaseError) as transfer_error:
        transfer_task_lease(
            registry_path=registry,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            owner=AGENT_A,
            idempotency_key="turn-lease-1",
            new_owner=AGENT_B,
            new_idempotency_key="turn-lease-2",
        )
    assert transfer_error.value.code == "handoff_mode_forbids_lease"


def test_soft_claim_allows_release_and_inspect_of_legacy_leftover(
    tmp_path: Path,
) -> None:
    registry, state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _set_frontmatter_mode(state, HANDOFF_MODE_SOFT_CLAIM)

    inspected = inspect_task_lease(
        registry_path=registry,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    assert inspected["ok"] is True
    assert inspected["handoff_mode"] == HANDOFF_MODE_SOFT_CLAIM

    released = release_task_lease(
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        owner=AGENT_A,
        idempotency_key="turn-lease-1",
        registry_path=registry,
    )
    assert released["ok"] is True
    assert released["released"] is True


def test_soft_claim_todo_verbs_behave_like_legacy(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_SOFT_CLAIM)
    todo = _add_todo(registry)

    claim = _claim(registry, todo["todo_id"], AGENT_B)
    assert claim["ok"] is True
    assert claim["handoff_mode"] == HANDOFF_MODE_SOFT_CLAIM
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_B

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_B,
        evidence="soft mode keyless completion",
    )
    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_SOFT_CLAIM
    assert result["task_lease_fence"]["required"] is False


# ---------------------------------------------------------------------------
# (c) hard_lease: ownership mutations require the actor to hold the lease.
# ---------------------------------------------------------------------------


def test_hard_lease_claim_without_lease_is_typed_rejected(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    before = state.read_text(encoding="utf-8")

    with pytest.raises(TaskLeaseError) as error:
        _claim(registry, todo["todo_id"], AGENT_B)

    assert error.value.code == "handoff_mode_requires_lease"
    assert error.value.payload["handoff_mode"] == HANDOFF_MODE_HARD_LEASE
    assert state.read_text(encoding="utf-8") == before


def test_hard_lease_claim_by_non_owner_is_typed_rejected(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    before = state.read_text(encoding="utf-8")

    with pytest.raises(TaskLeaseError) as error:
        _claim(registry, todo["todo_id"], AGENT_B)

    assert error.value.code == "handoff_mode_requires_lease"
    assert error.value.payload["lease_owner"] == AGENT_A
    assert state.read_text(encoding="utf-8") == before


def test_hard_lease_holder_claim_succeeds(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    result = _claim(registry, todo["todo_id"], AGENT_A)

    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_HARD_LEASE
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_A


def test_hard_lease_expired_lease_does_not_authorize_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A, ttl_seconds=60)
    real_now = task_lease.now_utc()
    monkeypatch.setattr(task_lease, "now_utc", lambda: real_now + timedelta(hours=2))

    with pytest.raises(TaskLeaseError) as error:
        _claim(registry, todo["todo_id"], AGENT_A)

    assert error.value.code == "handoff_mode_requires_lease"


def test_hard_lease_clear_claim_requires_lease(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)

    with pytest.raises(TaskLeaseError) as error:
        update_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            agent_id=AGENT_A,
            clear_claim=True,
        )
    assert error.value.code == "handoff_mode_requires_lease"

    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_A,
        clear_claim=True,
    )
    assert result["ok"] is True
    assert not _agent_todo(state, todo["todo_id"]).get("claimed_by")


def test_hard_lease_claimed_by_update_requires_lease(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)

    with pytest.raises(TaskLeaseError) as error:
        update_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            claimed_by=AGENT_A,
            agent_id=AGENT_A,
            note="keep ownership, add note",
        )

    assert error.value.code == "handoff_mode_requires_lease"


def test_hard_lease_non_ownership_update_needs_no_lease(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)

    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_B,
        note="metadata-only update",
    )

    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_HARD_LEASE


def test_hard_lease_creation_time_assignment_stays_allowed(tmp_path: Path) -> None:
    """A fresh todo id can never hold a lease; add --claimed-by is a
    deliberate boundary that stays open in hard_lease mode."""

    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)

    todo = _add_todo(registry, claimed_by=AGENT_A)

    assert todo["ok"] is True
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_A


def test_hard_lease_completion_successor_assignment_stays_allowed(
    tmp_path: Path,
) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_A,
        task_lease_idempotency_key="turn-lease-1",
        evidence="done with verified lease key",
        next_agent_todo="Follow-up slice for the peer lane.",
        next_claimed_by=AGENT_B,
    )

    assert result["ok"] is True
    successor_id = result["next_todos"][0]["todo_id"]
    assert _agent_todo(state, successor_id)["claimed_by"] == AGENT_B


def test_hard_lease_completion_without_lease_is_typed_rejected(
    tmp_path: Path,
) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)

    with pytest.raises(TaskLeaseError) as error:
        complete_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            agent_id=AGENT_A,
            evidence="no lease exists",
        )

    assert error.value.code == "handoff_mode_requires_lease"
    assert error.value.payload["handoff_mode"] == HANDOFF_MODE_HARD_LEASE


def test_hard_lease_completion_with_verified_key_succeeds(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=AGENT_A,
        task_lease_idempotency_key="turn-lease-1",
        evidence="done with verified lease key",
    )

    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_HARD_LEASE
    assert result["task_lease_fence"]["required"] is True
    assert result["task_lease_fence"]["execution_instance_verified"] is True


def test_hard_lease_self_disarm_state_becomes_loud_typed_error(
    tmp_path: Path,
) -> None:
    """Legacy remnants or manual edits can leave claimed_by diverged from a
    time-active lease. In hard_lease mode that must fail loudly instead of
    silently completing keyless."""

    registry, state = _write_workspace(tmp_path)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)
    _claim(registry, todo["todo_id"], AGENT_B)
    _set_frontmatter_mode(state, HANDOFF_MODE_HARD_LEASE)

    with pytest.raises(TaskLeaseError) as error:
        complete_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            agent_id=AGENT_B,
            evidence="split-brain keyless completion attempt",
        )

    assert error.value.code == "handoff_mode_lease_claim_divergence"
    assert error.value.payload["lease_owner"] == AGENT_A


# ---------------------------------------------------------------------------
# (d) the door: delegated todo_lifecycle_authority passes the hard gate.
# ---------------------------------------------------------------------------


def _orchestrator_grant() -> list[dict[str, Any]]:
    return [
        {
            "agent_id": ORCHESTRATOR,
            "actions": ["reassign", "update", "complete"],
            "requires_reason": True,
        }
    ]


def test_hard_lease_delegated_reassign_passes_gate_with_marker(
    tmp_path: Path,
) -> None:
    registry, state = _write_workspace(
        tmp_path,
        handoff_mode=HANDOFF_MODE_HARD_LEASE,
        lifecycle_authority=_orchestrator_grant(),
    )
    todo = _add_todo(registry, claimed_by=AGENT_A)

    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        claimed_by=AGENT_B,
        agent_id=ORCHESTRATOR,
        authority_reason="peer lane is stalled; reassigning",
    )

    assert result["ok"] is True
    assert result["handoff_mode"] == HANDOFF_MODE_HARD_LEASE
    assert result["handoff_gate_overridden"] is True
    assert result["mutation_authority"]["mode"] == "delegated_orchestration_override"
    assert (
        result["mutation_authority"]["authority_reason"]
        == "peer lane is stalled; reassigning"
    )
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_B


def test_hard_lease_delegated_complete_passes_gate_with_marker(
    tmp_path: Path,
) -> None:
    registry, _state = _write_workspace(
        tmp_path,
        handoff_mode=HANDOFF_MODE_HARD_LEASE,
        lifecycle_authority=_orchestrator_grant(),
    )
    todo = _add_todo(registry, claimed_by=AGENT_A)

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        agent_id=ORCHESTRATOR,
        authority_reason="closing stalled item for the goal owner",
        evidence="delegated completion",
    )

    assert result["ok"] is True
    assert result["handoff_gate_overridden"] is True
    assert result["task_lease_fence"]["required"] is False


def test_hard_lease_gate_has_no_untyped_bypass_without_grant(
    tmp_path: Path,
) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry, claimed_by=AGENT_A)

    with pytest.raises(ValueError):
        update_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            claimed_by=AGENT_B,
            agent_id=ORCHESTRATOR,
            authority_reason="no grant exists for this actor",
        )


# ---------------------------------------------------------------------------
# (f) identity normalization on both sides of the holder check.
# ---------------------------------------------------------------------------


def test_hard_lease_holder_check_normalizes_both_sides(tmp_path: Path) -> None:
    registry, state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    _acquire(registry, tmp_path, todo["todo_id"], owner=AGENT_A)

    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        claimed_by=" Agent-A ",
        agent_id="AGENT-A",
        claim_only=True,
    )

    assert result["ok"] is True
    assert _agent_todo(state, todo["todo_id"])["claimed_by"] == AGENT_A


def test_holder_gate_normalizes_lease_owner_case_variants(tmp_path: Path) -> None:
    registry, _state = _write_workspace(tmp_path, handoff_mode=HANDOFF_MODE_HARD_LEASE)
    todo = _add_todo(registry)
    lease_file = task_lease_path(
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    now = task_lease.now_utc()
    write_lease(
        lease_file,
        build_lease(
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
            owner="Agent-A",
            idempotency_key="turn-lease-1",
            write_scopes=[],
            acquire_ttl_seconds=600,
            version=1,
            acquired_at=task_lease.isoformat(now),
            updated_at=task_lease.isoformat(now),
            expires_at=task_lease.isoformat(now + timedelta(seconds=600)),
        ),
    )

    with ExitStack() as stack:
        gate = stack.enter_context(
            hold_handoff_lease_holder_gate(
                registry_path=registry,
                goal_id=GOAL_ID,
                todo_id=todo["todo_id"],
                actor_agent_id=" agent-a ",
            )
        )
        assert gate["active"] is True
        assert gate["owner"] == AGENT_A
