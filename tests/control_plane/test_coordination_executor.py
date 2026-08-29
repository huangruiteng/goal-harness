"""The authority execution layer over a coordination provider (RFC section 5).

Covers the machine-verifiable acceptance checks of RFC section 10 that apply
to the claim_work slice (1-5, 7-11), plus the Stage-2 harmony requirement:
domain decisions are delegated to the Stage 1 core, never re-derived here.
"""

from __future__ import annotations

import copy
import threading

import pytest

from loopx.control_plane.coordination import authority_core
from loopx.control_plane.coordination.executor import (
    CoordinationAuthorityExecutor,
    EnvelopeError,
    sample_claim_envelope,
)
from loopx.control_plane.coordination.executor import (
    MAX_LEASE_TTL_SECONDS,
)
from loopx.control_plane.coordination.head import HeadValidationError, bootstrap_head


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
    """Deterministic in-memory provider with fault hooks for checks 7 and 9."""

    def __init__(self, generation_step: int = 17):
        self._head = None
        self._generation = 0
        self._step = generation_step
        self._lock = threading.Lock()
        self.fault = None
        self.unrelated_advances = 0

    def load(self):
        with self._lock:
            return copy.deepcopy(self._head), self._generation

    def compare_and_put(self, expected_generation, head):
        with self._lock:
            if self.fault == "failed_before":
                self.fault = None
                return {"result": "failed", "error": "provider unavailable"}
            if expected_generation != self._generation:
                return {
                    "result": "conflict",
                    "current_provider_generation": self._generation,
                }
            if self.fault == "ambiguous_before":
                self.fault = None
                return {"result": "ambiguous"}
            if self.unrelated_advances:
                self.unrelated_advances -= 1
                self._generation += self._step
                return {
                    "result": "conflict",
                    "current_provider_generation": self._generation,
                }
            self._head = copy.deepcopy(head)
            self._generation += self._step
            if self.fault == "ambiguous_after":
                self.fault = None
                return {"result": "ambiguous"}
            return {"result": "applied", "provider_generation": self._generation}


def bootstrap(provider, todos=("todo-1", "todo-2")) -> dict:
    head = bootstrap_head("goal-a", {todo_id: todo() for todo_id in todos})
    assert provider.compare_and_put(0, head)["result"] == "applied"
    return head


def executor_for(provider) -> CoordinationAuthorityExecutor:
    return CoordinationAuthorityExecutor(
        provider, goal_id="goal-a", now=lambda: 1_800_000_000.0
    )


def envelope(agent="agent-a", todo_id="todo-1", operation_id=None, **overrides):
    return sample_claim_envelope(
        goal_id="goal-a",
        operation_id=operation_id or f"op-{agent}-{todo_id}",
        agent_id=agent,
        device_id=f"dev-{agent}",
        todo_id=todo_id,
        expected_todo_revision=7,
        expected_preconditions={
            "authorization_projection_revision": 3,
            "authorization_projection_digest": "sha256:bootstrap-auth",
            "dependency_revision": 12,
            "gate_revision": 5,
        },
        lease_ttl_seconds=600,
        **overrides,
    )


# ---- check 1: same-todo competition has exactly one winner ------------------


def test_same_todo_two_actors_one_winner() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)

    first = executor.apply(envelope("agent-a"))
    second = executor.apply(envelope("agent-b"))

    assert first["result"] == "applied"
    receipt = first["original_receipt"]
    assert receipt["schema_version"] == "loopx_authority_receipt_v0"
    assert receipt["command"] == "claim_work"
    assert receipt["accepted_authority_revision"] == 1
    assert receipt["accepted_todo_revision"] == 8
    assert receipt["lease_epoch"] == 7
    assert second["result"] == "conflict"
    assert second["reason"] == "todo_revision_mismatch"

    head, _ = provider.load()
    claimed = head["coordination"]["todos"]["todo-1"]
    assert claimed["status"] == "open"
    assert claimed["claimed_by"] == "agent-a"
    assert claimed["todo_revision"] == 8
    assert claimed["last_lease_epoch"] == 7
    lease = head["coordination"]["leases"]["todo-1"]
    assert lease["owner"] == "agent-a" and lease["lease_epoch"] == 7
    assert len(head["receipt_index"]) == 1


# ---- check 2: independent todos rebase internally and both apply ------------


def test_independent_todos_both_apply_after_internal_rebase() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor_a = executor_for(provider)
    executor_b = executor_for(provider)

    provider.unrelated_advances = 0
    first = executor_a.apply(envelope("agent-a", "todo-1"))
    second = executor_b.apply(envelope("agent-b", "todo-2"))

    assert first["result"] == "applied" and second["result"] == "applied"
    head, _ = provider.load()
    assert head["authority_revision"] == 2
    assert head["coordination"]["todos"]["todo-1"]["todo_revision"] == 8
    assert head["coordination"]["todos"]["todo-2"]["todo_revision"] == 8
    accepted = sorted(
        entry["original_receipt"]["accepted_authority_revision"]
        for entry in head["receipt_index"].values()
    )
    assert accepted == [1, 2]


# ---- checks 3 + 4: replay returns the original receipt ----------------------


def test_replay_and_aba_recover_the_original_receipt() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)

    request = envelope("agent-a", "todo-1", operation_id="op-A")
    first = executor.apply(request)
    assert first["result"] == "applied"

    immediate = executor.apply(copy.deepcopy(request))
    assert immediate["result"] == "already_applied"
    assert immediate["original_receipt"] == first["original_receipt"]

    advanced = executor.apply(envelope("agent-b", "todo-2"))
    assert advanced["result"] == "applied"

    reconstructed = executor_for(provider)
    replay = reconstructed.apply(copy.deepcopy(request))
    assert replay["result"] == "already_applied"
    assert replay["original_receipt"] == first["original_receipt"]
    assert replay["observed_authority_revision"] == 2
    assert replay["authorization_status"] == "active"

    transported = copy.deepcopy(request)
    transported["transport"] = {"attempt": 4}
    assert reconstructed.apply(transported)["result"] == "already_applied"


# ---- check 5: identity reuse with different semantics is rejected -----------


def test_operation_identity_mismatch_changes_nothing() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    request = envelope("agent-a", "todo-1", operation_id="op-A")
    assert executor.apply(request)["result"] == "applied"
    before = provider.load()

    mutated = copy.deepcopy(request)
    mutated["command"]["lease_ttl_seconds"] = 601
    outcome = executor.apply(mutated)
    assert outcome["result"] == "rejected"
    assert outcome["reason"] == "operation_identity_mismatch"
    assert provider.load() == before


# ---- check 7: crash windows and ambiguity ----------------------------------


def test_ambiguous_with_commit_recovers_from_receipt() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    provider.fault = "ambiguous_after"
    outcome = executor.apply(envelope("agent-a", "todo-1", operation_id="op-lost"))
    assert outcome["result"] == "already_applied"
    head, _ = provider.load()
    assert head["authority_revision"] == 1
    assert "op-lost" in head["receipt_index"]


def test_ambiguous_without_commit_fails_unproved() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    provider.fault = "ambiguous_before"
    outcome = executor.apply(envelope("agent-a", "todo-1"))
    assert outcome["result"] == "failed"
    assert outcome["reason"] == "provider_outcome_unproved"
    head, _ = provider.load()
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}


def test_provider_failed_before_cas_is_typed() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    provider.fault = "failed_before"
    outcome = executor.apply(envelope("agent-a", "todo-1"))
    assert outcome["result"] == "failed"
    assert outcome["reason"] == "provider_failed_before_cas"


# ---- check 8: rejections create no state ------------------------------------


def test_rejections_and_stale_preconditions_change_nothing() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    before = provider.load()

    unknown = executor.apply(envelope("agent-a", "todo-9"))
    assert unknown["result"] == "rejected" and unknown["reason"] == "todo_not_found"

    ineligible = executor.apply(envelope("agent-z", "todo-1"))
    assert ineligible["result"] == "rejected"
    assert ineligible["reason"] == "actor_ineligible"

    stale_revision = envelope("agent-a", "todo-1")
    stale_revision["command"]["expected_todo_revision"] = 6
    stale = executor.apply(stale_revision)
    assert stale["result"] == "conflict"
    assert stale["reason"] == "todo_revision_mismatch"

    stale_preconditions = envelope("agent-a", "todo-1")
    stale_preconditions["command"]["expected_preconditions"][
        "dependency_revision"
    ] = 11
    mismatch = executor.apply(stale_preconditions)
    assert mismatch["result"] == "conflict"
    assert mismatch["reason"] == "precondition_snapshot_mismatch"

    blocked = bootstrap_head(
        "goal-a", {"todo-3": todo(eligibility=eligibility() | {"gates_open": False})}
    )
    gated_provider = FakeProvider()
    assert gated_provider.compare_and_put(0, blocked)["result"] == "applied"
    gated = executor_for(gated_provider).apply(envelope("agent-a", "todo-3"))
    assert gated["result"] == "rejected" and gated["reason"] == "gate_closed"

    assert provider.load() == before


# ---- check 9: sustained unrelated contention fails typed --------------------


def test_sustained_unrelated_contention_returns_typed_failed() -> None:
    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    provider.unrelated_advances = 99
    outcome = executor.apply(envelope("agent-a", "todo-1", operation_id="op-c"))
    assert outcome["result"] == "failed"
    assert outcome["reason"] == "provider_contention_exhausted"
    head, _ = provider.load()
    assert head["authority_revision"] == 0
    assert "op-c" not in head["receipt_index"]


# ---- checks 10 + 11: retention and version domains --------------------------


def test_receipts_are_retained_and_version_domains_are_distinct() -> None:
    provider = FakeProvider(generation_step=17)
    bootstrap(provider)
    executor = executor_for(provider)
    assert executor.apply(envelope("agent-a", "todo-1"))["result"] == "applied"
    assert executor.apply(envelope("agent-b", "todo-2"))["result"] == "applied"
    head, generation = provider.load()
    assert generation == 3 * 17
    assert head["authority_revision"] == 2
    assert head["coordination"]["leases"]["todo-1"]["lease_epoch"] == 7
    assert len(head["receipt_index"]) == 2
    assert head["receipt_retention"] == {"mode": "retain_all_v0"}


# ---- harmony: domain decisions come from the Stage 1 core -------------------


def test_lease_acquire_rule_is_owned_by_the_native_decision(monkeypatch) -> None:
    """The NoKV executor and local file transaction share one acquire rule."""

    calls = []

    def native_decision(method, payload):
        calls.append((method, payload))
        return {
            "outcome": "rejected",
            "code": "native_rule_probe",
            "idempotent": False,
            "next_lease": None,
            "conflict_indexes": [],
        }

    monkeypatch.setattr(authority_core, "effect_runtime_result", native_decision)
    snapshot = authority_core.CoordinationSnapshot(
        handoff_mode=authority_core.HandoffMode.HARD_LEASE,
        registered_agents=("agent-a",),
        todo=authority_core.TodoSnapshot(
            todo_id="todo-1",
            status="open",
            role="agent",
        ),
    )
    plan = authority_core.decide(
        snapshot,
        authority_core.LeaseAcquireCommand(
            owner="agent-a",
            idempotency_key="lease-a",
            ttl_seconds=600,
        ),
    )

    assert plan.code == "native_rule_probe"
    assert calls[0][0] == "task_lease.acquire.decide"


def test_domain_rules_are_delegated_to_the_stage1_core(monkeypatch) -> None:
    """Flipping one core rule must flip the executor: no duplicated rules."""

    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)

    real_decide = authority_core.decide

    def approving_decide(snapshot, command):
        plan = real_decide(snapshot, command)
        if plan.code in {"actor_not_registered", "owner_not_registered"}:
            actor = getattr(command, "actor_agent_id", None) or getattr(
                command, "owner", None
            )
            patched = real_decide(
                authority_core.CoordinationSnapshot(
                    handoff_mode=snapshot.handoff_mode,
                    registered_agents=(*snapshot.registered_agents, actor),
                    todo=snapshot.todo,
                    lease=snapshot.lease,
                ),
                command,
            )
            return patched
        return plan

    import loopx.control_plane.coordination.executor as executor_module

    monkeypatch.setattr(executor_module, "decide", approving_decide)
    outcome = executor.apply(envelope("agent-z", "todo-1"))
    assert outcome["result"] == "applied", (
        "the executor must consult authority_core.decide for actor eligibility; "
        "a re-derived local rule would still reject agent-z"
    )


def test_uninitialized_head_fails_closed() -> None:
    provider = FakeProvider()
    executor = executor_for(provider)
    outcome = executor.apply(envelope("agent-a", "todo-1"))
    assert outcome["result"] == "failed"
    assert outcome["reason"] == "coordination_head_uninitialized"

# ---- audit hardening: provider verdicts and envelope corruption -------------


class MisreportingProvider:
    """Lands the write, then reports the CAS as failed (a lying provider)."""

    def __init__(self):
        self.inner = FakeProvider()

    def load(self):
        return self.inner.load()

    def compare_and_put(self, expected_generation, head):
        outcome = self.inner.compare_and_put(expected_generation, head)
        if outcome["result"] == "applied":
            return {"result": "failed", "error": "spurious timeout"}
        return outcome


def test_provider_failed_verdict_is_verified_not_trusted() -> None:
    """``failed`` claims the write provably never happened. The executor
    verifies that claim against the receipt index instead of trusting it, so a
    provider that misreports a landed write cannot manufacture a zombie claim
    whose caller was told it failed."""

    provider = MisreportingProvider()
    bootstrap(provider.inner)
    executor = CoordinationAuthorityExecutor(
        provider, goal_id="goal-a", now=lambda: 1_800_000_000.0
    )
    outcome = executor.apply(envelope("agent-a", "todo-1"))
    assert outcome["result"] == "already_applied"
    stored_head, _ = provider.load()
    stored = stored_head["receipt_index"]["op-agent-a-todo-1"]["original_receipt"]
    assert outcome["original_receipt"] == stored


def test_envelope_rejects_bool_disguised_integers() -> None:
    """bool is an int subclass; a True revision or TTL must not pass the typed
    integer gates and mint real state from a malformed envelope."""

    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    for mutate in (
        lambda command: command.update(expected_todo_revision=True),
        lambda command: command.update(lease_ttl_seconds=True),
        lambda command: command["expected_preconditions"].update(
            dependency_revision=True
        ),
    ):
        request = envelope("agent-a", "todo-1")
        mutate(request["command"])
        with pytest.raises(EnvelopeError):
            executor.apply(request)

def test_corrupt_stored_receipt_fails_typed_before_replay() -> None:
    """A digest-matching receipt entry whose ``original_receipt`` was gutted
    must surface as the typed head-validation failure at load, never as a
    KeyError from inside the replay or success paths."""

    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    assert executor.apply(envelope("agent-a", "todo-1"))["result"] == "applied"
    stored, generation = provider.load()
    stored["receipt_index"]["op-agent-a-todo-1"]["original_receipt"] = {}
    assert provider.compare_and_put(generation, stored)["result"] == "applied"
    with pytest.raises(HeadValidationError, match="receipt"):
        executor.apply(envelope("agent-a", "todo-1"))


def test_lease_ttl_is_bounded_by_the_task_lease_ceiling() -> None:
    """The shared envelope reuses the local task-lease TTL ceiling, so an
    astronomical caller value is a typed rejection at the envelope boundary
    and can never reach wall-clock arithmetic as an OverflowError."""

    provider = FakeProvider()
    bootstrap(provider)
    executor = executor_for(provider)
    for ttl in (10**100, MAX_LEASE_TTL_SECONDS + 1):
        request = envelope("agent-a", "todo-1")
        request["command"]["lease_ttl_seconds"] = ttl
        with pytest.raises(EnvelopeError, match="between 1 and"):
            executor.apply(request)
    at_ceiling = envelope("agent-a", "todo-1")
    at_ceiling["command"]["lease_ttl_seconds"] = MAX_LEASE_TTL_SECONDS
    assert executor.apply(at_ceiling)["result"] == "applied"


def test_lease_ttl_ceiling_matches_the_local_task_lease_authority() -> None:
    """The executor mirrors the constant instead of importing the (untyped)
    task-lease module; this pin keeps the two ceilings from drifting."""

    from loopx.control_plane.work_items.task_lease import (
        MAX_TASK_LEASE_TTL_SECONDS,
    )

    assert MAX_LEASE_TTL_SECONDS == MAX_TASK_LEASE_TTL_SECONDS
