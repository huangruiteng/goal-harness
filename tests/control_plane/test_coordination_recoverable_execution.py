"""Stage 3 recoverable execution ownership over the shared coordination head.

The horizon contract (RFC section 1.2): renew, release, expired-lease
reclaim, stale-fence rejection, and atomic completion with an accepted
continuation/evidence pointer - proven by crash and clock-boundary tests
showing that a superseded executor cannot write back. Every domain decision
is delegated to the Stage 1 core; the executor owns expiry adjudication
(its clock, the loaded head's expires_at, plus the reclaim grace window),
the store-lineage binding fence, and the aggregate writeback.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pytest

from loopx.control_plane.coordination.executor import (
    CoordinationAuthorityExecutor,
    EnvelopeError,
    sample_claim_envelope,
    sample_work_envelope,
)
from loopx.control_plane.coordination.head import (
    HeadMigrationRequired,
    HeadValidationError,
    bootstrap_head,
    head_digest,
    migrate_head_v0_to_v1,
    validated_head,
)
from loopx.control_plane.todos.durable_completion import (
    project_durable_completion_outcome,
)


def eligibility(allowed=("agent-a", "agent-b")) -> dict:
    return {
        "authorization_projection_revision": 3,
        "authorization_projection_digest": "sha256:bootstrap-auth",
        "allowed_agent_ids": list(allowed),
        "dependencies_satisfied": True,
        "dependency_revision": 12,
        "gates_open": True,
        "gate_revision": 5,
    }


def todo(**overrides) -> dict:
    base = {
        "todo_revision": 7,
        "status": "open",
        "claimed_by": None,
        "eligibility": eligibility(),
        "repository": "git:example/repo",
        "code_revision": "0123456789abcdef",
        "last_lease_epoch": 6,
    }
    base.update(overrides)
    return base


class FakeProvider:
    def __init__(self):
        self._head = None
        self._generation = 0
        self._lock = threading.Lock()
        self.identity = "test:store"

    def store_identity(self) -> str:
        return self.identity

    def load(self):
        with self._lock:
            return copy.deepcopy(self._head), self._generation

    def compare_and_put(self, expected_generation, head):
        with self._lock:
            if expected_generation != self._generation:
                return {
                    "result": "conflict",
                    "current_provider_generation": self._generation,
                }
            self._head = copy.deepcopy(head)
            self._generation += 1
            return {"result": "applied", "provider_generation": self._generation}


class Clock:
    def __init__(self, value: float = 1_800_000_000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


PRECONDITIONS = {
    "authorization_projection_revision": 3,
    "authorization_projection_digest": "sha256:bootstrap-auth",
    "dependency_revision": 12,
    "gate_revision": 5,
}


def bootstrap(provider, todos=("todo-1", "todo-2")) -> dict:
    head = bootstrap_head(
        "goal-a",
        {todo_id: todo() for todo_id in todos},
        store_binding=provider.store_identity(),
    )
    assert provider.compare_and_put(0, head)["result"] == "applied"
    return head


def executor_for(provider, clock, **kwargs) -> CoordinationAuthorityExecutor:
    return CoordinationAuthorityExecutor(
        provider, goal_id="goal-a", now=clock, **kwargs
    )


def claim(executor, agent, todo_id, operation_id, *, revision=7, ttl=600):
    return executor.apply(sample_claim_envelope(
        goal_id="goal-a", operation_id=operation_id, agent_id=agent,
        device_id=f"dev-{agent}", todo_id=todo_id,
        expected_todo_revision=revision,
        expected_preconditions=copy.deepcopy(PRECONDITIONS),
        lease_ttl_seconds=ttl,
    ))


def verb(executor, agent, operation_id, command):
    return executor.apply(sample_work_envelope(
        goal_id="goal-a", operation_id=operation_id, agent_id=agent,
        device_id=f"dev-{agent}", command=command,
    ))


def claimed_fixture(ttl=600):
    """provider, clock, executor, and the fence from a fresh claim."""

    provider = FakeProvider()
    bootstrap(provider)
    clock = Clock()
    executor = executor_for(provider, clock)
    first = claim(executor, "agent-a", "todo-1", "op-claim", ttl=ttl)
    assert first["result"] == "applied", first
    receipt = first["original_receipt"]
    fence = {"lease_id": receipt["lease_id"], "lease_epoch": receipt["lease_epoch"]}
    return provider, clock, executor, fence


def head_of(provider):
    head, _generation = provider.load()
    return head


# ---- renew ------------------------------------------------------------------


def test_renew_extends_expiry_without_minting_a_new_epoch() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    before = head_of(provider)
    clock.value += 500
    renewed = verb(executor, "agent-a", "op-renew", {
        "type": "renew_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert renewed["result"] == "applied", renewed
    head = head_of(provider)
    lease = head["coordination"]["leases"]["todo-1"]
    assert lease["lease_epoch"] == fence["lease_epoch"]
    assert lease["lease_id"] == fence["lease_id"]
    assert lease["expires_at"] > before["coordination"]["leases"]["todo-1"]["expires_at"]
    # Renewal advances todo_revision: the validity interval is a revision-
    # covered fact, so a reclaim carrying pre-renew observations conflicts
    # instead of surviving the internal rebase (RFC section 6.4).
    assert head["coordination"]["todos"]["todo-1"]["todo_revision"] == 9
    assert renewed["original_receipt"]["command"] == "renew_work"
    validated_head(head, goal_id="goal-a")

    replay = verb(executor, "agent-a", "op-renew", {
        "type": "renew_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert replay["result"] == "already_applied"
    assert replay["original_receipt"] == renewed["original_receipt"]


def test_renew_of_an_expired_lease_is_rejected() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 601
    rejected = verb(executor, "agent-a", "op-late-renew", {
        "type": "renew_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "lease_not_active"


def test_renew_by_a_non_holder_is_rejected() -> None:
    provider, clock, executor, fence = claimed_fixture()
    rejected = verb(executor, "agent-b", "op-steal-renew", {
        "type": "renew_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "not_lease_holder"


def test_renew_with_a_wrong_fence_is_a_stale_fence() -> None:
    provider, clock, executor, fence = claimed_fixture()
    rejected = verb(executor, "agent-a", "op-bad-fence", {
        "type": "renew_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": "lease_forged",
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "stale_lease_fence"


# ---- release ----------------------------------------------------------------


def test_release_clears_claim_and_keeps_the_epoch_watermark() -> None:
    provider, clock, executor, fence = claimed_fixture()
    released = verb(executor, "agent-a", "op-release", {
        "type": "release_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
    })
    assert released["result"] == "applied", released
    head = head_of(provider)
    record = head["coordination"]["todos"]["todo-1"]
    assert record["claimed_by"] is None and record["status"] == "open"
    assert record["last_lease_epoch"] == fence["lease_epoch"]
    assert "todo-1" not in head["coordination"]["leases"]
    validated_head(head, goal_id="goal-a")

    # No-ABA across release: the next claim mints strictly above the
    # watermark even though the lease record is gone.
    reclaimed = claim(executor, "agent-b", "todo-1", "op-reclaim-after-release",
                      revision=9)
    assert reclaimed["result"] == "applied"
    assert (
        reclaimed["original_receipt"]["lease_epoch"] == fence["lease_epoch"] + 1
    )


def test_release_of_an_expired_lease_is_rejected() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 601
    rejected = verb(executor, "agent-a", "op-late-release", {
        "type": "release_work", "todo_id": "todo-1",
        "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
    })
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "lease_not_active"


# ---- reclaim and the clock boundary -----------------------------------------


def reclaim_command(revision=9):
    return {
        "type": "reclaim_work", "todo_id": "todo-1",
        "expected_todo_revision": revision,
        "expected_preconditions": copy.deepcopy(PRECONDITIONS),
        "lease_ttl_seconds": 600,
    }


def test_reclaim_honors_the_grace_window_clock_boundaries() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    base = clock.value

    # Active lease: not reclaimable.
    clock.value = base + 300
    active = verb(executor, "agent-b", "op-r1", reclaim_command(revision=8))
    assert active["result"] == "rejected"
    assert active["reason"] == "lease_not_reclaimable"

    # Exactly at expiry: expired, but inside the grace window.
    clock.value = base + 600
    at_expiry = verb(executor, "agent-b", "op-r2", reclaim_command(revision=8))
    assert at_expiry["result"] == "rejected"
    assert at_expiry["reason"] == "lease_not_reclaimable"

    # One tick before the grace elapses: still not reclaimable.
    clock.value = base + 600 + 29.999
    inside_grace = verb(executor, "agent-b", "op-r3", reclaim_command(revision=8))
    assert inside_grace["result"] == "rejected"
    assert inside_grace["reason"] == "lease_not_reclaimable"

    # At expiry plus the full grace: reclaimable.
    clock.value = base + 600 + 30.0
    reclaimed = verb(executor, "agent-b", "op-r4", reclaim_command(revision=8))
    assert reclaimed["result"] == "applied", reclaimed
    receipt = reclaimed["original_receipt"]
    assert receipt["command"] == "reclaim_work"
    assert receipt["lease_epoch"] == fence["lease_epoch"] + 1
    assert receipt["superseded_owner"] == "agent-a"
    assert receipt["superseded_lease_epoch"] == fence["lease_epoch"]
    head = head_of(provider)
    record = head["coordination"]["todos"]["todo-1"]
    assert record["claimed_by"] == "agent-b"
    assert record["last_lease_epoch"] == fence["lease_epoch"] + 1
    assert head["coordination"]["leases"]["todo-1"]["owner"] == "agent-b"
    validated_head(head, goal_id="goal-a")


def test_reclaim_grace_is_configurable_and_recorded() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    clock = Clock()
    executor = executor_for(provider, clock, reclaim_grace_seconds=5.0)
    first = claim(executor, "agent-a", "todo-1", "op-claim", ttl=100)
    assert first["result"] == "applied"
    clock.value += 104.9
    early = verb(executor, "agent-b", "op-early", reclaim_command(revision=8))
    assert early["reason"] == "lease_not_reclaimable"
    assert early["reclaim_grace_seconds"] == 5.0
    clock.value += 0.1
    assert verb(executor, "agent-b", "op-take", reclaim_command(revision=8))[
        "result"
    ] == "applied"


def test_reclaim_of_an_unclaimed_todo_points_to_claim_work() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider, Clock())
    rejected = verb(executor, "agent-b", "op-noclaim", reclaim_command(revision=7))
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "todo_not_claimed"


def test_reclaim_by_an_ineligible_actor_is_rejected() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 700
    rejected = verb(executor, "agent-z", "op-outsider", reclaim_command(revision=8))
    assert rejected["result"] == "rejected"
    assert rejected["reason"] == "actor_ineligible"


def test_reclaim_with_stale_preconditions_conflicts() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 700
    command = reclaim_command(revision=8)
    command["expected_preconditions"]["gate_revision"] = 4
    stale = verb(executor, "agent-b", "op-stale-pre", command)
    assert stale["result"] == "conflict"
    assert stale["reason"] == "precondition_snapshot_mismatch"


# ---- the superseded executor cannot write back ------------------------------


def test_superseded_executor_writes_are_fenced_terminally() -> None:
    """The Stage 3 horizon proof: after a reclaim, every write the old
    holder sends with its old fence is a typed stale_lease_fence rejection
    that never rebases past, and the head is untouched by any of them."""

    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 700
    reclaimed = verb(executor, "agent-b", "op-take", reclaim_command(revision=8))
    assert reclaimed["result"] == "applied"
    settled = provider.load()

    stale_fence = {
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
    }
    stale_writes = [
        ("op-a-renew", {"type": "renew_work", "todo_id": "todo-1",
                        "expected_todo_revision": 9, **stale_fence,
                        "lease_ttl_seconds": 600}),
        ("op-a-release", {"type": "release_work", "todo_id": "todo-1",
                          "expected_todo_revision": 9, **stale_fence}),
        ("op-a-complete", {"type": "complete_work", "todo_id": "todo-1",
                           "expected_todo_revision": 9, **stale_fence,
                           "no_followup": False, "successor_todo_ids": [],
                           "evidence": None}),
    ]
    for operation_id, command in stale_writes:
        outcome = verb(executor, "agent-a", operation_id, command)
        assert outcome["result"] == "rejected", (operation_id, outcome)
        assert outcome["reason"] == "stale_lease_fence", (operation_id, outcome)
    assert provider.load() == settled

    # The old holder cannot even re-claim: the todo is claimed by agent-b.
    retry = claim(executor, "agent-a", "todo-1", "op-a-retry", revision=9)
    assert retry["result"] == "rejected"
    assert retry["reason"] == "todo_not_open"


# ---- completion -------------------------------------------------------------


def complete_command(*, revision, fence, no_followup=False, successors=(),
                     evidence=None):
    return {
        "type": "complete_work", "todo_id": "todo-1",
        "expected_todo_revision": revision,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "no_followup": no_followup,
        "successor_todo_ids": list(successors),
        "evidence": evidence,
    }


def test_complete_with_successor_is_one_atomic_transition() -> None:
    provider, clock, executor, fence = claimed_fixture()
    evidence = {
        "pointer": "artifact://public/runs/run-1/report",
        "digest": "sha256:" + "a" * 64,
        "privacy_class": "public",
    }
    done = verb(executor, "agent-a", "op-done", complete_command(
        revision=8, fence=fence, successors=("todo_next01",), evidence=evidence,
    ))
    assert done["result"] == "applied", done
    assert done["original_receipt"]["completion_continuation"] == "successor"
    head = head_of(provider)
    record = head["coordination"]["todos"]["todo-1"]
    assert record["status"] == "done"
    assert record["claimed_by"] == "agent-a"
    assert record["completion_continuation"] == "successor"
    assert record["successor_todo_ids"] == ["todo_next01"]
    assert record["evidence"] == evidence
    assert "todo-1" not in head["coordination"]["leases"]
    successor = head["coordination"]["todos"]["todo_next01"]
    assert successor["status"] == "open" and successor["claimed_by"] is None
    assert successor["todo_revision"] == 0 and successor["last_lease_epoch"] == 0
    assert successor["eligibility"] == record["eligibility"]
    validated_head(head, goal_id="goal-a")

    # The successor is immediately claimable in the same shared head.
    follow = claim(executor, "agent-b", "todo_next01", "op-follow", revision=0)
    assert follow["result"] == "applied"


def test_completed_record_projects_through_the_production_seam() -> None:
    """The shared head's done records satisfy the local durable-completion
    projection exactly - the read-side seam both worlds share. The seam
    accepts public todo ids only, so this chain uses them throughout (as
    bootstrap_head_from_goal_state does for every real migration)."""

    provider = FakeProvider()
    head = bootstrap_head(
        "goal-a", {"todo_parent01": todo()},
        store_binding=provider.store_identity(),
    )
    assert provider.compare_and_put(0, head)["result"] == "applied"
    clock = Clock()
    executor = executor_for(provider, clock)
    first = claim(executor, "agent-a", "todo_parent01", "op-claim")
    assert first["result"] == "applied"
    receipt = first["original_receipt"]
    done = verb(executor, "agent-a", "op-done", {
        "type": "complete_work", "todo_id": "todo_parent01",
        "expected_todo_revision": 8,
        "lease_id": receipt["lease_id"],
        "expected_lease_epoch": receipt["lease_epoch"],
        "no_followup": False, "successor_todo_ids": ["todo_next01"],
        "evidence": None,
    })
    assert done["result"] == "applied", done
    todos = head_of(provider)["coordination"]["todos"]
    outcome = project_durable_completion_outcome(
        todo={"todo_id": "todo_parent01", **todos["todo_parent01"]},
        expected_todo_id="todo_parent01",
        existing_todo_ids=set(todos),
    )
    assert outcome == {
        "todo_id": "todo_parent01",
        "continuation": "successor",
        "successor_todo_ids": ["todo_next01"],
    }


def test_complete_no_followup_and_active_goal_paths() -> None:
    provider, clock, executor, fence = claimed_fixture()
    done = verb(executor, "agent-a", "op-done", complete_command(
        revision=8, fence=fence, no_followup=True,
    ))
    assert done["result"] == "applied"
    record = head_of(provider)["coordination"]["todos"]["todo-1"]
    assert record["completion_continuation"] == "no_followup"
    assert record["no_followup"] is True

    second = claim(executor, "agent-b", "todo-2", "op-c2")
    fence2 = {
        "lease_id": second["original_receipt"]["lease_id"],
        "lease_epoch": second["original_receipt"]["lease_epoch"],
    }
    active_goal = verb(executor, "agent-b", "op-done-2", {
        "type": "complete_work", "todo_id": "todo-2",
        "expected_todo_revision": 8,
        "lease_id": fence2["lease_id"],
        "expected_lease_epoch": fence2["lease_epoch"],
        "no_followup": False, "successor_todo_ids": [], "evidence": None,
    })
    assert active_goal["result"] == "applied"
    record = head_of(provider)["coordination"]["todos"]["todo-2"]
    assert record["completion_continuation"] == "active_goal"
    assert "no_followup" not in record and "successor_todo_ids" not in record
    validated_head(head_of(provider), goal_id="goal-a")


def test_complete_contradiction_and_bad_successors_fail_closed() -> None:
    provider, clock, executor, fence = claimed_fixture()
    with pytest.raises(EnvelopeError, match="cannot record both"):
        verb(executor, "agent-a", "op-both", complete_command(
            revision=8, fence=fence, no_followup=True, successors=("todo_x01",),
        ))
    with pytest.raises(EnvelopeError, match="public todo ids"):
        verb(executor, "agent-a", "op-badid", complete_command(
            revision=8, fence=fence, successors=("Not A Todo",),
        ))
    with pytest.raises(EnvelopeError, match="evidence"):
        verb(executor, "agent-a", "op-badev", complete_command(
            revision=8, fence=fence,
            evidence={"pointer": "x", "digest": "nope", "privacy_class": "p"},
        ))
    # A colliding-but-valid id reaches the semantic rejection (an invalid
    # id like "todo-2" would already fail the envelope pattern above).
    provider2, clock2, executor2, fence2 = claimed_fixture()
    head = head_of(provider2)
    head["coordination"]["todos"]["todo_next01"] = todo(todo_revision=0,
                                                        last_lease_epoch=0)
    assert provider2.compare_and_put(2, head)["result"] == "applied"
    clash = verb(executor2, "agent-a", "op-clash2", complete_command(
        revision=8, fence=fence2, successors=("todo_next01",),
    ))
    assert clash["result"] == "rejected"
    assert clash["reason"] == "successor_todo_exists"


def test_complete_with_an_expired_lease_is_rejected() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    clock.value += 601
    late = verb(executor, "agent-a", "op-late-done", complete_command(
        revision=8, fence=fence,
    ))
    assert late["result"] == "rejected"
    assert late["reason"] == "lease_not_active"


def test_continuation_rule_matches_the_local_facade() -> None:
    """The executor mirrors the TS-owned continuation rule; this pin keeps
    the two from drifting on any input combination."""

    from loopx.control_plane.coordination.executor import _continuation_for_write

    try:
        from loopx.control_plane.todos.completion_state import (
            completion_continuation_for_write,
        )

        facade = {
            (False, False): completion_continuation_for_write(
                no_followup=False, has_successor=False),
            (False, True): completion_continuation_for_write(
                no_followup=False, has_successor=True),
            (True, False): completion_continuation_for_write(
                no_followup=True, has_successor=False),
        }
    except Exception:  # noqa: BLE001 - the TS effect runtime is optional here
        pytest.skip("TypeScript effect runtime unavailable")
    assert facade == {
        (False, False): "active_goal",
        (False, True): "successor",
        (True, False): "no_followup",
    }
    assert _continuation_for_write(no_followup=False, has_successor=False) == "active_goal"
    assert _continuation_for_write(no_followup=False, has_successor=True) == "successor"
    assert _continuation_for_write(no_followup=True, has_successor=False) == "no_followup"
    with pytest.raises(EnvelopeError):
        _continuation_for_write(no_followup=True, has_successor=True)


# ---- the store-lineage binding fence ----------------------------------------


def test_restored_lineage_fails_closed_on_every_verb() -> None:
    provider, clock, executor, fence = claimed_fixture()
    provider.identity = "test:restored-copy"
    for operation_id, envelope_command in [
        ("op-f1", None),  # claim_work via helper below
        ("op-f2", {"type": "renew_work", "todo_id": "todo-1",
                   "expected_todo_revision": 8, **{
                       "lease_id": fence["lease_id"],
                       "expected_lease_epoch": fence["lease_epoch"]},
                   "lease_ttl_seconds": 600}),
        ("op-f3", {"type": "complete_work", "todo_id": "todo-1",
                   "expected_todo_revision": 8,
                   "lease_id": fence["lease_id"],
                   "expected_lease_epoch": fence["lease_epoch"],
                   "no_followup": True, "successor_todo_ids": [],
                   "evidence": None}),
    ]:
        if envelope_command is None:
            outcome = claim(executor, "agent-b", "todo-2", operation_id)
        else:
            outcome = verb(executor, "agent-a", operation_id, envelope_command)
        assert outcome["result"] == "failed", (operation_id, outcome)
        assert outcome["reason"] == "store_lineage_mismatch"
        assert outcome["head_store_binding"] == "test:store"
        assert outcome["provider_store_identity"] == "test:restored-copy"


def test_bootstrap_binds_the_provider_identity() -> None:
    provider = FakeProvider()
    provider.identity = "test:lineage-42"
    head = bootstrap_head(
        "goal-a", {"todo-1": todo()}, store_binding=provider.store_identity()
    )
    assert head["store_binding"] == "test:lineage-42"


# ---- the full recoverable lifecycle -----------------------------------------


def test_full_lifecycle_chain_with_exact_receipt_replay() -> None:
    """claim -> renew -> reclaim (after expiry) -> complete by the new owner,
    with every receipt replayable field-for-field afterwards."""

    provider, clock, executor, fence = claimed_fixture(ttl=600)

    renewed = verb(executor, "agent-a", "op-renew", {
        "type": "renew_work", "todo_id": "todo-1", "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert renewed["result"] == "applied"

    clock.value += 600 + 31
    reclaimed = verb(executor, "agent-b", "op-take", reclaim_command(revision=9))
    assert reclaimed["result"] == "applied"
    new_fence = {
        "lease_id": reclaimed["original_receipt"]["lease_id"],
        "lease_epoch": reclaimed["original_receipt"]["lease_epoch"],
    }

    done = verb(executor, "agent-b", "op-finish", {
        "type": "complete_work", "todo_id": "todo-1",
        "expected_todo_revision": 10,
        "lease_id": new_fence["lease_id"],
        "expected_lease_epoch": new_fence["lease_epoch"],
        "no_followup": False, "successor_todo_ids": ["todo_next01"],
        "evidence": None,
    })
    assert done["result"] == "applied", done

    head = head_of(provider)
    assert head["authority_revision"] == 4
    assert len(head["receipt_index"]) == 4
    validated_head(head, goal_id="goal-a")

    replays = {
        "op-renew": renewed, "op-take": reclaimed, "op-finish": done,
    }
    fresh = executor_for(provider, clock)
    replayed_renew = verb(fresh, "agent-a", "op-renew", {
        "type": "renew_work", "todo_id": "todo-1", "expected_todo_revision": 8,
        "lease_id": fence["lease_id"],
        "expected_lease_epoch": fence["lease_epoch"],
        "lease_ttl_seconds": 600,
    })
    assert replayed_renew["result"] == "already_applied"
    assert replayed_renew["original_receipt"] == renewed["original_receipt"]
    for operation_id, original in replays.items():
        entry = head["receipt_index"][operation_id]["original_receipt"]
        assert entry == original["original_receipt"], operation_id


# ---- reclaim grace configuration boundary -----------------------------------


def test_illegal_reclaim_grace_is_rejected_at_construction() -> None:
    # NaN makes `expired_for < grace` always false (every active lease
    # becomes reclaimable); negative grace advances the takeover before
    # expiry; bool is the classic coercion accident. All fail closed.
    provider = FakeProvider()
    for bad in (
        float("nan"), float("inf"), float("-inf"), -1, -0.001, True, False,
        "30", None, 10**400,
    ):
        with pytest.raises(ValueError):
            executor_for(provider, Clock(), reclaim_grace_seconds=bad)


def test_zero_grace_is_legal_but_never_reclaims_an_active_lease() -> None:
    provider, clock, executor, fence = claimed_fixture(ttl=600)
    zero = executor_for(provider, clock, reclaim_grace_seconds=0)
    # The clock has not advanced: the 600s lease is fully active, and the
    # smallest accepted grace still refuses the takeover.
    grab = verb(zero, "agent-b", "op-grab-active", reclaim_command(revision=8))
    assert grab["result"] == "rejected"
    assert grab["reason"] == "lease_not_reclaimable"
    assert head_of(provider)["coordination"]["leases"]["todo-1"]["owner"] == "agent-a"


# ---- evidence portability boundary ------------------------------------------


GOOD_DIGEST = "sha256:" + "a" * 64


def test_evidence_rejects_host_paths_and_unknown_privacy_classes() -> None:
    provider, clock, executor, fence = claimed_fixture()
    rejected = [
        # The reviewer's exact reproduction: an absolute local path with a
        # typo'd privacy class must never enter the shared head.
        {"pointer": "/private/example/secret.log", "digest": GOOD_DIGEST,
         "privacy_class": "publci"},
        {"pointer": "/private/example/secret.log", "digest": GOOD_DIGEST,
         "privacy_class": "public"},
        {"pointer": "file:///private/example/secret.log",
         "digest": GOOD_DIGEST, "privacy_class": "private"},
        {"pointer": "FILE:///etc/passwd", "digest": GOOD_DIGEST,
         "privacy_class": "private"},
        {"pointer": "c:\\runs\\report.log", "digest": GOOD_DIGEST,
         "privacy_class": "public"},
        {"pointer": "runs/report.log", "digest": GOOD_DIGEST,
         "privacy_class": "public"},
        {"pointer": "~/report.log", "digest": GOOD_DIGEST,
         "privacy_class": "public"},
        {"pointer": "artifact://public/runs/run-1/report", "digest": GOOD_DIGEST,
         "privacy_class": "PUBLIC"},
        {"pointer": "artifact://public/runs/run-1/report", "digest": GOOD_DIGEST,
         "privacy_class": "internal"},
        {"pointer": "artifact://public/runs/run-1/report", "digest": GOOD_DIGEST,
         "privacy_class": ""},
    ]
    for evidence in rejected:
        with pytest.raises(EnvelopeError):
            verb(executor, "agent-a", "op-bad-evidence", complete_command(
                revision=8, fence=fence, evidence=evidence,
            ))
    # Nothing above may have landed: the todo is still open and claimed.
    head = head_of(provider)
    assert head["coordination"]["todos"]["todo-1"]["status"] == "open"

    accepted = verb(executor, "agent-a", "op-good-evidence", complete_command(
        revision=8, fence=fence, no_followup=True, evidence={
            "pointer": "artifact://private/nokv/wb-goals/goal-a/report",
            "digest": GOOD_DIGEST, "privacy_class": "private",
        },
    ))
    assert accepted["result"] == "applied", accepted


def test_head_with_a_host_path_evidence_pointer_fails_closed() -> None:
    provider, clock, executor, fence = claimed_fixture()
    done = verb(executor, "agent-a", "op-done-evidence", complete_command(
        revision=8, fence=fence, no_followup=True, evidence={
            "pointer": "artifact://public/runs/run-1/report",
            "digest": GOOD_DIGEST, "privacy_class": "public",
        },
    ))
    assert done["result"] == "applied", done
    head = head_of(provider)
    validated_head(head, goal_id="goal-a")
    # The boundary and head validation are one oracle: a pointer the
    # envelope refuses can never validate out of a stored head either.
    corrupted = copy.deepcopy(head)
    corrupted["coordination"]["todos"]["todo-1"]["evidence"]["pointer"] = (
        "/private/example/secret.log"
    )
    with pytest.raises(HeadValidationError):
        validated_head(corrupted, goal_id="goal-a")


def test_evidence_pointer_binds_its_declared_privacy_class() -> None:
    provider, clock, executor, fence = claimed_fixture()
    rejected = [
        # An arbitrary URI scheme is not a reviewed artifact contract.
        {"pointer": "https://localhost/private/report", "privacy_class": "public"},
        {"pointer": "nokv://private-workbench/secret", "privacy_class": "public"},
        {"pointer": "artifact:/etc/passwd", "privacy_class": "private"},
        # The URI's typed privacy namespace and the sibling enum must agree.
        {"pointer": "artifact://private/runs/secret", "privacy_class": "public"},
        {"pointer": "artifact://public/runs/report", "privacy_class": "private"},
        # Opaque ids stay bounded and cannot smuggle traversal or URI metadata.
        {"pointer": "artifact://public/../secret", "privacy_class": "public"},
        {"pointer": "artifact://public/report?format=json", "privacy_class": "public"},
    ]
    for index, item in enumerate(rejected):
        with pytest.raises(EnvelopeError):
            verb(
                executor,
                "agent-a",
                f"op-evidence-privacy-{index}",
                complete_command(
                    revision=8,
                    fence=fence,
                    evidence={"digest": GOOD_DIGEST, **item},
                ),
            )

    for index, evidence in enumerate(
        (
            {
                "pointer": "artifact://public/runs/run-1/report",
                "digest": GOOD_DIGEST,
                "privacy_class": "public",
            },
            {
                "pointer": "artifact://private/nokv/wb-goals/goal-a/report",
                "digest": GOOD_DIGEST,
                "privacy_class": "private",
            },
        )
    ):
        isolated_provider, isolated_clock, isolated_executor, isolated_fence = (
            claimed_fixture()
        )
        accepted = verb(
            isolated_executor,
            "agent-a",
            f"op-evidence-valid-{index}",
            complete_command(
                revision=8,
                fence=isolated_fence,
                no_followup=True,
                evidence=evidence,
            ),
        )
        assert accepted["result"] == "applied", accepted


# ---- legacy v0 heads and the explicit store-binding migration ---------------


def legacy_v0_head() -> dict:
    """The exact Stage 2 shape: today's head minus the store binding."""

    head = bootstrap_head(
        "goal-a", {"todo-1": todo()}, store_binding="test:store",
    )
    del head["store_binding"]
    head["schema_version"] = "loopx_coordination_head_v0"
    return head


def frozen_stage2_claimed_head() -> dict:
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "coordination_head_stage2_v0_claimed.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_a_legacy_v0_head_is_classified_not_crashed() -> None:
    provider = FakeProvider()
    assert provider.compare_and_put(0, legacy_v0_head())["result"] == "applied"
    executor = executor_for(provider, Clock())
    outcome = claim(executor, "agent-a", "todo-1", "op-on-legacy")
    assert outcome == {
        "result": "failed",
        "reason": "head_schema_migration_required",
        "provider_generation": 1,
    }
    with pytest.raises(HeadMigrationRequired):
        validated_head(legacy_v0_head(), goal_id="goal-a")


def test_only_a_valid_stage2_v0_head_is_classified_as_migratable() -> None:
    valid = legacy_v0_head()
    with pytest.raises(HeadMigrationRequired):
        validated_head(valid, goal_id="goal-a")

    corruptions = []
    wrong_goal = copy.deepcopy(valid)
    wrong_goal["goal_id"] = "goal-other"
    corruptions.append(wrong_goal)
    missing_field = copy.deepcopy(valid)
    del missing_field["receipt_index"]
    corruptions.append(missing_field)
    extra_field = copy.deepcopy(valid)
    extra_field["unreviewed"] = True
    corruptions.append(extra_field)
    smuggled_binding = copy.deepcopy(valid)
    smuggled_binding["store_binding"] = "smuggled:binding"
    corruptions.append(smuggled_binding)

    for corrupted in corruptions:
        with pytest.raises(HeadValidationError) as exc_info:
            validated_head(corrupted, goal_id="goal-a")
        assert not isinstance(exc_info.value, HeadMigrationRequired)


def test_stage3_fields_cannot_be_smuggled_under_the_legacy_v0_token() -> None:
    provider, _clock, executor, fence = claimed_fixture()
    completed = verb(
        executor,
        "agent-a",
        "op-stage3-done",
        complete_command(revision=8, fence=fence, no_followup=True),
    )
    assert completed["result"] == "applied"
    stage3_shaped_v0 = head_of(provider)
    stage3_shaped_v0["schema_version"] = "loopx_coordination_head_v0"
    del stage3_shaped_v0["store_binding"]
    with pytest.raises(HeadValidationError) as exc_info:
        validated_head(stage3_shaped_v0, goal_id="goal-a")
    assert not isinstance(exc_info.value, HeadMigrationRequired)

    provider2, _clock2, executor2, _fence2 = claimed_fixture()
    non_claim_receipt_v0 = head_of(provider2)
    non_claim_receipt_v0["schema_version"] = "loopx_coordination_head_v0"
    del non_claim_receipt_v0["store_binding"]
    receipt = non_claim_receipt_v0["receipt_index"]["op-claim"][
        "original_receipt"
    ]
    receipt["command"] = "renew_work"
    with pytest.raises(HeadValidationError) as exc_info:
        validated_head(non_claim_receipt_v0, goal_id="goal-a")
    assert not isinstance(exc_info.value, HeadMigrationRequired)


def test_explicit_migration_upgrades_a_v0_head_end_to_end() -> None:
    provider = FakeProvider()
    assert provider.compare_and_put(0, legacy_v0_head())["result"] == "applied"
    # The operator path: load, attest the reviewed store's own identity,
    # migrate, and write back through the same CAS.
    stale, generation = provider.load()
    migrated = migrate_head_v0_to_v1(
        stale, goal_id="goal-a", store_binding=provider.store_identity(),
    )
    assert migrated["schema_version"] == "loopx_coordination_head_v1"
    assert stale.get("store_binding") is None  # input is never mutated
    assert provider.compare_and_put(generation, migrated)["result"] == "applied"
    executor = executor_for(provider, Clock())
    first = claim(executor, "agent-a", "todo-1", "op-post-migration")
    assert first["result"] == "applied", first


def test_frozen_stage2_claimed_head_migrates_without_rewriting_history() -> None:
    legacy = frozen_stage2_claimed_head()
    assert head_digest(legacy) == (
        "sha256:a10866d23d0d61b8352163ef64c93b05656c6bc8717b2a944ba987dd5444aee6"
    )
    with pytest.raises(HeadMigrationRequired):
        validated_head(legacy, goal_id="goal-a")

    provider = FakeProvider()
    migrated = migrate_head_v0_to_v1(
        legacy,
        goal_id="goal-a",
        store_binding=provider.store_identity(),
    )
    assert migrated["receipt_index"] == legacy["receipt_index"]
    assert migrated["coordination"] == legacy["coordination"]
    assert provider.compare_and_put(0, migrated)["result"] == "applied"

    renewed = verb(
        executor_for(provider, Clock()),
        "agent-a",
        "op-after-stage2-migration",
        {
            "type": "renew_work",
            "todo_id": "todo-1",
            "expected_todo_revision": 8,
            "lease_id": "lease_8c5b438a43110ce57000c32a",
            "expected_lease_epoch": 7,
            "lease_ttl_seconds": 600,
        },
    )
    assert renewed["result"] == "applied", renewed


@pytest.mark.parametrize(
    "corruption",
    [
        "lease_watermark",
        "unproved_owner",
        "unproved_expiry",
        "authority_revision",
        "missing_lease",
        "unclaimed_with_lease",
    ],
)
def test_legacy_migration_requires_a_receipt_proved_live_claim(
    corruption: str,
) -> None:
    legacy = frozen_stage2_claimed_head()
    todo_record = legacy["coordination"]["todos"]["todo-1"]
    lease_record = legacy["coordination"]["leases"]["todo-1"]
    if corruption == "lease_watermark":
        todo_record["last_lease_epoch"] = 6
    elif corruption == "unproved_owner":
        todo_record["claimed_by"] = "agent-b"
        lease_record["owner"] = "agent-b"
    elif corruption == "unproved_expiry":
        lease_record["expires_at"] = "2027-01-15T09:10:00.000Z"
    elif corruption == "authority_revision":
        legacy["authority_revision"] = 0
    elif corruption == "missing_lease":
        del legacy["coordination"]["leases"]["todo-1"]
    else:
        todo_record["claimed_by"] = None

    with pytest.raises(HeadValidationError) as exc_info:
        validated_head(legacy, goal_id="goal-a")
    assert not isinstance(exc_info.value, HeadMigrationRequired)


def test_migration_refuses_anything_but_a_clean_v0_document() -> None:
    v1 = bootstrap_head("goal-a", {"todo-1": todo()}, store_binding="test:store")
    with pytest.raises(HeadValidationError):
        migrate_head_v0_to_v1(v1, goal_id="goal-a", store_binding="test:store")
    already_bound = legacy_v0_head()
    already_bound["store_binding"] = "smuggled:binding"
    with pytest.raises(HeadValidationError):
        migrate_head_v0_to_v1(
            already_bound, goal_id="goal-a", store_binding="test:store",
        )
    with pytest.raises(HeadValidationError):
        migrate_head_v0_to_v1(
            legacy_v0_head(), goal_id="goal-a", store_binding="",
        )
