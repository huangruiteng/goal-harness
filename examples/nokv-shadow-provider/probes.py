"""Deterministic probes for the coordination authority proof.

Run ``python probes.py contract`` without NoKV or external services.  Every
claim/CAS probe drives the production coordination modules
(``loopx.control_plane.coordination.head`` and ``.executor``) - there is no
second reference authority - and finishes by round-tripping its persisted
head through the production ``validated_head``, so a probe that passes is
evidence about the exact code the runtime ships.  The claim/CAS probes do
not qualify NoKV restart, recovery, GC, HA, or a live deployment.  The
durable-completion probes are the offline read-side comparison registered by
RFC shared-goal-authority-state-provider-v0.  They prove the provider byte-CAS
can hold and read back a post-completion
head whose durable records project to the same typed continuation outcomes
(``successor | no_followup | active_goal``, fail-closed on
contradiction/dangling) as the LoopX projection seam.  They deliberately
mutate provider bytes to construct negative read fixtures; Stage 3 focused
tests and ``live_e2e.py`` qualify the actual atomic completion write side.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from loopx.control_plane.coordination.executor import (  # noqa: E402
    CoordinationAuthorityExecutor,
    EnvelopeError,
    sample_claim_envelope,
)
from loopx.control_plane.coordination.head import (  # noqa: E402
    bootstrap_head,
    validated_head,
)
from loopx.control_plane.todos.completion_state import (  # noqa: E402
    completion_continuation_for_write,
)
from loopx.control_plane.todos.durable_completion import (  # noqa: E402
    project_durable_completion_outcome,
)

from provider import (  # noqa: E402
    NoKVCoordinationProvider,
    ProviderProtocolError,
    ProviderUnavailableError,
)


def out(probe: str, **values) -> None:
    print(json.dumps({"probe": probe, **values}, sort_keys=True), flush=True)


class SimulatedCrash(RuntimeError):
    pass


class DeterministicProvider:
    """Byte-level CAS whose generation deliberately cannot alias domain versions."""

    def __init__(self, generation_step: int = 17):
        self._aggregate = None
        self._generation = 0
        self._generation_step = generation_step
        self._lock = threading.Lock()
        self._barrier = None
        self._barrier_loads_left = 0
        self._fault = None
        self._contention_advances = 0
        self.identity = "probe:store"

    def store_identity(self) -> str:
        return self.identity

    def arm_load_barrier(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties)
        self._barrier_loads_left = parties

    def arm_fault(self, fault: str) -> None:
        if fault not in {
            "failed_before",
            "crash_before",
            "crash_after",
            "ambiguous_before",
            "ambiguous_with_unrelated_advance",
            "ambiguous_after",
            "ambiguous_after_with_unrelated_advance",
        }:
            raise ValueError(f"unknown fault: {fault}")
        self._fault = fault

    def arm_contention(self, advances: int) -> None:
        self._contention_advances = advances

    def load(self):
        barrier = None
        with self._lock:
            value = copy.deepcopy(self._aggregate)
            generation = self._generation
            if self._barrier_loads_left:
                self._barrier_loads_left -= 1
                barrier = self._barrier
        if barrier is not None:
            barrier.wait(timeout=5)
        return value, generation

    def compare_and_put(self, expected_generation: int, aggregate: dict):
        with self._lock:
            if self._fault == "failed_before":
                self._fault = None
                return {"result": "failed"}
            if self._fault == "crash_before":
                self._fault = None
                raise SimulatedCrash("crash_before")
            if expected_generation != self._generation:
                return {
                    "result": "conflict",
                    "current_provider_generation": self._generation,
                }
            if self._fault == "ambiguous_before":
                self._fault = None
                return {"result": "ambiguous"}
            if self._fault == "ambiguous_with_unrelated_advance":
                self._fault = None
                self._generation += self._generation_step
                return {"result": "ambiguous"}
            if self._contention_advances:
                # Simulate an unrelated provider-level rewrite.  The opaque
                # generation advances while the target todo stays unchanged.
                self._contention_advances -= 1
                self._generation += self._generation_step
                return {
                    "result": "conflict",
                    "current_provider_generation": self._generation,
                }
            self._aggregate = copy.deepcopy(aggregate)
            self._generation += self._generation_step
            generation = self._generation
            if self._fault == "crash_after":
                self._fault = None
                raise SimulatedCrash("crash_after")
            if self._fault == "ambiguous_after":
                self._fault = None
                return {"result": "ambiguous"}
            if self._fault == "ambiguous_after_with_unrelated_advance":
                self._fault = None
                self._generation += self._generation_step
                return {"result": "ambiguous"}
            return {"result": "applied", "provider_generation": generation}


def initial_todo(
    allowed_agents=None,
    dependencies_satisfied: bool = True,
    gates_open: bool = True,
) -> dict:
    return {
        "todo_revision": 7,
        "status": "open",
        "claimed_by": None,
        "last_lease_epoch": 0,
        "eligibility": {
            "allowed_agent_ids": allowed_agents or ["agent-a", "agent-0", "agent-1"],
            "authorization_projection_digest": "sha256:bootstrap-auth",
            "authorization_projection_revision": 3,
            "dependencies_satisfied": dependencies_satisfied,
            "dependency_revision": 12,
            "gates_open": gates_open,
            "gate_revision": 5,
        },
        "repository": "git:example/repo",
        "code_revision": "0123456789abcdef",
    }


def bootstrap(provider, goal_id: str, todo_ids) -> int:
    head = bootstrap_head(
        goal_id,
        {todo_id: initial_todo() for todo_id in todo_ids},
        store_binding=provider.store_identity(),
    )
    result = provider.compare_and_put(0, head)
    assert result["result"] == "applied", result
    return result["provider_generation"]


def load_head(provider, goal_id: str):
    del goal_id  # provider handles are already bound to one goal key
    return provider.load()


def authority(provider, goal_id: str, when: float) -> CoordinationAuthorityExecutor:
    return CoordinationAuthorityExecutor(provider, goal_id=goal_id, now=lambda: when)


def assert_production_valid(provider, goal_id: str) -> None:
    """The persisted probe artifact must pass the production validator."""

    head, _generation = provider.load()
    validated_head(head, goal_id=goal_id)


def assert_exact_replay(first: dict, replay: dict) -> None:
    assert first["result"] == "applied", first
    assert replay["result"] == "already_applied", replay
    assert replay["original_receipt"] == first["original_receipt"], (first, replay)


def claim(operation_id: str, goal_id: str, todo_id: str, **values) -> dict:
    expected_preconditions = values.pop("expected_preconditions", None)
    if expected_preconditions is None:
        expected_preconditions = {
            "authorization_projection_revision": 3,
            "authorization_projection_digest": "sha256:bootstrap-auth",
            "dependency_revision": 12,
            "gate_revision": 5,
        }
    envelope = sample_claim_envelope(
        goal_id=goal_id,
        operation_id=operation_id,
        agent_id=values.pop("agent_id", "agent-a"),
        device_id=values.pop("device_id", "dev-laptop"),
        todo_id=todo_id,
        expected_todo_revision=values.pop("expected_todo_revision", 7),
        expected_preconditions=expected_preconditions,
        lease_ttl_seconds=values.pop("lease_ttl_seconds", 600),
        transport=values.pop("transport", None),
    )
    if values:
        raise TypeError(f"unknown claim kwargs: {sorted(values)}")
    return envelope


def assert_bootstrap_rejected(todo: dict, message: str | None = None) -> None:
    try:
        bootstrap_head("goal-private", {"todo-private": todo}, store_binding="probe:store")
    except ValueError as exc:
        if message is not None:
            assert message in str(exc)
    else:
        raise AssertionError("unsafe todo entered the shared head")


def probe_bootstrap_and_preconditions() -> None:
    provider = DeterministicProvider()
    uninitialized = authority(provider, "goal-preconditions", 1000).apply(
        claim("op-uninitialized", "goal-preconditions", "todo-known")
    )
    assert uninitialized["result"] == "failed"
    assert uninitialized["reason"] == "coordination_head_uninitialized"

    initial_head = bootstrap_head(
        "goal-preconditions",
        {
            "todo-known": initial_todo(),
            "todo-dependency-blocked": initial_todo(dependencies_satisfied=False),
            "todo-gate-blocked": initial_todo(gates_open=False),
        },
        store_binding=provider.store_identity(),
    )
    bootstrap_result = provider.compare_and_put(0, initial_head)
    assert bootstrap_result["result"] == "applied"
    initial_generation = bootstrap_result["provider_generation"]
    executor = authority(provider, "goal-preconditions", 1000)
    missing = executor.apply(claim("op-missing", "goal-preconditions", "todo-missing"))
    stale = executor.apply(
        claim("op-stale", "goal-preconditions", "todo-known", expected_todo_revision=6)
    )
    expected_preconditions = {
        "authorization_projection_revision": 3,
        "authorization_projection_digest": "sha256:bootstrap-auth",
        "dependency_revision": 12,
        "gate_revision": 5,
    }
    stale_values = {
        "authorization_projection_revision": 2,
        "authorization_projection_digest": "sha256:stale-auth",
        "dependency_revision": 11,
        "gate_revision": 4,
    }
    changed_preconditions = []
    for field, stale_value in stale_values.items():
        preconditions = copy.deepcopy(expected_preconditions)
        preconditions[field] = stale_value
        changed_preconditions.append(executor.apply(claim(
            f"op-stale-{field}",
            "goal-preconditions",
            "todo-known",
            expected_preconditions=preconditions,
        )))
    ineligible = executor.apply(claim(
        "op-ineligible",
        "goal-preconditions",
        "todo-known",
        agent_id="agent-not-allowed",
    ))
    dependency_blocked = executor.apply(
        claim("op-dependency-blocked", "goal-preconditions", "todo-dependency-blocked")
    )
    gate_blocked = executor.apply(
        claim("op-gate-blocked", "goal-preconditions", "todo-gate-blocked")
    )
    head, generation = load_head(provider, "goal-preconditions")
    assert missing == {
        "result": "rejected",
        "reason": "todo_not_found",
        "observed_authority_revision": 0,
        "provider_generation": initial_generation,
    }
    assert stale["result"] == "conflict" and stale["reason"] == "todo_revision_mismatch"
    assert all(result["result"] == "conflict" for result in changed_preconditions)
    assert all(
        result["reason"] == "precondition_snapshot_mismatch"
        for result in changed_preconditions
    )
    assert ineligible["result"] == "rejected" and ineligible["reason"] == "actor_ineligible"
    assert dependency_blocked["result"] == "rejected"
    assert dependency_blocked["reason"] == "dependencies_not_satisfied"
    assert gate_blocked["result"] == "rejected" and gate_blocked["reason"] == "gate_closed"
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}
    assert generation == initial_generation
    assert_production_valid(provider, "goal-preconditions")
    private_todo = initial_todo()
    private_todo["raw_todo_body"] = "must not enter the shared head"
    assert_bootstrap_rejected(private_todo, "fields do not match v0")
    absolute_path_todo = initial_todo()
    absolute_path_todo["repository"] = "/" + "synthetic/local/repository"
    assert_bootstrap_rejected(absolute_path_todo, "repository is not portable")
    credential_repository_todo = initial_todo()
    credential_repository_todo["repository"] = "git:" + "user@host/repository"
    invalid_revision_todo = initial_todo()
    invalid_revision_todo["code_revision"] = "review-ready"
    for unsafe_todo in (credential_repository_todo, invalid_revision_todo):
        assert_bootstrap_rejected(unsafe_todo)
    out(
        "contract.bootstrap_and_preconditions",
        ok=True,
        uninitialized_failed=True,
        no_implicit_todo_creation=True,
        todo_revision_checked=True,
        named_preconditions_checked=True,
        eligibility_checked=True,
        dependency_and_gate_checked=True,
        bootstrap_privacy_allowlist_checked=True,
        repository_metadata_checked=True,
        production_validator_round_trip=True,
    )


def probe_a_b_replay_a() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-review", ["todo-review", "todo-followup"])
    executor = authority(provider, "goal-review", 1100)
    envelope_a = claim("op-review-a", "goal-review", "todo-review")
    first_a = executor.apply(envelope_a)
    first_b = executor.apply(claim("op-followup-b", "goal-review", "todo-followup"))
    replay_a = authority(provider, "goal-review", 9000).apply(envelope_a)
    head, generation = load_head(provider, "goal-review")
    assert first_b["result"] == "applied"
    assert_exact_replay(first_a, replay_a)
    assert head["authority_revision"] == 2 and generation == 51
    assert head["receipt_index"]["op-review-a"]["original_receipt"] == first_a[
        "original_receipt"
    ]
    assert len(head["receipt_index"]) == 2
    assert_production_valid(provider, "goal-review")
    out(
        "contract.a_success_b_advance_replay_a",
        ok=True,
        authority_reconstructed=True,
        original_receipt_equal=True,
        authority_revision=2,
        provider_generation=generation,
        lease_epoch=first_a["original_receipt"]["lease_epoch"],
        receipt_count=2,
    )


def probe_operation_identity() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-digest", ["todo-original", "todo-mutated"])
    executor = authority(provider, "goal-digest", 1200)
    original = claim(
        "op-stable",
        "goal-digest",
        "todo-original",
        transport={"attempt": 1, "trace_id": "trace-a"},
    )
    first = executor.apply(original)
    transport_retry = copy.deepcopy(original)
    transport_retry["transport"] = {"attempt": 2, "trace_id": "trace-b"}
    assert_exact_replay(first, executor.apply(transport_retry))

    changed = copy.deepcopy(original)
    changed["command"]["todo_id"] = "todo-mutated"
    mismatch = executor.apply(changed)
    assert mismatch["result"] == "rejected"
    assert mismatch["reason"] == "operation_identity_mismatch"
    unknown = copy.deepcopy(original)
    unknown["unexpected_semantic_field"] = True
    try:
        executor.apply(unknown)
    except EnvelopeError as exc:
        assert "unknown command envelope fields" in str(exc)
    else:
        raise AssertionError("unknown semantic field was ignored")
    head, _ = load_head(provider, "goal-digest")
    assert len(head["receipt_index"]) == 1
    assert_production_valid(provider, "goal-digest")
    out(
        "contract.operation_identity",
        ok=True,
        transport_metadata_excluded=True,
        semantic_change_rejected=True,
        unknown_fields_fail_closed=True,
    )


def probe_competing_claims() -> None:
    def race(provider, goal_id, envelopes):
        provider.arm_load_barrier(2)

        def run(index: int):
            return authority(provider, goal_id, 1300 + index).apply(envelopes[index])

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    same_provider = DeterministicProvider(generation_step=23)
    bootstrap(same_provider, "goal-race", ["todo-one-winner"])
    same_envelopes = [
        claim(
            f"op-claim-{index}",
            "goal-race",
            "todo-one-winner",
            agent_id=f"agent-{index}",
            device_id=f"device-{index}",
        )
        for index in range(2)
    ]
    same_results = race(same_provider, "goal-race", same_envelopes)
    applied = [result for result in same_results if result["result"] == "applied"]
    conflicts = [result for result in same_results if result["result"] == "conflict"]
    head, generation = load_head(same_provider, "goal-race")
    assert len(applied) == 1 and len(conflicts) == 1, same_results
    winner = applied[0]["original_receipt"]["actor"]["agent_id"]
    assert conflicts[0]["reason"] == "todo_revision_mismatch"
    assert "original_receipt" not in conflicts[0] and "lease_id" not in conflicts[0]
    assert head["authority_revision"] == 1 and len(head["receipt_index"]) == 1
    same_todo = head["coordination"]["todos"]["todo-one-winner"]
    assert same_todo["todo_revision"] == 8
    assert same_todo["status"] == "open"
    assert same_todo["claimed_by"] == winner
    assert set(head["coordination"]["leases"]) == {"todo-one-winner"}
    assert head["coordination"]["leases"]["todo-one-winner"]["owner"] == winner
    assert generation == 46
    assert_production_valid(same_provider, "goal-race")

    independent_provider = DeterministicProvider(generation_step=29)
    bootstrap(independent_provider, "goal-independent", ["todo-a", "todo-b"])
    independent_envelopes = [
        claim(
            f"op-independent-{index}",
            "goal-independent",
            f"todo-{'ab'[index]}",
            agent_id=f"agent-{index}",
            device_id=f"device-{index}",
        )
        for index in range(2)
    ]
    independent_results = race(
        independent_provider,
        "goal-independent",
        independent_envelopes,
    )
    independent_head, independent_generation = load_head(
        independent_provider,
        "goal-independent",
    )
    assert [result["result"] for result in independent_results].count("applied") == 2, (
        independent_results
    )
    assert independent_head["authority_revision"] == 2
    assert len(independent_head["receipt_index"]) == 2
    assert set(independent_head["coordination"]["leases"]) == {"todo-a", "todo-b"}
    assert independent_head["coordination"]["todos"]["todo-a"]["todo_revision"] == 8
    assert independent_head["coordination"]["todos"]["todo-b"]["todo_revision"] == 8
    assert independent_head["coordination"]["todos"]["todo-a"]["status"] == "open"
    assert independent_head["coordination"]["todos"]["todo-b"]["status"] == "open"
    assert independent_head["coordination"]["todos"]["todo-a"]["claimed_by"] == "agent-0"
    assert independent_head["coordination"]["todos"]["todo-b"]["claimed_by"] == "agent-1"
    assert independent_head["coordination"]["leases"]["todo-a"]["owner"] == "agent-0"
    assert independent_head["coordination"]["leases"]["todo-b"]["owner"] == "agent-1"
    assert set(independent_head["receipt_index"]) == {
        "op-independent-0",
        "op-independent-1",
    }
    assert independent_head["receipt_index"]["op-independent-0"][
        "original_receipt"
    ]["todo_id"] == "todo-a"
    assert independent_head["receipt_index"]["op-independent-1"][
        "original_receipt"
    ]["todo_id"] == "todo-b"
    assert independent_generation == 87
    replayed = authority(independent_provider, "goal-independent", 9000).apply(
        independent_envelopes[0]
    )
    assert_exact_replay(independent_results[0], replayed)
    assert load_head(independent_provider, "goal-independent") == (
        independent_head,
        independent_generation,
    )
    assert_production_valid(independent_provider, "goal-independent")
    out(
        "contract.competing_claims",
        ok=True,
        same_todo_applied=1,
        same_todo_conflicts=1,
        independent_todos_applied=2,
        independent_authority_revision=2,
        independent_replay_exact=True,
        claim_preserves_open_status=True,
    )


def probe_crash_windows_and_ambiguity() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-faults", ["todo-before", "todo-after", "todo-ambiguous"])
    before = claim("op-before", "goal-faults", "todo-before")
    provider.arm_fault("failed_before")
    failed = authority(provider, "goal-faults", 1400).apply(before)
    assert failed["result"] == "failed"
    assert failed["reason"] == "provider_failed_before_cas"
    head, generation = load_head(provider, "goal-faults")
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}
    assert generation == 17
    provider.arm_fault("crash_before")
    try:
        authority(provider, "goal-faults", 1400).apply(before)
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("before-CAS crash was not injected")
    head, generation = load_head(provider, "goal-faults")
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}
    assert generation == 17

    after = claim("op-after", "goal-faults", "todo-after")
    provider.arm_fault("crash_after")
    try:
        authority(provider, "goal-faults", 1500).apply(after)
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("after-CAS crash was not injected")
    committed, committed_generation = load_head(provider, "goal-faults")
    durable_receipt = committed["receipt_index"]["op-after"]["original_receipt"]
    replay = authority(provider, "goal-faults", 9000).apply(after)
    assert replay["result"] == "already_applied"
    assert replay["original_receipt"] == durable_receipt
    assert load_head(provider, "goal-faults") == (committed, committed_generation)

    ambiguous = claim("op-ambiguous", "goal-faults", "todo-ambiguous")
    provider.arm_fault("ambiguous_after")
    reconciled = authority(provider, "goal-faults", 1600).apply(ambiguous)
    final_head, _ = load_head(provider, "goal-faults")
    assert reconciled["result"] == "already_applied"
    assert final_head["authority_revision"] == 2 and len(final_head["receipt_index"]) == 2
    assert_production_valid(provider, "goal-faults")

    ambiguous_before_provider = DeterministicProvider()
    bootstrap(ambiguous_before_provider, "goal-ambiguous-before", ["todo-target"])
    before_head = load_head(ambiguous_before_provider, "goal-ambiguous-before")
    ambiguous_before_provider.arm_fault("ambiguous_before")
    unproved = authority(ambiguous_before_provider, "goal-ambiguous-before", 1650).apply(
        claim("op-unproved", "goal-ambiguous-before", "todo-target")
    )
    assert unproved["result"] == "failed"
    assert unproved["reason"] == "provider_outcome_unproved"
    assert load_head(ambiguous_before_provider, "goal-ambiguous-before") == before_head
    assert_production_valid(ambiguous_before_provider, "goal-ambiguous-before")

    ambiguous_advance_provider = DeterministicProvider()
    bootstrap(ambiguous_advance_provider, "goal-ambiguous-advance", ["todo-target"])
    ambiguous_advance_provider.arm_fault("ambiguous_with_unrelated_advance")
    retried = authority(
        ambiguous_advance_provider, "goal-ambiguous-advance", 1675
    ).apply(claim("op-retried", "goal-ambiguous-advance", "todo-target"))
    retried_head, _ = load_head(ambiguous_advance_provider, "goal-ambiguous-advance")
    assert retried["result"] == "applied"
    assert retried_head["authority_revision"] == 1
    assert set(retried_head["receipt_index"]) == {"op-retried"}
    assert_production_valid(ambiguous_advance_provider, "goal-ambiguous-advance")

    ambiguous_committed_provider = DeterministicProvider()
    bootstrap(ambiguous_committed_provider, "goal-ambiguous-committed", ["todo-target"])
    ambiguous_committed_provider.arm_fault("ambiguous_after_with_unrelated_advance")
    recovered = authority(
        ambiguous_committed_provider, "goal-ambiguous-committed", 1685
    ).apply(claim("op-recovered", "goal-ambiguous-committed", "todo-target"))
    recovered_head, _ = load_head(
        ambiguous_committed_provider,
        "goal-ambiguous-committed",
    )
    assert recovered["result"] == "already_applied"
    assert recovered_head["authority_revision"] == 1
    assert set(recovered_head["receipt_index"]) == {"op-recovered"}
    assert_production_valid(ambiguous_committed_provider, "goal-ambiguous-committed")

    contention_provider = DeterministicProvider()
    bootstrap(contention_provider, "goal-contention", ["todo-target"])
    contention_provider.arm_contention(8)
    exhausted = authority(contention_provider, "goal-contention", 1700).apply(
        claim("op-contention", "goal-contention", "todo-target")
    )
    contention_head, _ = load_head(contention_provider, "goal-contention")
    assert exhausted["result"] == "failed"
    assert exhausted["reason"] == "provider_contention_exhausted"
    assert "op-contention" not in contention_head["receipt_index"]
    assert contention_head["coordination"]["todos"]["todo-target"]["status"] == "open"
    assert_production_valid(contention_provider, "goal-contention")
    out(
        "contract.crash_windows_and_ambiguity",
        ok=True,
        before_cas_no_partial_state=True,
        failed_before_cas_no_write=True,
        after_cas_exact_receipt_recovered=True,
        ambiguous_reconciled_from_receipt=True,
        ambiguous_same_generation_failed_unproved=True,
        ambiguous_after_unrelated_advance_retried=True,
        ambiguous_committed_then_advanced_replayed=True,
        bounded_contention_failed_without_receipt=True,
        no_double_apply=True,
    )


def probe_version_domains_and_retain_all() -> None:
    provider = DeterministicProvider(generation_step=101)
    bootstrap(provider, "goal-versions", ["todo-a", "todo-b"])
    executor = authority(provider, "goal-versions", 1700)
    first = executor.apply(claim("op-a", "goal-versions", "todo-a"))
    second = executor.apply(claim("op-b", "goal-versions", "todo-b"))
    head, generation = load_head(provider, "goal-versions")
    assert generation == 303 and head["authority_revision"] == 2
    assert first["original_receipt"]["lease_epoch"] == 1
    assert second["original_receipt"]["lease_epoch"] == 1
    assert head["receipt_retention"] == {"mode": "retain_all_v0"}
    assert len(head["receipt_index"]) == 2
    assert_production_valid(provider, "goal-versions")
    out(
        "contract.version_domains_and_retain_all",
        ok=True,
        provider_generation=generation,
        authority_revision=2,
        lease_epochs=[1, 1],
        receipt_retention="retain_all_v0",
        receipt_count=2,
    )


def _evolve_completion_head(provider, todo_mutations: dict) -> None:
    """CAS-write an evolved post-completion head over a bootstrapped open one.

    Each mutated todo is committed in the shape the atomic ``complete_work``
    transition leaves behind (``status="done"``,
    the declared continuation fields, and the explicit
    ``completion_continuation`` the LoopX lifecycle records durably), so the
    probes read the bytes back through the provider seam rather than through
    an in-memory fixture.  The continuation is derived with the same LoopX
    helper the lifecycle write uses; a mutation may pin an explicit
    ``completion_continuation`` to model a contradictory record.
    """
    head, generation = load_head(provider, "goal-completion")
    todos = head["coordination"]["todos"]
    for todo_id, fields in todo_mutations.items():
        record = copy.deepcopy(todos[todo_id])
        record["status"] = "done"
        record["todo_revision"] = record["todo_revision"] + 1
        for key, value in fields.items():
            record[key] = value
        if "completion_continuation" not in record:
            record["completion_continuation"] = completion_continuation_for_write(
                no_followup=record.get("no_followup") is True,
                has_successor=bool(record.get("successor_todo_ids")),
            )
        todos[todo_id] = record
    result = provider.compare_and_put(generation, head)
    assert result["result"] == "applied", result


def _project_from_provider_head(provider) -> dict[str, dict]:
    """Read the head back through the provider and project every done record.

    Returns ``{todo_id: typed outcome}`` for each durably-done record (the seam
    is invoked after a completion write, so open records are not projected),
    using the head's full Todo id universe as ``existing_todo_ids`` (the
    read-side seam's provider-first shape: same projection, same id universe,
    no host JSON).
    """
    head, _generation = load_head(provider, "goal-completion")
    todos = head["coordination"]["todos"]
    existing = set(todos)
    outcomes: dict[str, dict] = {}
    for todo_id in sorted(todos):
        record = {"todo_id": todo_id, **todos[todo_id]}
        if record["status"] != "done":
            continue
        outcomes[todo_id] = project_durable_completion_outcome(
            todo=record,
            expected_todo_id=todo_id,
            existing_todo_ids=existing,
        )
    return outcomes


def probe_durable_completion_projection() -> None:
    provider = DeterministicProvider()
    bootstrap(
        provider,
        "goal-completion",
        ["todo_done01", "todo_done02", "todo_done03", "todo_next01"],
    )
    _evolve_completion_head(
        provider,
        {
            "todo_done01": {"successor_todo_ids": ["todo_next01"]},
            "todo_done02": {"no_followup": True},
            "todo_done03": {},
        },
    )
    outcomes = _project_from_provider_head(provider)
    assert outcomes["todo_done01"] == {
        "todo_id": "todo_done01",
        "continuation": "successor",
        "successor_todo_ids": ["todo_next01"],
    }
    assert outcomes["todo_done02"] == {
        "todo_id": "todo_done02",
        "continuation": "no_followup",
    }
    assert outcomes["todo_done03"] == {
        "todo_id": "todo_done03",
        "continuation": "active_goal",
    }
    # Replay stability: re-reading the same provider bytes and projecting again
    # yields the identical typed outcomes (no clock, no randomness).
    replay = _project_from_provider_head(provider)
    assert replay == outcomes
    out(
        "contract.durable_completion_projection",
        ok=True,
        continuations=[
            outcomes["todo_done01"]["continuation"],
            outcomes["todo_done02"]["continuation"],
            outcomes["todo_done03"]["continuation"],
        ],
        replay_stable=True,
    )


def probe_durable_completion_fail_closed() -> None:
    provider = DeterministicProvider()
    bootstrap(
        provider,
        "goal-completion",
        ["todo_done04", "todo_done05", "todo_done06", "todo_next01"],
    )
    _evolve_completion_head(
        provider,
        {
            # Contradiction: both no_followup and a (existing) successor.
            "todo_done04": {
                "no_followup": True,
                "successor_todo_ids": ["todo_next01"],
                "completion_continuation": "no_followup",
            },
            # Dangling: one declared successor exists, one does not.
            "todo_done05": {
                "successor_todo_ids": ["todo_next01", "todo_missing9"]
            },
            # The explicit continuation contradicts the recorded fields.
            "todo_done06": {
                "successor_todo_ids": ["todo_next01"],
                "completion_continuation": "active_goal",
            },
        },
    )
    head, _generation = load_head(provider, "goal-completion")
    todos = head["coordination"]["todos"]
    existing = set(todos)
    expected_failures = {
        "todo_done04": "both no_followup and successor_todo_ids",
        "todo_done05": "declares missing successor Todo ids: todo_missing9",
        "todo_done06": "completion_continuation contradicts successor_todo_ids",
    }
    for todo_id, expected in expected_failures.items():
        try:
            project_durable_completion_outcome(
                todo={"todo_id": todo_id, **todos[todo_id]},
                expected_todo_id=todo_id,
                existing_todo_ids=existing,
            )
        except ValueError as exc:
            assert expected in str(exc), (todo_id, str(exc))
        else:
            raise AssertionError(f"{todo_id} did not fail closed")
    # A durably done record without its explicit continuation is not
    # projectable: the seam fails closed instead of guessing.
    stripped = {"todo_id": "todo_done05", **todos["todo_done05"]}
    del stripped["completion_continuation"]
    stripped["successor_todo_ids"] = ["todo_next01"]
    try:
        project_durable_completion_outcome(
            todo=stripped, expected_todo_id="todo_done05", existing_todo_ids=existing
        )
    except ValueError as exc:
        assert "missing completion_continuation" in str(exc)
    else:
        raise AssertionError("missing completion_continuation did not fail closed")
    out(
        "contract.durable_completion_fail_closed",
        ok=True,
        contradiction_rejected=True,
        dangling_successor_rejected=True,
        continuation_contradiction_rejected=True,
        missing_continuation_rejected=True,
    )


class FakeNoKVClient:
    """Minimal double for the NoKV Python SDK ``Client`` surface the adapter uses.

    It raises the exception classes the SDK raises since NoKV 0.11.0
    (``nokv-python`` maps ``NotFound`` to ``FileNotFoundError`` and
    ``AlreadyExists`` to ``FileExistsError``; every other client failure stays
    ``RuntimeError``).  Generations restart at 1 per path lifetime and every
    replacement advances by one, like the live workspace.
    """

    def __init__(self):
        self.paths: dict[tuple[str, str], tuple[bytes, int]] = {}
        self.stat_failure: Exception | None = None
        self.read_failure: Exception | None = None

    def stat(self, workbench: str, path: str) -> dict:
        if self.stat_failure is not None:
            failure, self.stat_failure = self.stat_failure, None
            raise failure
        try:
            _bytes, generation = self.paths[(workbench, path)]
        except KeyError:
            raise FileNotFoundError("workspace request failed: path does not exist") from None
        return {"generation": generation}

    def read(self, workbench: str, path: str) -> dict:
        if self.read_failure is not None:
            failure, self.read_failure = self.read_failure, None
            raise failure
        try:
            data, generation = self.paths[(workbench, path)]
        except KeyError:
            raise FileNotFoundError("workspace request failed: path does not exist") from None
        return {"bytes": data, "metadata": {"generation": generation}}

    def publish_bytes(self, workbench: str, path: str, data: bytes, **options) -> dict:
        expected = options.get("expected_generation")
        current = self.paths.get((workbench, path))
        if expected is None:
            if current is not None:
                raise FileExistsError(
                    "artifact publication failed during complete: workspace request "
                    "failed: path already exists"
                )
            generation = 1
        else:
            if current is None or current[1] != expected:
                raise RuntimeError(
                    "artifact publication failed during complete: workspace request "
                    f"failed: path generation mismatch: expected {expected}"
                )
            generation = current[1] + 1
        self.paths[(workbench, path)] = (bytes(data), generation)
        return {"generation": generation}


def probe_nokv_adapter_exception_mapping() -> None:
    """The NoKV byte-CAS adapter classifies SDK failures by exception class only.

    ``load`` returns ``(None, 0)`` only for the SDK's typed missing signal
    (``FileNotFoundError``); any other client failure raises the typed
    ``ProviderUnavailableError`` instead of masquerading as an uninitialized
    goal or escaping as a bare ``RuntimeError``.  ``compare_and_put`` reports
    typed ``applied | conflict | ambiguous | failed`` for every SDK outcome:
    error prose is never a channel, because real non-missing failures carry
    messages such as ``invalid root route: root placement does not exist``.
    """

    client = FakeNoKVClient()
    goal_id = "adapter-mapping"
    provider = NoKVCoordinationProvider(client, "wb-adapter", goal_id)
    head = bootstrap_head(goal_id, {}, store_binding="probe:adapter")

    assert provider.load() == (None, 0)
    created = provider.compare_and_put(0, head)
    assert created == {"result": "applied", "provider_generation": 1}, created
    loaded, generation = provider.load()
    assert loaded == head and generation == 1

    # bootstrap race: the loser observed generation 0 before the winner landed
    lost_race = provider.compare_and_put(0, head)
    assert lost_race["result"] == "conflict", lost_race
    assert lost_race["current_provider_generation"] == 1
    provider._generation = lambda: 0  # the stat pre-check raced too
    lost_race_at_publish = provider.compare_and_put(0, head)
    assert lost_race_at_publish == {"result": "ambiguous"}, lost_race_at_publish
    del provider._generation

    # replacement CAS: stale expected generation, both before and at publish
    advanced = copy.deepcopy(head)
    advanced["authority_revision"] = 1
    replaced = provider.compare_and_put(1, advanced)
    assert replaced == {"result": "applied", "provider_generation": 2}, replaced
    stale = provider.compare_and_put(1, advanced)
    assert stale == {"result": "conflict", "current_provider_generation": 2}, stale
    provider._generation = lambda: 1
    stale_at_publish = provider.compare_and_put(1, advanced)
    assert stale_at_publish == {"result": "ambiguous"}, stale_at_publish
    del provider._generation

    # a provider failure before any publish attempt proves that nothing was written
    client.stat_failure = RuntimeError("RPC transport failed: connection refused")
    failed = provider.compare_and_put(2, advanced)
    assert failed["result"] == "failed", failed
    assert provider.load() == (advanced, 2)

    # A routing outage whose message carries a not-found token must classify
    # as unavailable, never as missing: (None, 0) would tell the authority
    # the goal is uninitialized and authorize a bootstrap-create during an
    # outage.  This is the real string shape ClientError::InvalidRoute
    # produces through the 0.11 SDK.
    routing_outage = RuntimeError("invalid root route: root placement does not exist")
    client.read_failure = routing_outage
    try:
        provider.load()
    except ProviderUnavailableError as exc:
        assert "root placement does not exist" in str(exc)
    else:
        raise AssertionError("routing outage was classified as missing")

    # The same routing outage during the CAS pre-check is a typed failed
    # verdict, never the conflict-or-create path a misclassified generation 0
    # would take.
    client.stat_failure = RuntimeError(
        "logical shard LogicalShardId([34]) was not found"
    )
    outage_verdict = provider.compare_and_put(2, advanced)
    assert outage_verdict["result"] == "failed", outage_verdict
    assert "was not found" in outage_verdict["error"]

    # A token-free outage is the same typed unavailable, not a bare
    # RuntimeError leak.
    client.read_failure = RuntimeError("connection refused by endpoint")
    try:
        provider.load()
    except ProviderUnavailableError:
        pass
    else:
        raise AssertionError("token-free outage did not raise typed unavailable")

    # Pre-0.11 SDKs signalled missing with RuntimeError prose.  They cannot
    # route the post-#465 control plane and are outside the pinned baseline,
    # so that prose now classifies as unavailable rather than missing.
    class LegacyClient(FakeNoKVClient):
        def read(self, workbench: str, path: str) -> dict:
            if (workbench, path) not in self.paths:
                raise RuntimeError("workspace request failed: path not found")
            return super().read(workbench, path)

    legacy = NoKVCoordinationProvider(LegacyClient(), "wb-legacy", goal_id)
    try:
        legacy.load()
    except ProviderUnavailableError:
        pass
    else:
        raise AssertionError("legacy prose was still classified as missing")

    # Corrupt persisted bytes and unserializable heads stay typed too, in
    # parity with the file provider's seam contract.
    corrupt_client = FakeNoKVClient()
    corrupt_client.paths[("wb-corrupt", f"goals/{goal_id}/coordination-head.json")] = (
        b"{not json",
        3,
    )
    corrupt = NoKVCoordinationProvider(corrupt_client, "wb-corrupt", goal_id)
    try:
        corrupt.load()
    except ProviderProtocolError:
        pass
    else:
        raise AssertionError("corrupt persisted bytes escaped untyped")
    unserializable = provider.compare_and_put(2, {"x": float("nan")})
    assert unserializable["result"] == "failed", unserializable
    assert "serializable" in unserializable["error"]

    # The authoritative CAS token is typed state at both ends of the seam.
    # A bool or otherwise invalid caller expectation is a typed failed
    # verdict before any client I/O, and a malformed SDK response carrying
    # generation true / a negative / a string must never be repaired into a
    # legitimate generation.
    class ExplodingClient:
        def __getattr__(self, name):
            raise AssertionError("no client I/O may happen for invalid input")

    untouchable = NoKVCoordinationProvider(ExplodingClient(), "wb-typed", goal_id)
    for invalid_expected in (True, False, -1, "1"):
        verdict = untouchable.compare_and_put(invalid_expected, head)
        assert verdict["result"] == "failed", (invalid_expected, verdict)
        assert "non-negative integer" in verdict["error"]

    class MalformedClient(FakeNoKVClient):
        def __init__(self, generation_value):
            super().__init__()
            self.generation_value = generation_value

        def stat(self, workbench, path):
            return {"generation": self.generation_value}

        def read(self, workbench, path):
            return {
                "bytes": b"{}",
                "metadata": {"generation": self.generation_value},
            }

    for bad_generation in (True, -3, "7", None):
        malformed = NoKVCoordinationProvider(
            MalformedClient(bad_generation), "wb-malformed", goal_id
        )
        try:
            malformed.load()
        except ProviderProtocolError:
            pass
        else:
            raise AssertionError(f"generation {bad_generation!r} was repaired")
        try:
            malformed._generation()
        except ProviderProtocolError:
            pass
        else:
            raise AssertionError(f"stat generation {bad_generation!r} was repaired")

    class ShapelessClient(FakeNoKVClient):
        def read(self, workbench, path):
            return {"metadata": {"generation": 1}}

    shapeless = NoKVCoordinationProvider(ShapelessClient(), "wb-shapeless", goal_id)
    try:
        shapeless.load()
    except ProviderProtocolError as exc:
        assert "bytes" in str(exc)
    else:
        raise AssertionError("missing read bytes escaped untyped")

    class BoolPublishClient(FakeNoKVClient):
        def publish_bytes(self, workbench, path, data, **options):
            return {"generation": True}

    bool_publish = NoKVCoordinationProvider(BoolPublishClient(), "wb-boolpub", goal_id)
    try:
        bool_publish.compare_and_put(0, head)
    except ProviderProtocolError:
        pass
    else:
        raise AssertionError("publish generation true was repaired to applied")

    out(
        "contract.nokv_adapter_exception_mapping",
        ok=True,
        uninitialized_load_typed=True,
        create_only_race_typed=True,
        stale_generation_typed=True,
        pre_publish_failure_typed=True,
        routing_outage_not_missing=True,
        outage_raises_typed_unavailable=True,
        legacy_prose_unsupported=True,
        corrupt_bytes_typed=True,
        unserializable_head_typed_failed=True,
        invalid_expected_generation_typed=True,
        malformed_generation_never_repaired=True,
        malformed_result_shape_typed=True,
    )


PROBES = (
    probe_bootstrap_and_preconditions,
    probe_a_b_replay_a,
    probe_operation_identity,
    probe_competing_claims,
    probe_crash_windows_and_ambiguity,
    probe_version_domains_and_retain_all,
    probe_nokv_adapter_exception_mapping,
    probe_durable_completion_projection,
    probe_durable_completion_fail_closed,
)


def run_contract() -> None:
    for probe in PROBES:
        probe()
    out("contract.summary", ok=True, probes=len(PROBES))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "contract":
        print("usage: python probes.py contract", file=sys.stderr)
        return 2
    run_contract()
    return 0


if __name__ == "__main__":
    sys.exit(main())
