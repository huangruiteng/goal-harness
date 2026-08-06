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

    def arm_load_barrier(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties)
        self._barrier_loads_left = parties

    def arm_fault(self, fault: str) -> None:
        if fault not in {
            "failed_before",
            "crash_before",
            "crash_after",
            "ambiguous_after",
        }:
            raise ValueError(f"unknown fault: {fault}")
        self._fault = fault

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
            self._aggregate = copy.deepcopy(aggregate)
            self._generation += self._generation_step
            generation = self._generation
            if self._fault == "crash_after":
                self._fault = None
                raise SimulatedCrash("crash_after")
            if self._fault == "ambiguous_after":
                self._fault = None
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


def probe_bootstrap_and_preconditions() -> None:
    provider = DeterministicProvider()
    authority = CoordinationAuthority(provider, "goal-preconditions", fixed_clock(1000))
    uninitialized = authority.apply(sample_envelope(
        operation_id="op-uninitialized",
        goal_id="goal-preconditions",
        todo_id="todo-known",
    ))
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
    missing = authority.apply(sample_envelope(
        operation_id="op-missing",
        goal_id="goal-preconditions",
        todo_id="todo-missing",
    ))
    stale = authority.apply(sample_envelope(
        operation_id="op-stale",
        goal_id="goal-preconditions",
        todo_id="todo-known",
        expected_todo_revision=6,
    ))
    ineligible = authority.apply(sample_envelope(
        operation_id="op-ineligible",
        agent_id="agent-not-allowed",
        goal_id="goal-preconditions",
        todo_id="todo-known",
    ))
    dependency_blocked = authority.apply(sample_envelope(
        operation_id="op-dependency-blocked",
        goal_id="goal-preconditions",
        todo_id="todo-dependency-blocked",
    ))
    gate_blocked = authority.apply(sample_envelope(
        operation_id="op-gate-blocked",
        goal_id="goal-preconditions",
        todo_id="todo-gate-blocked",
    ))
    head, generation = load_head(provider, "goal-preconditions")
    assert missing == {
        "result": "rejected",
        "reason": "todo_not_found",
        "observed_authority_revision": 0,
        "provider_generation": initial_generation,
    }
    assert stale["result"] == "conflict" and stale["reason"] == "todo_revision_mismatch"
    assert ineligible["result"] == "rejected" and ineligible["reason"] == "actor_ineligible"
    assert dependency_blocked["result"] == "rejected"
    assert dependency_blocked["reason"] == "dependencies_not_satisfied"
    assert gate_blocked["result"] == "rejected" and gate_blocked["reason"] == "gate_closed"
    assert head["authority_revision"] == 0 and head["receipt_index"] == {}
    assert generation == initial_generation
    private_todo = initial_todo()
    private_todo["raw_todo_body"] = "must not enter the shared head"
    try:
        bootstrap_aggregate("goal-private", {"todo-private": private_todo})
    except ValueError as exc:
        assert "fields do not match v0" in str(exc)
    else:
        raise AssertionError("unknown bootstrap field was copied into the head")
    absolute_path_todo = initial_todo()
    absolute_path_todo["repository"] = "/" + "synthetic/local/repository"
    try:
        bootstrap_aggregate("goal-private", {"todo-private": absolute_path_todo})
    except ValueError as exc:
        assert "repository is not portable" in str(exc)
    else:
        raise AssertionError("absolute repository path entered the shared head")
    credential_repository_todo = initial_todo()
    credential_repository_todo["repository"] = "git:" + "user@host/repository"
    invalid_revision_todo = initial_todo()
    invalid_revision_todo["code_revision"] = "review-ready"
    for unsafe_todo in (credential_repository_todo, invalid_revision_todo):
        try:
            bootstrap_aggregate("goal-private", {"todo-private": unsafe_todo})
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe repository metadata entered the shared head")
    out(
        "contract.bootstrap_and_preconditions",
        ok=True,
        uninitialized_failed=True,
        no_implicit_todo_creation=True,
        todo_revision_checked=True,
        eligibility_checked=True,
        dependency_and_gate_checked=True,
        bootstrap_privacy_allowlist_checked=True,
        repository_metadata_checked=True,
    )


def probe_a_b_replay_a() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-review", ["todo-review", "todo-followup"])
    authority = CoordinationAuthority(provider, "goal-review", fixed_clock(1100))
    envelope_a = sample_envelope(
        operation_id="op-review-a",
        goal_id="goal-review",
        todo_id="todo-review",
    )
    first_a = authority.apply(envelope_a)
    first_b = authority.apply(sample_envelope(
        operation_id="op-followup-b",
        goal_id="goal-review",
        todo_id="todo-followup",
        expected_authority_revision=1,
    ))
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
    original = sample_envelope(
        operation_id="op-stable",
        goal_id="goal-digest",
        todo_id="todo-original",
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
    provider = DeterministicProvider(generation_step=23)
    bootstrap(provider, "goal-race", ["todo-one-winner"])
    provider.arm_load_barrier(2)
    envelopes = [
        sample_envelope(
            operation_id=f"op-claim-{index}",
            agent_id=f"agent-{index}",
            device_id=f"device-{index}",
            goal_id="goal-race",
            todo_id="todo-one-winner",
        )
        for index in range(2)
    ]

    def run(index: int):
        return CoordinationAuthority(
            provider,
            "goal-race",
            fixed_clock(1300 + index),
        ).apply(envelopes[index])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, range(2)))
    applied = [result for result in results if result["result"] == "applied"]
    conflicts = [result for result in results if result["result"] == "conflict"]
    head, generation = load_head(provider, "goal-race")
    assert len(applied) == 1 and len(conflicts) == 1, results
    assert head["authority_revision"] == 1 and len(head["receipt_index"]) == 1
    assert generation == 46
    out(
        "contract.competing_claims",
        ok=True,
        applied=1,
        conflicts=1,
        authority_revision=1,
        provider_generation=generation,
    )


def probe_crash_windows_and_ambiguity() -> None:
    provider = DeterministicProvider()
    bootstrap(provider, "goal-faults", ["todo-before", "todo-after", "todo-ambiguous"])
    before = sample_envelope(
        operation_id="op-before",
        goal_id="goal-faults",
        todo_id="todo-before",
    )
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

    after = sample_envelope(
        operation_id="op-after",
        goal_id="goal-faults",
        todo_id="todo-after",
    )
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

    ambiguous = sample_envelope(
        operation_id="op-ambiguous",
        goal_id="goal-faults",
        todo_id="todo-ambiguous",
        expected_authority_revision=1,
    )
    provider.arm_fault("ambiguous_after")
    reconciled = CoordinationAuthority(provider, "goal-faults", fixed_clock(1600)).apply(
        ambiguous
    )
    final_head, _ = load_head(provider, "goal-faults")
    assert reconciled["result"] == "already_applied"
    assert final_head["authority_revision"] == 2 and len(final_head["receipt_index"]) == 2
    out(
        "contract.crash_windows_and_ambiguity",
        ok=True,
        before_cas_no_partial_state=True,
        failed_before_cas_no_write=True,
        after_cas_exact_receipt_recovered=True,
        ambiguous_reconciled_from_receipt=True,
        no_double_apply=True,
    )


def probe_version_domains_and_retain_all() -> None:
    provider = DeterministicProvider(generation_step=101)
    bootstrap(provider, "goal-versions", ["todo-a", "todo-b"])
    authority = CoordinationAuthority(provider, "goal-versions", fixed_clock(1700))
    first = authority.apply(sample_envelope(
        operation_id="op-a",
        goal_id="goal-versions",
        todo_id="todo-a",
    ))
    second = authority.apply(sample_envelope(
        operation_id="op-b",
        goal_id="goal-versions",
        todo_id="todo-b",
        expected_authority_revision=1,
    ))
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
