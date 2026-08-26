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
import threading

import pytest

from loopx.control_plane.coordination.executor import (
    CoordinationAuthorityExecutor,
    EnvelopeError,
    sample_claim_envelope,
    sample_work_envelope,
)
from loopx.control_plane.coordination.head import bootstrap_head, validated_head
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
        "pointer": "artifact://runs/run-1/report",
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
