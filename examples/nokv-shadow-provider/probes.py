"""Deterministic probes for the claim-only coordination authority proof.

Run ``python probes.py contract`` without NoKV or external services.  These
probes do not qualify NoKV restart, recovery, GC, HA, or a live deployment.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from provider import (  # noqa: E402
    CoordinationAuthority,
    bootstrap_aggregate,
    sample_envelope,
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


def fixed_clock(value: float):
    return lambda: value


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
    head = bootstrap_aggregate(
        goal_id,
        {todo_id: initial_todo() for todo_id in todo_ids},
    )
    result = provider.compare_and_put(
        0,
        head,
    )
    assert result["result"] == "applied", result
    return result["provider_generation"]


def load_head(provider, goal_id: str):
    del goal_id  # provider handles are already bound to one goal key
    return provider.load()


def assert_exact_replay(first: dict, replay: dict) -> None:
    assert first["result"] == "applied", first
    assert replay["result"] == "already_applied", replay
    assert replay["original_receipt"] == first["original_receipt"], (first, replay)


def claim(operation_id: str, goal_id: str, todo_id: str, **values) -> dict:
    return sample_envelope(
        operation_id=operation_id,
        goal_id=goal_id,
        todo_id=todo_id,
        **values,
    )


def assert_bootstrap_rejected(todo: dict, message: str | None = None) -> None:
    try:
        bootstrap_aggregate("goal-private", {"todo-private": todo})
    except ValueError as exc:
        if message is not None:
            assert message in str(exc)
    else:
        raise AssertionError("unsafe todo entered the shared head")


def probe_bootstrap_and_preconditions() -> None:
    provider = DeterministicProvider()
    authority = CoordinationAuthority(provider, "goal-preconditions", fixed_clock(1000))
    uninitialized = authority.apply(
        claim("op-uninitialized", "goal-preconditions", "todo-known")
    )
    assert uninitialized["result"] == "failed"
    assert uninitialized["reason"] == "coordination_head_uninitialized"

    initial_head = bootstrap_aggregate(
        "goal-preconditions",
        {
            "todo-known": initial_todo(),
            "todo-dependency-blocked": initial_todo(dependencies_satisfied=False),
            "todo-gate-blocked": initial_todo(gates_open=False),
        },
    )
    bootstrap_result = provider.compare_and_put(0, initial_head)
    assert bootstrap_result["result"] == "applied"
    initial_generation = bootstrap_result["provider_generation"]
    missing = authority.apply(claim("op-missing", "goal-preconditions", "todo-missing"))
    stale = authority.apply(
        claim("op-stale", "goal-preconditions", "todo-known", expected_todo_revision=6)
    )
    expected_preconditions = initial_todo()["eligibility"]
    expected_preconditions = {
        field: expected_preconditions[field]
        for field in (
            "authorization_projection_revision",
            "authorization_projection_digest",
            "dependency_revision",
            "gate_revision",
        )
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
        changed_preconditions.append(authority.apply(claim(
            f"op-stale-{field}",
            "goal-preconditions",
            "todo-known",
            expected_preconditions=preconditions,
        )))
    ineligible = authority.apply(claim(
        "op-ineligible",
        "goal-preconditions",
        "todo-known",
        agent_id="agent-not-allowed",
    ))
    dependency_blocked = authority.apply(
        claim("op-dependency-blocked", "goal-preconditions", "todo-dependency-blocked")
    )
    gate_blocked = authority.apply(
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
    )


def probe_a_b_replay_a() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-review", ["todo-review", "todo-followup"])
    authority = CoordinationAuthority(provider, "goal-review", fixed_clock(1100))
    envelope_a = claim("op-review-a", "goal-review", "todo-review")
    first_a = authority.apply(envelope_a)
    first_b = authority.apply(claim("op-followup-b", "goal-review", "todo-followup"))
    replay_a = CoordinationAuthority(provider, "goal-review", fixed_clock(9000)).apply(
        envelope_a
    )
    head, generation = load_head(provider, "goal-review")
    assert first_b["result"] == "applied"
    assert_exact_replay(first_a, replay_a)
    assert head["authority_revision"] == 2 and generation == 51
    assert head["receipt_index"]["op-review-a"]["original_receipt"] == first_a[
        "original_receipt"
    ]
    assert len(head["receipt_index"]) == 2
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
    authority = CoordinationAuthority(provider, "goal-digest", fixed_clock(1200))
    original = claim(
        "op-stable",
        "goal-digest",
        "todo-original",
        transport={"attempt": 1, "trace_id": "trace-a"},
    )
    first = authority.apply(original)
    transport_retry = copy.deepcopy(original)
    transport_retry["transport"] = {"attempt": 2, "trace_id": "trace-b"}
    assert_exact_replay(first, authority.apply(transport_retry))

    changed = copy.deepcopy(original)
    changed["command"]["todo_id"] = "todo-mutated"
    mismatch = authority.apply(changed)
    assert mismatch["result"] == "rejected"
    assert mismatch["reason"] == "operation_identity_mismatch"
    unknown = copy.deepcopy(original)
    unknown["unexpected_semantic_field"] = True
    try:
        authority.apply(unknown)
    except ValueError as exc:
        assert "unknown command envelope fields" in str(exc)
    else:
        raise AssertionError("unknown semantic field was ignored")
    head, _ = load_head(provider, "goal-digest")
    assert len(head["receipt_index"]) == 1
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
            return CoordinationAuthority(
                provider,
                goal_id,
                fixed_clock(1300 + index),
            ).apply(envelopes[index])

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, range(2)))

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
    replayed = CoordinationAuthority(
        independent_provider,
        "goal-independent",
        fixed_clock(9000),
    ).apply(independent_envelopes[0])
    assert_exact_replay(independent_results[0], replayed)
    assert load_head(independent_provider, "goal-independent") == (
        independent_head,
        independent_generation,
    )
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
    failed = CoordinationAuthority(provider, "goal-faults", fixed_clock(1400)).apply(
        before
    )
    assert failed["result"] == "failed"
    assert failed["reason"] == "provider_failed_before_cas"
    head, generation = load_head(provider, "goal-faults")
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}
    assert generation == 17
    provider.arm_fault("crash_before")
    try:
        CoordinationAuthority(provider, "goal-faults", fixed_clock(1400)).apply(before)
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
        CoordinationAuthority(provider, "goal-faults", fixed_clock(1500)).apply(after)
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("after-CAS crash was not injected")
    committed, committed_generation = load_head(provider, "goal-faults")
    durable_receipt = committed["receipt_index"]["op-after"]["original_receipt"]
    replay = CoordinationAuthority(provider, "goal-faults", fixed_clock(9000)).apply(after)
    assert replay["result"] == "already_applied"
    assert replay["original_receipt"] == durable_receipt
    assert load_head(provider, "goal-faults") == (committed, committed_generation)

    ambiguous = claim("op-ambiguous", "goal-faults", "todo-ambiguous")
    provider.arm_fault("ambiguous_after")
    reconciled = CoordinationAuthority(provider, "goal-faults", fixed_clock(1600)).apply(
        ambiguous
    )
    final_head, _ = load_head(provider, "goal-faults")
    assert reconciled["result"] == "already_applied"
    assert final_head["authority_revision"] == 2 and len(final_head["receipt_index"]) == 2

    ambiguous_before_provider = DeterministicProvider()
    bootstrap(ambiguous_before_provider, "goal-ambiguous-before", ["todo-target"])
    before_head = load_head(ambiguous_before_provider, "goal-ambiguous-before")
    ambiguous_before_provider.arm_fault("ambiguous_before")
    unproved = CoordinationAuthority(
        ambiguous_before_provider,
        "goal-ambiguous-before",
        fixed_clock(1650),
    ).apply(claim("op-unproved", "goal-ambiguous-before", "todo-target"))
    assert unproved["result"] == "failed"
    assert unproved["reason"] == "provider_outcome_unproved"
    assert load_head(ambiguous_before_provider, "goal-ambiguous-before") == before_head

    ambiguous_advance_provider = DeterministicProvider()
    bootstrap(ambiguous_advance_provider, "goal-ambiguous-advance", ["todo-target"])
    ambiguous_advance_provider.arm_fault("ambiguous_with_unrelated_advance")
    retried = CoordinationAuthority(
        ambiguous_advance_provider,
        "goal-ambiguous-advance",
        fixed_clock(1675),
    ).apply(claim("op-retried", "goal-ambiguous-advance", "todo-target"))
    retried_head, _ = load_head(ambiguous_advance_provider, "goal-ambiguous-advance")
    assert retried["result"] == "applied"
    assert retried_head["authority_revision"] == 1
    assert set(retried_head["receipt_index"]) == {"op-retried"}

    ambiguous_committed_provider = DeterministicProvider()
    bootstrap(ambiguous_committed_provider, "goal-ambiguous-committed", ["todo-target"])
    ambiguous_committed_provider.arm_fault("ambiguous_after_with_unrelated_advance")
    recovered = CoordinationAuthority(
        ambiguous_committed_provider,
        "goal-ambiguous-committed",
        fixed_clock(1685),
    ).apply(claim("op-recovered", "goal-ambiguous-committed", "todo-target"))
    recovered_head, _ = load_head(
        ambiguous_committed_provider,
        "goal-ambiguous-committed",
    )
    assert recovered["result"] == "already_applied"
    assert recovered_head["authority_revision"] == 1
    assert set(recovered_head["receipt_index"]) == {"op-recovered"}

    contention_provider = DeterministicProvider()
    bootstrap(contention_provider, "goal-contention", ["todo-target"])
    contention_provider.arm_contention(8)
    exhausted = CoordinationAuthority(
        contention_provider,
        "goal-contention",
        fixed_clock(1700),
    ).apply(claim("op-contention", "goal-contention", "todo-target"))
    contention_head, _ = load_head(contention_provider, "goal-contention")
    assert exhausted["result"] == "failed"
    assert exhausted["reason"] == "provider_contention_exhausted"
    assert "op-contention" not in contention_head["receipt_index"]
    assert contention_head["coordination"]["todos"]["todo-target"]["status"] == "open"
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
    authority = CoordinationAuthority(provider, "goal-versions", fixed_clock(1700))
    first = authority.apply(claim("op-a", "goal-versions", "todo-a"))
    second = authority.apply(claim("op-b", "goal-versions", "todo-b"))
    head, generation = load_head(provider, "goal-versions")
    assert generation == 303 and head["authority_revision"] == 2
    assert first["original_receipt"]["lease_epoch"] == 1
    assert second["original_receipt"]["lease_epoch"] == 1
    assert head["receipt_retention"] == {"mode": "retain_all_v0"}
    assert len(head["receipt_index"]) == 2
    out(
        "contract.version_domains_and_retain_all",
        ok=True,
        provider_generation=generation,
        authority_revision=2,
        lease_epochs=[1, 1],
        receipt_retention="retain_all_v0",
        receipt_count=2,
    )


PROBES = (
    probe_bootstrap_and_preconditions,
    probe_a_b_replay_a,
    probe_operation_identity,
    probe_competing_claims,
    probe_crash_windows_and_ambiguity,
    probe_version_domains_and_retain_all,
)


def run_contract() -> None:
    for probe in PROBES:
        probe()
    out("contract.summary", ok=True, probes=len(PROBES))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "contract"
    {"contract": run_contract}[command]()
