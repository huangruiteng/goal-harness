"""Deterministic probes for the coordination authority proof.

Run ``python probes.py contract`` without NoKV or external services.  The
claim/CAS probes do not qualify NoKV restart, recovery, GC, HA, or a live
deployment.  The durable-completion probes are the read-side comparison
registered by RFC shared-goal-authority-state-provider-v0 (later runtime
qualification slice): they prove the provider byte-CAS can hold and read back
a post-completion head whose durable records project to the same typed
continuation outcomes (``successor | no_followup | active_goal``, fail-closed
on contradiction/dangling) as the LoopX projection seam.  They do not
implement or qualify the atomic ``complete_todo_with_successor`` write side.
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

from loopx.control_plane.todos.completion_state import (  # noqa: E402
    completion_continuation_for_write,
)
from loopx.control_plane.todos.durable_completion import (  # noqa: E402
    project_durable_completion_outcome,
)

from provider import (  # noqa: E402
    CoordinationAuthority,
    NoKVCoordinationProvider,
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


def _evolve_completion_head(provider, todo_mutations: dict) -> None:
    """CAS-write an evolved post-completion head over a bootstrapped open one.

    The v0 authority proof only knows ``claim_work``; durable completion is a
    later slice.  Each mutated todo is committed the way the future atomic
    ``complete_todo_with_successor`` write will leave it (``status="done"``,
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
    ``AlreadyExists`` to ``FileExistsError``; other RPC failures stay
    ``RuntimeError``).  Generations restart at 1 per path lifetime and every
    replacement advances by one, like the live workspace.
    """

    def __init__(self):
        self.paths: dict[tuple[str, str], tuple[bytes, int]] = {}
        self.stat_failure: Exception | None = None

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
    """The NoKV byte-CAS adapter must classify SDK exceptions into RFC verbs.

    ``load`` returns ``(None, 0)`` for an uninitialized head, and
    ``compare_and_put`` returns typed ``applied | conflict | ambiguous | failed``
    for every SDK outcome it can observe: it never leaks ``FileNotFoundError``,
    ``FileExistsError``, or ``RuntimeError`` to the authority.
    """

    client = FakeNoKVClient()
    goal_id = "adapter-mapping"
    provider = NoKVCoordinationProvider(client, "wb-adapter", goal_id)
    head = bootstrap_aggregate(goal_id, {})

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

    # legacy SDKs raised RuntimeError for a missing path; both spellings stay classified
    class LegacyClient(FakeNoKVClient):
        def read(self, workbench: str, path: str) -> dict:
            if (workbench, path) not in self.paths:
                raise RuntimeError("workspace request failed: path not found")
            return super().read(workbench, path)

        def stat(self, workbench: str, path: str) -> dict:
            if (workbench, path) not in self.paths:
                raise RuntimeError("workspace request failed: path not found")
            return super().stat(workbench, path)

    legacy = NoKVCoordinationProvider(LegacyClient(), "wb-legacy", goal_id)
    assert legacy.load() == (None, 0)
    assert legacy.compare_and_put(0, head)["result"] == "applied"

    out(
        "contract.nokv_adapter_exception_mapping",
        ok=True,
        uninitialized_load_typed=True,
        create_only_race_typed=True,
        stale_generation_typed=True,
        pre_publish_failure_typed=True,
        legacy_runtime_error_still_classified=True,
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


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "contract"
    {"contract": run_contract}[command]()
