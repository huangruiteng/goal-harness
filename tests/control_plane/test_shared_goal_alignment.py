"""Stage 1 read-only shared goal alignment projection tests.

Every fixture Todo metadata line must only use tokens that exist in
``_TODO_METADATA_FIELD_SCHEMA`` (``todos/contract.py``): the parser silently
drops unknown keys, so an invented token would make the fixture lie. The
builder below asserts each ``todo_id`` actually parsed before any projection
runs, so a silently-ignored metadata line fails the fixture itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.effect_runtime import (
    EffectRuntimeRejected,
    effect_runtime_result,
)
from loopx.control_plane.goals import shared_goal_alignment
from loopx.control_plane.goals.shared_goal_alignment import (
    project_shared_goal_alignment,
)
from loopx.control_plane.todos.active_state_todo_parser import (
    parse_active_state_todos,
)
from loopx.event_sourced_state import (
    AppendOnlyStateEventStore,
    TODO_ADDED,
    make_state_event,
)

GOAL_ID = "goal-stage1"
AGENTS = ("agent-a", "agent-b")
EVENT_LOG_NAME = "events.jsonl"

STATE_HEADER_LINES = [
    "---",
    "status: active",
    "updated_at: 2026-09-01T00:00:00+00:00",
    "---",
    "",
    "# Stage 1 Alignment Fixture",
    "",
    "## Next Action",
    "",
    "Shared compatibility prose; it must never enter the projection digest.",
    "",
    "## Agent Todo",
    "",
]


def _todo_lines(specs: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for spec in specs:
        tokens = " ".join(f"{key}={value}" for key, value in spec.items())
        lines.append(f"- [ ] [{spec.get('priority', 'P1')}] {spec['text']}")
        lines.append(f"  <!-- loopx:todo {tokens} -->")
    return lines


def _write_fixture(
    root: Path,
    *,
    todo_specs: list[dict[str, str]],
    events: list[dict[str, str]] | None = None,
    leases: dict[str, dict[str, object]] | None = None,
) -> dict[str, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_relative = Path(".codex") / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state_file = project / state_relative
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        "\n".join([*STATE_HEADER_LINES, *_todo_lines(todo_specs)]) + "\n",
        encoding="utf-8",
    )

    registry_path = project / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "shared-goal-alignment-stage1",
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state_relative),
                        "quota": {"compute": 1.0, "window_hours": 24},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": list(AGENTS),
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if events:
        store = AppendOnlyStateEventStore(state_file.with_name(EVENT_LOG_NAME))
        for event in events:
            store.append(
                make_state_event(
                    event_id=event["event_id"],
                    goal_id=GOAL_ID,
                    event_type=TODO_ADDED,
                    actor_agent_id=event["actor_agent_id"],
                    refs={"todo_id": event["todo_id"]},
                    payload={"text": f"Fixture event for {event['todo_id']}."},
                )
            )

    if leases:
        for todo_id, lease in leases.items():
            lease_path = (
                runtime / "goals" / GOAL_ID / "task-leases" / f"{todo_id}.json"
            )
            lease_path.parent.mkdir(parents=True, exist_ok=True)
            lease_path.write_text(
                json.dumps(lease, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
    else:
        runtime.mkdir(parents=True, exist_ok=True)

    _assert_fixture_todos_parsed(state_file, todo_specs)
    return {
        "project": project,
        "runtime": runtime,
        "registry": registry_path,
        "state_file": state_file,
    }


def _assert_fixture_todos_parsed(
    state_file: Path,
    todo_specs: list[dict[str, str]],
) -> None:
    parsed = parse_active_state_todos(
        state_file.read_text(encoding="utf-8"),
        item_limit=None,
    )
    items = parsed.get("agent_todos", {}).get("items", [])
    parsed_ids = {item.get("todo_id") for item in items}
    for spec in todo_specs:
        assert spec.get("todo_id") in parsed_ids, (
            f"fixture todo {spec.get('todo_id')} was silently ignored by the "
            "parser; check every metadata token exists in the schema"
        )


def _default_todo_specs() -> list[dict[str, str]]:
    return [
        {
            "todo_id": "todo_lane_a",
            "text": "Continue the agent-a claimed advancement slice.",
            "status": "open",
            "task_class": "advancement_task",
            "action_kind": "run",
            "claimed_by": "agent-a",
            "priority": "P0",
        },
        {
            "todo_id": "todo_unclaimed",
            "text": "Pick up unclaimed work only after claiming it.",
            "status": "open",
            "task_class": "advancement_task",
            "action_kind": "test",
            "priority": "P1",
        },
        {
            "todo_id": "todo_blocked",
            "text": "Blocked slice stays out of the frontier.",
            "status": "blocked",
            "task_class": "advancement_task",
            "action_kind": "fix",
            "claimed_by": "agent-a",
            "priority": "P1",
        },
        {
            "todo_id": "todo_monitor",
            "text": "Monitor work never enters the advancement frontier.",
            "status": "open",
            "task_class": "continuous_monitor",
            "action_kind": "watch",
            "priority": "P2",
        },
    ]


def _default_events() -> list[dict[str, str]]:
    return [
        {
            "event_id": "evt_stage1_001",
            "actor_agent_id": "agent-b",
            "todo_id": "todo_monitor",
        },
        {
            "event_id": "evt_stage1_002",
            "actor_agent_id": "agent-a",
            "todo_id": "todo_lane_a",
        },
        {
            "event_id": "evt_stage1_003",
            "actor_agent_id": "agent-a",
            "todo_id": "todo_unclaimed",
        },
    ]


def test_projects_revision_binding_and_unclaimed_work(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert projection["schema_version"] == "shared_goal_alignment_v0"
    assert projection["goal_id"] == GOAL_ID
    assert projection["agent_id"] == "agent-a"
    assert projection["read_only"] is True
    canonical = projection["canonical_goal"]
    assert canonical["revision_basis"] == "state_event_log"
    assert canonical["goal_revision"] == 3
    assert canonical["intent_digest"].startswith("sha256:")
    assert canonical["state_updated_at"] == "2026-09-01T00:00:00+00:00"
    frontier = projection["frontier_basis"]
    assert frontier["based_on_goal_revision"] == 3
    assert frontier["basis_source"] == "state_event_log"
    assert frontier["last_agent_event_id"] == "evt_stage1_003"
    assert projection["frontier_counts"] == {
        "current_agent_claimed_advancement_count": 1,
        "unclaimed_advancement_count": 1,
        "other_agent_claimed_advancement_count": 0,
    }
    assert [item["todo_id"] for item in projection["unclaimed_eligible_work"]] == [
        "todo_unclaimed"
    ]
    assert all(
        item["claim_required_before_work"] is True
        for item in projection["unclaimed_eligible_work"]
    )
    assert projection["drift_facts"] == []
    assert projection["conflict_facts"] == []


def test_peer_events_do_not_advance_another_agents_basis(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-b",
        project=paths["project"],
    )

    # agent-a authored events 2 and 3; agent-b's basis stays at its own
    # latest attributed event (1) and never inherits the peer sequences.
    assert projection["canonical_goal"]["goal_revision"] == 3
    assert projection["frontier_basis"]["based_on_goal_revision"] == 1
    assert projection["frontier_basis"]["last_agent_event_id"] == (
        "evt_stage1_001"
    )
    assert projection["drift_facts"] == ["frontier_basis_stale"]


def test_appending_one_event_rotates_the_projection_into_stale(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )
    event_log = paths["state_file"].with_name(EVENT_LOG_NAME)

    before = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )
    assert before["canonical_goal"]["goal_revision"] == 3
    assert before["frontier_basis"]["based_on_goal_revision"] == 3
    assert before["drift_facts"] == []

    AppendOnlyStateEventStore(event_log).append(
        make_state_event(
            event_id="evt_stage1_004",
            goal_id=GOAL_ID,
            event_type=TODO_ADDED,
            actor_agent_id="agent-b",
            refs={"todo_id": "todo_lane_a"},
            payload={"text": "Fixture event that moves the canonical head."},
        )
    )

    after = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )
    assert after["canonical_goal"]["goal_revision"] == 4
    assert after["frontier_basis"]["based_on_goal_revision"] == 3
    assert after["drift_facts"] == ["frontier_basis_stale"]


def test_without_an_event_log_the_basis_is_unverifiable_not_stale(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=None,
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert projection["canonical_goal"]["revision_basis"] == (
        "markdown_active_state"
    )
    assert projection["canonical_goal"]["goal_revision"] == 0
    assert projection["frontier_basis"] == {
        "based_on_goal_revision": None,
        "basis_source": "unbound",
        "last_agent_event_id": None,
    }
    assert projection["drift_facts"] == []
    assert projection["conflict_facts"] == ["frontier_basis_unverifiable"]


def test_next_action_prose_never_changes_the_intent_digest(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    first = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )
    state_text = paths["state_file"].read_text(encoding="utf-8")
    paths["state_file"].write_text(
        state_text.replace(
            "Shared compatibility prose; it must never enter the projection digest.",
            "A completely different shared Next Action written by a peer.",
        ),
        encoding="utf-8",
    )
    second = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert first["canonical_goal"]["intent_digest"] == (
        second["canonical_goal"]["intent_digest"]
    )


def test_blocked_and_monitor_todos_stay_out_of_unclaimed_work(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    unclaimed_ids = [
        item["todo_id"] for item in projection["unclaimed_eligible_work"]
    ]
    assert unclaimed_ids == ["todo_unclaimed"]
    assert "todo_blocked" not in unclaimed_ids
    assert "todo_monitor" not in unclaimed_ids


def test_lease_owner_mismatch_projects_a_conflict_fact(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
        leases={
            "todo_lane_a": {
                "schema_version": "task_lease_v0",
                "goal_id": GOAL_ID,
                "todo_id": "todo_lane_a",
                "owner": "agent-b",
                "lease_epoch": 2,
                "version": 1,
            },
        },
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert projection["conflict_facts"] == ["lease_owner_mismatch"]
    assert projection["drift_facts"] == []


def test_matching_lease_owner_is_not_a_conflict(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
        leases={
            "todo_lane_a": {
                "schema_version": "task_lease_v0",
                "goal_id": GOAL_ID,
                "todo_id": "todo_lane_a",
                "owner": "agent-a",
                "lease_epoch": 1,
                "version": 1,
            },
        },
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert "lease_owner_mismatch" not in projection["conflict_facts"]


def test_corrupt_lease_epoch_fails_closed(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
        leases={
            "todo_lane_a": {
                "schema_version": "task_lease_v0",
                "owner": "agent-a",
                "lease_epoch": 0,
                "version": 1,
            },
        },
    )

    with pytest.raises(ValueError, match="lease epoch"):
        project_shared_goal_alignment(
            goal_id=GOAL_ID,
            agent_id="agent-a",
            project=paths["project"],
        )


def test_open_lane_replan_obligation_projects_a_conflict_fact(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
        status_item={
            "autonomous_replan_obligations_by_agent": {
                "agent-a": {
                    "schema_version": "autonomous_replan_obligation_v0",
                    "required": True,
                },
            },
        },
    )

    assert "open_lane_replan_obligation" in projection["conflict_facts"]


def test_peer_claimed_bound_todo_projects_a_conflict_fact(
    tmp_path: Path,
) -> None:
    specs = [
        *_default_todo_specs(),
        {
            "todo_id": "todo_taken_over",
            "text": "Previously bound to agent-a, now claimed by agent-b.",
            "status": "open",
            "task_class": "advancement_task",
            "action_kind": "fix",
            "claimed_by": "agent-b",
            "bound_agent": "agent-a",
            "priority": "P1",
        },
    ]
    paths = _write_fixture(
        tmp_path,
        todo_specs=specs,
        events=_default_events(),
    )

    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert "peer_claimed_lane_conflict" in projection["conflict_facts"]


def test_unregistered_agent_fails_closed(tmp_path: Path) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    with pytest.raises(ValueError, match="not registered"):
        project_shared_goal_alignment(
            goal_id=GOAL_ID,
            agent_id="agent-z",
            project=paths["project"],
        )


def test_unknown_goal_fails_closed(tmp_path: Path) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )

    with pytest.raises(ValueError, match="not registered"):
        project_shared_goal_alignment(
            goal_id="goal-unknown",
            agent_id="agent-a",
            project=paths["project"],
        )


def test_adapter_sends_typed_facts_only(monkeypatch, tmp_path: Path) -> None:
    paths = _write_fixture(
        tmp_path,
        todo_specs=_default_todo_specs(),
        events=_default_events(),
    )
    captured: dict[str, object] = {}

    def call(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return effect_runtime_result(method, params)

    monkeypatch.setattr(shared_goal_alignment, "effect_runtime_result", call)
    projection = project_shared_goal_alignment(
        goal_id=GOAL_ID,
        agent_id="agent-a",
        project=paths["project"],
    )

    assert captured["method"] == "goal.shared_goal_alignment.project"
    request = captured["params"]
    assert isinstance(request, dict)
    # Typed-facts invariant: no prose field ever enters the request.
    assert "prose" not in json.dumps(request)
    assert request["goal_id"] == GOAL_ID
    assert request["agent_id"] == "agent-a"
    assert request["canonical_goal"]["goal_revision"] == 3
    assert request["frontier_basis"]["based_on_goal_revision"] == 3
    assert request["claims"] == [
        {
            "todo_id": "todo_lane_a",
            "claimed_by": "agent-a",
            "lease_epoch": None,
            "lease_owner": None,
        }
    ]
    assert request["peer_claimed_bound_todo_ids"] == []
    assert request["open_lane_replan_obligation_required"] is False
    assert projection["schema_version"] == "shared_goal_alignment_v0"


def test_registered_method_rejects_an_illegal_request() -> None:
    # A claim attributed to another agent is a contract violation the TS
    # validator must reject at the registered runtime method.
    digest = "sha256:" + "a" * 64
    with pytest.raises(EffectRuntimeRejected) as excinfo:
        effect_runtime_result(
            "goal.shared_goal_alignment.project",
            {
                "schema_version": "shared_goal_alignment_request_v0",
                "goal_id": GOAL_ID,
                "agent_id": "agent-a",
                "canonical_goal": {
                    "goal_revision": 3,
                    "intent_digest": digest,
                    "revision_basis": "state_event_log",
                    "state_updated_at": None,
                },
                "frontier_basis": {
                    "based_on_goal_revision": 3,
                    "basis_source": "state_event_log",
                    "last_agent_event_id": "evt_stage1_003",
                },
                "frontier_counts": {
                    "current_agent_claimed_advancement_count": 1,
                    "unclaimed_advancement_count": 0,
                    "other_agent_claimed_advancement_count": 0,
                },
                "claims": [
                    {
                        "todo_id": "todo_lane_a",
                        "claimed_by": "agent-b",
                        "lease_epoch": None,
                        "lease_owner": None,
                    }
                ],
                "unclaimed_eligible": [],
                "peer_claimed_bound_todo_ids": [],
                "open_lane_replan_obligation_required": False,
            },
        )
    assert excinfo.value.error_kind == "request_rejected"
