"""The RFC ``loopx_coordination_head_v1`` aggregate: schema, canonical bytes, adapters.

Stage 2 slice: the head is the one CAS document a coordination provider stores.
This file pins the aggregate contract before any executor logic exists.
"""

from __future__ import annotations

import copy
import json

import pytest

from loopx.control_plane.coordination.authority_core import (
    HandoffMode,
    TodoSnapshot,
)
from loopx.control_plane.coordination.goal_state_shadow import (
    bootstrap_head_from_goal_state,
)
from loopx.control_plane.coordination.head import (
    HEAD_SCHEMA_VERSION,
    HeadValidationError,
    bootstrap_head,
    canonical_head_bytes,
    claim_snapshot_for_todo,
    head_digest,
    validated_head,
)


def eligibility() -> dict:
    return {
        "authorization_projection_revision": 3,
        "authorization_projection_digest": "sha256:bootstrap-auth",
        "allowed_agent_ids": ["agent-a", "agent-b"],
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


def head() -> dict:
    return bootstrap_head(
        "goal-a", {"todo-1": todo(), "todo-2": todo()}, store_binding="test:store"
    )


# ---- bootstrap + validation -------------------------------------------------


def test_bootstrap_head_matches_rfc_shape() -> None:
    built = head()
    assert built["schema_version"] == HEAD_SCHEMA_VERSION == "loopx_coordination_head_v1"
    assert built["goal_id"] == "goal-a"
    assert built["handoff_mode"] == "hard_lease"
    assert built["store_binding"] == "test:store"
    assert built["authority_revision"] == 0
    assert set(built["coordination"]) == {"todos", "leases"}
    assert built["coordination"]["leases"] == {}
    assert built["receipt_index"] == {}
    assert built["receipt_retention"] == {"mode": "retain_all_v0"}
    assert validated_head(built, goal_id="goal-a") is built


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda h: h.pop("receipt_retention"), "fields"),
        (lambda h: h.update(receipt_retention={"mode": "bounded"}), "retain_all_v0"),
        (lambda h: h.update(schema_version="v1"), "identity"),
        (lambda h: h.update(goal_id="other"), "identity"),
        (lambda h: h.update(authority_revision="9"), "authority_revision"),
        (lambda h: h.update(authority_revision=True), "authority_revision"),
        (lambda h: h.update(handoff_mode="soft_claim"), "hard_lease"),
        (lambda h: h.update(handoff_mode="legacy"), "hard_lease"),
        (lambda h: h["coordination"].pop("leases"), "todos and leases"),
        (lambda h: h.update(extra=True), "fields"),
    ],
)
def test_validated_head_fails_closed(mutate, match) -> None:
    broken = head()
    mutate(broken)
    with pytest.raises(HeadValidationError, match=match):
        validated_head(broken, goal_id="goal-a")


def test_bootstrap_rejects_non_portable_todo() -> None:
    with pytest.raises(HeadValidationError, match="repository"):
        bootstrap_head("goal-a", {"todo-1": todo(repository="/abs/path")}, store_binding="test:store")
    with pytest.raises(HeadValidationError, match="open and unclaimed"):
        bootstrap_head("goal-a", {"todo-1": todo(claimed_by="agent-a")}, store_binding="test:store")
    with pytest.raises(HeadValidationError, match="fields"):
        bad = todo()
        bad.pop("last_lease_epoch")
        bootstrap_head("goal-a", {"todo-1": bad}, store_binding="test:store")


@pytest.mark.parametrize(
    "overrides",
    [
        {"todo_revision": True},
        {"todo_revision": -1},
        {"last_lease_epoch": True},
        {"last_lease_epoch": -7},
    ],
)
def test_bootstrap_rejects_bool_and_negative_counts(overrides) -> None:
    """bool is an int subclass; a ``True`` epoch would mint ``True + 1`` and a
    negative one would mint decreasing epochs, so both fail closed exactly like
    the local core's corrupt_lease."""

    with pytest.raises(HeadValidationError):
        bootstrap_head("goal-a", {"todo-1": todo(**overrides)}, store_binding="test:store")


def test_bootstrap_rejects_bool_eligibility_revision() -> None:
    poisoned = eligibility()
    poisoned["gate_revision"] = True
    with pytest.raises(HeadValidationError, match="eligibility revisions"):
        bootstrap_head("goal-a", {"todo-1": todo(eligibility=poisoned)}, store_binding="test:store")


def leased_head() -> dict:
    built = head()
    built["coordination"]["todos"]["todo-1"].update(
        claimed_by="agent-a",
        last_lease_epoch=7,
    )
    built["coordination"]["leases"]["todo-1"] = {
        "lease_id": "lease_abc",
        "owner": "agent-a",
        "lease_epoch": 7,
        "expires_at": "2027-01-01T00:00:00.000Z",
        "write_scopes": [],
    }
    return built


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda lease: lease.update(lease_epoch=0), "positive"),
        (lambda lease: lease.update(lease_epoch=True), "positive"),
        (lambda lease: lease.update(owner=""), "identity"),
        (lambda lease: lease.update(expires_at=123), "timestamp"),
        (lambda lease: lease.update(expires_at="not-a-time"), "timestamp"),
        # Naive timestamps read differently under each host's local timezone,
        # so the same persisted bytes would be active on one endpoint and
        # expired on another; v0 mints and accepts aware UTC only.
        (lambda lease: lease.update(expires_at="2030-01-01T00:00:00"), "timestamp"),
        (
            lambda lease: lease.update(expires_at="2030-01-01T00:00:00+08:00"),
            "timestamp",
        ),
        (lambda lease: lease.update(write_scopes=["repo"]), "write_scopes"),
    ],
)
def test_validated_head_rejects_corrupt_lease_records(mutate, match) -> None:
    assert validated_head(leased_head(), goal_id="goal-a")
    broken = leased_head()
    mutate(broken["coordination"]["leases"]["todo-1"])
    with pytest.raises(HeadValidationError, match=match):
        validated_head(broken, goal_id="goal-a")


@pytest.mark.parametrize(
    ("corruption", "match"),
    [
        ("missing_lease", "claimed todo.*active lease"),
        ("unclaimed_with_lease", "unclaimed todo.*active lease"),
        ("owner_mismatch", "owner.*claimed_by"),
        ("epoch_mismatch", "lease_epoch.*watermark"),
    ],
)
def test_validated_head_binds_claim_to_its_live_lease(
    corruption: str,
    match: str,
) -> None:
    broken = leased_head()
    todo_record = broken["coordination"]["todos"]["todo-1"]
    lease_record = broken["coordination"]["leases"]["todo-1"]
    if corruption == "missing_lease":
        del broken["coordination"]["leases"]["todo-1"]
    elif corruption == "unclaimed_with_lease":
        todo_record["claimed_by"] = None
    elif corruption == "owner_mismatch":
        lease_record["owner"] = "agent-b"
    else:
        todo_record["last_lease_epoch"] = 6

    with pytest.raises(HeadValidationError, match=match):
        validated_head(broken, goal_id="goal-a")


_RECEIPT_DIGEST = "sha256:" + "0" * 64


def receipted_head() -> dict:
    built = leased_head()
    built["receipt_index"]["op-1"] = {
        "request_digest": _RECEIPT_DIGEST,
        "original_receipt": {
            "schema_version": "loopx_authority_receipt_v0",
            "operation_id": "op-1",
            "request_digest": _RECEIPT_DIGEST,
            "command": "claim_work",
            "actor": {"agent_id": "agent-a", "device_id": "dev-a"},
            "todo_id": "todo-1",
            "accepted_authority_revision": 1,
            "accepted_todo_revision": 8,
            "applied_at": "2027-01-01T00:00:00.000Z",
            "lease_id": "lease_abc",
            "lease_epoch": 7,
            "expires_at": "2027-01-01T00:10:00.000Z",
        },
    }
    return built


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda e: e.update(original_receipt={}), "outside the v0 slice"),
        (lambda e: e.update(extra=True), "fields do not match"),
        (lambda e: e.update(request_digest="sha256:bootstrap"), "request_digest"),
        (
            lambda e: e["original_receipt"].update(operation_id="op-2"),
            "its own operation id",
        ),
        (
            lambda e: e["original_receipt"].update(
                request_digest="sha256:" + "1" * 64
            ),
            "disagrees with its index entry",
        ),
        (
            lambda e: e["original_receipt"].update(todo_id="todo-9"),
            "todo the head does not carry",
        ),
        (
            lambda e: e["original_receipt"].update(accepted_todo_revision=0),
            "accepted revisions",
        ),
        (lambda e: e["original_receipt"].update(lease_epoch=True), "lease_epoch"),
        (
            lambda e: e["original_receipt"].update(applied_at="not-a-time"),
            "timestamps",
        ),
        (
            lambda e: e["original_receipt"].update(applied_at="2030-01-01T00:00:00"),
            "timestamps",
        ),
        (
            lambda e: e["original_receipt"].update(
                expires_at="2030-01-01T00:00:00+08:00"
            ),
            "timestamps",
        ),
        (
            lambda e: e["original_receipt"].update(actor={"agent_id": ""}),
            "actor identity",
        ),
        (
            lambda e: e["original_receipt"].update(command="transfer_work"),
            "outside the v0 slice",
        ),
        (
            lambda e: e["original_receipt"].update(command="release_work"),
            "fields do not match",
        ),
    ],
)
def test_validated_head_rejects_corrupt_receipt_entries(mutate, match) -> None:
    """Persisted receipts cross the same trust boundary as todos and leases:
    every field the executor later dereferences unconditionally is validated
    here, so a digest-matching entry with a gutted ``original_receipt`` fails
    closed instead of surfacing as a KeyError inside replay."""

    assert validated_head(receipted_head(), goal_id="goal-a")
    broken = receipted_head()
    mutate(broken["receipt_index"]["op-1"])
    with pytest.raises(HeadValidationError, match=match):
        validated_head(broken, goal_id="goal-a")


# ---- canonical bytes + digest ----------------------------------------------


def test_canonical_bytes_are_key_order_independent() -> None:
    a = head()
    b = json.loads(json.dumps(a))
    b["coordination"] = dict(reversed(list(b["coordination"].items())))
    assert canonical_head_bytes(a) == canonical_head_bytes(b)
    assert head_digest(a) == head_digest(b)
    assert head_digest(a).startswith("sha256:")


def test_canonical_bytes_change_with_content() -> None:
    a = head()
    b = copy.deepcopy(a)
    b["authority_revision"] = 1
    assert canonical_head_bytes(a) != canonical_head_bytes(b)


def test_canonical_bytes_fail_closed_on_unrepresentable_values() -> None:
    """Non-finite floats would serialize into bytes a strict RFC 8259 reader
    rejects, and non-JSON objects have no canonical form at all; neither may
    ever become "canonical" bytes or an unclassified exception."""

    poisoned = head()
    poisoned["coordination"]["todos"]["todo-1"]["eligibility"][
        "dependency_revision"
    ] = float("nan")
    with pytest.raises(HeadValidationError, match="serializable"):
        canonical_head_bytes(poisoned)
    with pytest.raises(HeadValidationError, match="serializable"):
        canonical_head_bytes({"x": object()})


# ---- snapshot adapter -------------------------------------------------------


def test_claim_snapshot_maps_aggregate_facts_into_core_types() -> None:
    built = head()
    snapshot = claim_snapshot_for_todo(built, "todo-1")
    # The shared head carries claim and lease together, so the core's
    # hard-lease holder gate is a live invariant for it.
    assert snapshot.handoff_mode is HandoffMode.HARD_LEASE
    assert snapshot.registered_agents == ("agent-a", "agent-b")
    assert isinstance(snapshot.todo, TodoSnapshot)
    assert snapshot.todo.todo_id == "todo-1"
    assert snapshot.todo.status == "open"
    assert snapshot.todo.claimed_by is None
    # No lease in the head projects the no-ABA tombstone: the epoch watermark
    # from the todo, not an absent lease, so the core mints last+1.
    assert snapshot.lease is not None
    assert snapshot.lease.present is False and snapshot.lease.active is False
    assert snapshot.lease.lease_epoch == 6 and snapshot.lease.version == 6
    with pytest.raises(HeadValidationError, match="todo"):
        claim_snapshot_for_todo(built, "todo-9")


def test_snapshot_mode_is_read_from_the_head() -> None:
    """The mode is the head's revision-covered fact, not an adapter constant:
    v0 validation pins it to hard_lease, and the projection follows whatever
    the (validated) document says rather than re-deciding it."""

    built = head()
    assert claim_snapshot_for_todo(built, "todo-1").handoff_mode is HandoffMode.HARD_LEASE
    relaxed = {**built, "handoff_mode": "legacy"}
    assert claim_snapshot_for_todo(relaxed, "todo-1").handoff_mode is HandoffMode.LEGACY


# ---- shadow bootstrap from the local goal state -----------------------------
#
# Fixtures are written by loopx's own writers so the parity is against the real
# on-disk format, not a hand-approximated markdown.


def _shadow_workspace(tmp_path):
    import json as _json

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\ngoal_id: shadow-goal\nupdated_at: 2026-08-01T00:00:00+00:00\n"
        "handoff_mode: hard_lease\n---\n\n## Agent Todo\n\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        _json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": "shadow-goal",
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a", "agent-b"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state


def _seed_todos(registry):
    from loopx.control_plane.work_items.task_lease import acquire_task_lease
    from loopx.todos import add_goal_todo, complete_goal_todo

    claimed = add_goal_todo(
        registry_path=registry, goal_id="shadow-goal", role="agent",
        text="Ship the provider slice.", task_class="advancement_task",
        claimed_by="agent-a",
    )
    open_todo = add_goal_todo(
        registry_path=registry, goal_id="shadow-goal", role="agent",
        text="Review the provider slice.", task_class="advancement_task",
    )
    done = add_goal_todo(
        registry_path=registry, goal_id="shadow-goal", role="agent",
        text="Land the prerequisite.", task_class="advancement_task",
        claimed_by="agent-b",
    )
    acquire_task_lease(
        registry_path=registry,
        runtime_root=registry.parent / "runtime",
        goal_id="shadow-goal",
        todo_id=done["todo_id"],
        owner="agent-b",
        idempotency_key="turn-lease-1",
        ttl_seconds=600,
    )
    complete_goal_todo(
        registry_path=registry, goal_id="shadow-goal", todo_id=done["todo_id"],
        agent_id="agent-b", evidence="landed", no_followup=True,
        task_lease_idempotency_key="turn-lease-1",
        task_lease_expected_version=1,
    )
    return claimed["todo_id"], open_todo["todo_id"], done["todo_id"]


def test_bootstrap_from_goal_state_shadows_open_unclaimed_todos(tmp_path) -> None:
    registry, state = _shadow_workspace(tmp_path)
    claimed_id, open_id, done_id = _seed_todos(registry)

    built, report = bootstrap_head_from_goal_state(
        state.read_text(encoding="utf-8"),
        goal_id="shadow-goal",
        store_binding="test:store",
        repository="git:example/repo",
        code_revision="0123456789abcdef",
        allowed_agent_ids=["agent-a", "agent-b"],
        with_report=True,
    )

    todos = built["coordination"]["todos"]
    assert set(todos) == {open_id}
    entry = todos[open_id]
    assert entry["status"] == "open" and entry["claimed_by"] is None
    assert entry["todo_revision"] == 0 and entry["last_lease_epoch"] == 0
    assert entry["eligibility"]["allowed_agent_ids"] == ["agent-a", "agent-b"]
    assert validated_head(built, goal_id="shadow-goal") is built
    assert report["skipped"] == {claimed_id: "claimed", done_id: "done"}
    assert report["source_handoff_mode"] == "hard_lease"


def test_bootstrap_from_goal_state_read_parity_with_the_projection(tmp_path) -> None:
    """Every open unclaimed todo in the real projection lands in the head, and
    nothing else does — the RFC section 11 shadow read-parity for this slice."""

    from loopx.status import parse_active_state_todos

    registry, state = _shadow_workspace(tmp_path)
    _seed_todos(registry)
    text = state.read_text(encoding="utf-8")
    built = bootstrap_head_from_goal_state(
        text,
        goal_id="shadow-goal",
        store_binding="test:store",
        repository="git:example/repo",
        code_revision="0123456789abcdef",
        allowed_agent_ids=["agent-a"],
    )
    projected = parse_active_state_todos(text)["agent_todos"]["items"]
    expected = {
        item["todo_id"]
        for item in projected
        if not item.get("done") and not item.get("claimed_by")
    }
    assert set(built["coordination"]["todos"]) == expected


def test_bootstrap_from_soft_claim_goal_fails_closed() -> None:
    """A soft_claim goal's declared mode rejects lease minting locally; shared
    claim_work mints a lease on every accepted claim, so migrating such a goal
    would silently invert its semantics. Bootstrap refuses instead."""

    state_text = (
        "---\ngoal_id: shadow-goal\nupdated_at: 2026-08-01T00:00:00+00:00\n"
        "handoff_mode: soft_claim\n---\n\n## Agent Todo\n\n"
    )
    with pytest.raises(HeadValidationError, match="soft_claim"):
        bootstrap_head_from_goal_state(
            state_text,
            goal_id="shadow-goal",
            store_binding="test:store",
            repository="git:example/repo",
            code_revision="0123456789abcdef",
            allowed_agent_ids=["agent-a"],
        )
