from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from loopx.control_plane.capability_hooks import (
    POST_WRITEBACK_HOOK_INPUT_SCHEMA_VERSION,
    POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
    PostWritebackHookReceiptJournal,
    _post_writeback_dispatch_id,
    dispatch_post_writeback_hooks,
)
from loopx.capabilities.periodic_report.post_writeback_hook import (
    build_periodic_report_post_writeback_projection,
    evaluate_periodic_report_trigger_evaluation_intent,
    periodic_report_post_writeback_hook,
    periodic_report_post_writeback_hooks_for_goal,
)


def _input() -> dict[str, object]:
    return {
        "schema_version": POST_WRITEBACK_HOOK_INPUT_SCHEMA_VERSION,
        "receipt": {
            "schema_version": "loopx_rollout_event_v0",
            "event_id": "evt-stage-1",
            "event_kind": "refresh_state",
            "status": "appended",
            "recorded_at": "2026-08-30T01:00:00+08:00",
            "durable": True,
        },
        "identity": {
            "goal_id": "goal-1",
            "agent_id": "agent-1",
            "todo_id": "todo-1",
            "turn_instance_id": "turn-1",
            "effect_id": "goal-1:agent-1:todo-1:turn-1",
        },
        "state_version": "vision-revision-2",
        "projection": {
            "stage_completion": {
                "schema_version": "periodic_report_stage_completion_receipt_v0",
                "stage_identity": "stage-123",
            }
        },
    }


def _hook(*, key: str = "periodic-report:stage-123") -> PostWritebackHookRegistration:
    def producer(value: object) -> dict[str, object]:
        assert isinstance(value, dict)
        return {
            "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": "periodic_report.stage_completion",
            "capability_id": "periodic-report",
            "phase": "post_writeback",
            "status": "intent",
            "intent": {
                "schema_version": "loopx_capability_intent_v0",
                "intent_kind": "periodic_report.trigger_evaluation",
                "idempotency_key": key,
                "source_receipt_id": "evt-stage-1",
                "payload": {"stage_identity": "stage-123"},
                "requested_write_scope": [],
            },
        }

    return PostWritebackHookRegistration(
        hook_id="periodic_report.stage_completion",
        capability_id="periodic-report",
        event_kinds=("refresh_state",),
        intent_kinds=("periodic_report.trigger_evaluation",),
        requested_read_scope=("stage_completion",),
        producer=producer,
    )


def test_post_writeback_dispatch_returns_one_effect_free_intent() -> None:
    dispatch = dispatch_post_writeback_hooks([_hook()], hook_input=_input())

    assert dispatch["intent_count"] == 1
    assert dispatch["failures"] == []
    assert dispatch["primary_writeback_preserved"] is True
    assert dispatch["external_writes_performed"] is False


def test_post_writeback_dispatch_isolates_failures_and_duplicate_hooks() -> None:
    failed = PostWritebackHookRegistration(
        hook_id="periodic_report.failed",
        capability_id="periodic-report",
        event_kinds=("refresh_state",),
        intent_kinds=("periodic_report.trigger_evaluation",),
        requested_read_scope=("stage_completion",),
        producer=lambda _value: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    dispatch = dispatch_post_writeback_hooks(
        [_hook(), _hook(), failed],
        hook_input=_input(),
    )

    assert dispatch["intent_count"] == 1
    assert {item["error_code"] for item in dispatch["failures"]} == {
        "duplicate_hook_id",
        "producer_failed",
    }


def test_post_writeback_dispatch_rejects_non_durable_input_before_provider() -> None:
    called = False

    def producer(_value: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    hook = PostWritebackHookRegistration(
        hook_id="periodic_report.stage_completion",
        capability_id="periodic-report",
        event_kinds=("refresh_state",),
        intent_kinds=("periodic_report.trigger_evaluation",),
        requested_read_scope=("stage_completion",),
        producer=producer,
    )
    pending = _input()
    pending["receipt"] = {**pending["receipt"], "durable": False}  # type: ignore[arg-type]

    dispatch = dispatch_post_writeback_hooks([hook], hook_input=pending)

    assert called is False
    assert dispatch["intent_count"] == 0
    assert dispatch["failures"][0]["error_code"] == "registration_or_input_rejected"


def test_periodic_report_hook_emits_only_an_approval_neutral_trigger_intent() -> None:
    hook_input = _input()
    hook_input["projection"] = {
        **hook_input["projection"],  # type: ignore[dict-item]
        "project_progress": {
            "schema_version": "periodic_report_project_progress_projection_v0",
            "goal_id": "goal-1",
            "observed_at": "2026-08-30T09:00:00Z",
            "language": "zh-CN",
            "items": [
                {
                    "item_id": "completed_1",
                    "title": "Frozen stage outcome",
                    "summary": "The stage snapshot is captured at writeback.",
                    "content_kind": "outcome",
                    "value_rank": 10,
                    "source_ref": "todo:todo-1",
                }
            ],
        },
    }
    dispatch = dispatch_post_writeback_hooks(
        [periodic_report_post_writeback_hook()],
        hook_input=hook_input,
    )

    intent = dispatch["intents"][0]
    assert intent["intent_kind"] == "periodic_report.trigger_evaluation"
    assert intent["requested_write_scope"] == []
    assert intent["payload"]["generation_authorized"] is False
    assert intent["payload"]["external_delivery_authorized"] is False
    assert intent["payload"]["project_progress"]["items"][0]["title"] == (
        "Frozen stage outcome"
    )


def test_periodic_report_hook_accepts_durable_todo_completion() -> None:
    hook_input = _input()
    hook_input["receipt"] = {
        **hook_input["receipt"],  # type: ignore[dict-item]
        "event_kind": "todo_complete",
        "status": "committed",
    }

    dispatch = dispatch_post_writeback_hooks(
        [periodic_report_post_writeback_hook()],
        hook_input=hook_input,
    )

    assert dispatch["intent_count"] == 1
    assert dispatch["failures"] == []


def test_post_writeback_sidecar_replay_skips_provider(tmp_path) -> None:
    calls = 0
    base = _hook()

    def producer(value: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return dict(base.producer(value))  # type: ignore[arg-type]

    hook = PostWritebackHookRegistration(
        hook_id=base.hook_id,
        capability_id=base.capability_id,
        event_kinds=base.event_kinds,
        intent_kinds=base.intent_kinds,
        requested_read_scope=base.requested_read_scope,
        producer=producer,
    )
    journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")

    first = dispatch_post_writeback_hooks([hook], hook_input=_input(), journal=journal)
    replay = dispatch_post_writeback_hooks([hook], hook_input=_input(), journal=journal)

    assert calls == 1
    assert first["intent_count"] == replay["intent_count"] == 1
    assert replay["invoked_count"] == 0
    assert replay["replayed_hooks"] == ["periodic_report.stage_completion"]
    assert replay["intents"] == first["intents"]


def test_post_writeback_retryable_failure_recovers_after_restart(tmp_path) -> None:
    calls = 0
    base = _hook()

    def producer(value: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return dict(base.producer(value))  # type: ignore[arg-type]

    hook = PostWritebackHookRegistration(
        hook_id=base.hook_id,
        capability_id=base.capability_id,
        event_kinds=base.event_kinds,
        intent_kinds=base.intent_kinds,
        requested_read_scope=base.requested_read_scope,
        producer=producer,
    )
    first = dispatch_post_writeback_hooks(
        [hook],
        hook_input=_input(),
        journal=PostWritebackHookReceiptJournal(tmp_path, "goal-1"),
    )

    assert first["intent_count"] == 0
    assert first["failures"][0]["error_code"] == "producer_failed"
    assert first["failures"][0]["durable_receipt_ref"].startswith(
        "post-writeback-hook:pwh_"
    )
    receipt_path = next(
        (tmp_path / "goals" / "goal-1" / "post_writeback_hooks").glob("*.json")
    )
    failed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert failed_receipt["status"] == "retryable_failure"
    assert failed_receipt["attempt_count"] == 1

    restarted_journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")
    recovered = dispatch_post_writeback_hooks(
        [hook], hook_input=_input(), journal=restarted_journal
    )
    replay = dispatch_post_writeback_hooks(
        [hook], hook_input=_input(), journal=restarted_journal
    )

    assert calls == 2
    assert recovered["intent_count"] == replay["intent_count"] == 1
    assert recovered["retried_hooks"] == ["periodic_report.stage_completion"]
    assert replay["replayed_hooks"] == ["periodic_report.stage_completion"]
    recovered_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert recovered_receipt["status"] == "intent_recorded"
    assert recovered_receipt["attempt_count"] == 2


def test_post_writeback_policy_version_rotates_replay_identity(tmp_path) -> None:
    calls = 0
    base = _hook()

    def producer(value: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return dict(base.producer(value))  # type: ignore[arg-type]

    journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")
    for policy_version in ("v0", "v1"):
        hook = PostWritebackHookRegistration(
            hook_id=base.hook_id,
            capability_id=base.capability_id,
            event_kinds=base.event_kinds,
            intent_kinds=base.intent_kinds,
            requested_read_scope=base.requested_read_scope,
            producer=producer,
            policy_version=policy_version,
        )
        dispatch = dispatch_post_writeback_hooks(
            [hook], hook_input=_input(), journal=journal
        )
        assert dispatch["invoked_count"] == 1

    assert calls == 2
    assert (
        len(
            list(
                (tmp_path / "goals" / "goal-1" / "post_writeback_hooks").glob("*.json")
            )
        )
        == 2
    )


def test_periodic_report_hook_requires_explicit_goal_profile_opt_in(tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-1",
                        "control_plane": {
                            "periodic_report": {
                                "enabled": False,
                                "profile_preset": "weekly",
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        periodic_report_post_writeback_hooks_for_goal(
            registry_path=registry_path, goal_id="goal-1"
        )
        == ()
    )

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["goals"][0]["control_plane"]["periodic_report"]["enabled"] = True
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    hooks = periodic_report_post_writeback_hooks_for_goal(
        registry_path=registry_path, goal_id="goal-1"
    )
    assert len(hooks) == 1
    assert hooks[0].hook_id == "periodic_report.runtime_trigger"

    hook_input = _input()
    hook_input["projection"] = {
        "stage_completion": {
            "schema_version": "periodic_report_stage_completion_receipt_v0",
            "stage_identity": "stage-123",
            "agent_id": "agent-1",
            "closed_vision_revision": "2026-08-30T10:00:00Z",
            "frontier_identity": "frontier-2",
            "transition": "successor_frontier_settled",
            "completed_at": "2026-08-30T11:00:00Z",
            "acceptance": "validated",
            "outcome_checkpoint_satisfied": True,
            "durable_writeback_required": True,
            "evidence_refs": ["frontier-2"],
        }
    }
    dispatch = dispatch_post_writeback_hooks(hooks, hook_input=hook_input)
    decision = evaluate_periodic_report_trigger_evaluation_intent(
        dispatch["intents"][0]
    )

    assert decision["eligible"] is True
    assert decision["selected_trigger_kind"] == "bounded_segment_milestone"
    assert decision["boundary"]["external_writes_performed"] is False


def test_periodic_report_projection_reduces_durable_successor_transition(
    tmp_path,
) -> None:
    runtime_root = tmp_path / "runtime"
    state_path = tmp_path / "goal.md"
    state_path.write_text(
        """# Goal

## User Todo

## Agent Todo

- [ ] Analyze the next bounded family.
  <!-- loopx:todo todo_id=todo-next status=open task_class=advancement_task claimed_by=agent-1 -->
""",
        encoding="utf-8",
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-1",
                        "repo": str(tmp_path),
                        "state_file": "goal.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runs_dir = runtime_root / "goals" / "goal-1" / "runs"
    runs_dir.mkdir(parents=True)
    runs = [
        {
            "generated_at": "2026-08-30T11:00:00Z",
            "goal_id": "goal-1",
            "agent_vision": {
                "schema_version": "goal_vision_replan_contract_v0",
                "agent_id": "agent-1",
                "state": "active",
                "vision_patch": {"acceptance_summary": "Next family is bounded."},
            },
            "autonomous_replan_ack": {
                "recorded": True,
                "frontier_identity": "frontier-2",
                "semantic_delta": {
                    "accepted": True,
                    "outcomes": ["fresh_vision_path_outcome"],
                    "trigger_kinds": ["vision_successor_required"],
                    "obligation_id": "replan-2",
                },
            },
        },
        {
            "generated_at": "2026-08-30T10:00:00Z",
            "goal_id": "goal-1",
            "agent_vision": {
                "schema_version": "goal_vision_replan_contract_v0",
                "agent_id": "agent-1",
                "state": "vision_closed",
                "vision_patch": {"acceptance_summary": "First family accepted."},
            },
            "vision_checkpoint": {
                "schema_version": "vision_checkpoint_v0",
                "satisfied": True,
                "decision": "patched",
                "triggers": [
                    {
                        "kind": "material_delivery_outcome",
                        "delivery_outcome": "outcome_progress",
                    }
                ],
            },
        },
    ]
    (runs_dir / "index.jsonl").write_text(
        "".join(json.dumps(run) + "\n" for run in runs),
        encoding="utf-8",
    )

    projection = build_periodic_report_post_writeback_projection(
        payload={"state": {"path": str(state_path)}},
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-1",
        agent_id="agent-1",
    )

    receipt = projection["stage_completion"]
    assert receipt["transition"] == "successor_frontier_settled"
    assert receipt["frontier_identity"] == "frontier-2"
    assert projection["project_progress"]["observed_at"] == receipt["completed_at"]


def test_periodic_report_projection_reduces_terminal_after_todo_completion(
    tmp_path,
) -> None:
    runtime_root = tmp_path / "runtime"
    state_path = tmp_path / "goal.md"
    state_path.write_text(
        """# Goal

## User Todo

## Agent Todo

- [x] Complete the bounded analysis.
  <!-- loopx:todo todo_id=todo_analysis status=done task_class=advancement_task claimed_by=agent-1 no_followup=true updated_at=2026-08-30T10:30:00Z -->
- [ ] Watch for later external changes.
  <!-- loopx:todo todo_id=todo_watch status=open task_class=continuous_monitor claimed_by=agent-1 watch_only=true next_due_at=2026-09-06T10:30:00Z -->
""",
        encoding="utf-8",
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-1",
                        "repo": str(tmp_path),
                        "state_file": "goal.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runs_dir = runtime_root / "goals" / "goal-1" / "runs"
    runs_dir.mkdir(parents=True)
    closed_run = {
        "generated_at": "2026-08-30T10:00:00Z",
        "goal_id": "goal-1",
        "agent_id": "agent-1",
        "agent_vision": {
            "schema_version": "goal_vision_replan_contract_v0",
            "agent_id": "agent-1",
            "state": "vision_closed",
            "vision_patch": {"acceptance_summary": "Analysis accepted."},
        },
        "vision_checkpoint": {
            "schema_version": "vision_checkpoint_v0",
            "satisfied": True,
            "decision": "patched",
            "triggers": [
                {
                    "kind": "material_delivery_outcome",
                    "delivery_outcome": "primary_goal_outcome",
                }
            ],
        },
    }
    (runs_dir / "index.jsonl").write_text(
        json.dumps(closed_run) + "\n",
        encoding="utf-8",
    )

    projection = build_periodic_report_post_writeback_projection(
        payload={"state_file": str(state_path)},
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-1",
        agent_id="agent-1",
    )

    receipt = projection["stage_completion"]
    assert receipt["transition"] == "goal_terminal"
    assert receipt["frontier_identity"] == "validated-goal-terminal"


def test_post_writeback_concurrent_exact_dispatch_single_flight(tmp_path) -> None:
    calls = 0
    lock = threading.Lock()
    base = _hook()

    def producer(value: object) -> dict[str, object]:
        nonlocal calls
        time.sleep(0.05)
        with lock:
            calls += 1
        return dict(base.producer(value))  # type: ignore[arg-type]

    hook = PostWritebackHookRegistration(
        hook_id=base.hook_id,
        capability_id=base.capability_id,
        event_kinds=base.event_kinds,
        intent_kinds=base.intent_kinds,
        requested_read_scope=base.requested_read_scope,
        producer=producer,
    )
    journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")
    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []

    def worker() -> None:
        barrier.wait()
        res = dispatch_post_writeback_hooks([hook], hook_input=_input(), journal=journal)
        results.append(res)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert calls == 1
    assert len(results) == 2
    invoked_counts = [res["invoked_count"] for res in results]
    assert sorted(invoked_counts) == [0, 1]
    replayed_results = [res for res in results if res["invoked_count"] == 0]
    assert replayed_results[0]["replayed_hooks"] == ["periodic_report.stage_completion"]
    assert results[0]["intents"] == results[1]["intents"]


def test_periodic_report_projection_isolates_other_agent_ack_and_claimed_todos(
    tmp_path,
) -> None:
    runtime_root = tmp_path / "runtime"
    state_path = tmp_path / "goal.md"
    state_path.write_text(
        """# Goal

## User Todo

## Agent Todo

- [ ] Analyze the next bounded family for Agent B.
  <!-- loopx:todo todo_id=todo-b status=open task_class=advancement_task claimed_by=agent-b -->
""",
        encoding="utf-8",
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-1",
                        "repo": str(tmp_path),
                        "state_file": "goal.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runs_dir = runtime_root / "goals" / "goal-1" / "runs"
    runs_dir.mkdir(parents=True)
    runs = [
        {
            "generated_at": "2026-08-30T11:00:00Z",
            "goal_id": "goal-1",
            "agent_vision": {
                "schema_version": "goal_vision_replan_contract_v0",
                "agent_id": "agent-a",
                "state": "active",
                "vision_patch": {"acceptance_summary": "Agent A next vision."},
            },
            "autonomous_replan_ack": {
                "recorded": True,
                "agent_id": "agent-b",
                "frontier_identity": "frontier-b",
                "semantic_delta": {
                    "accepted": True,
                    "outcomes": ["fresh_vision_path_outcome"],
                    "trigger_kinds": ["vision_successor_required"],
                    "obligation_id": "replan-b",
                },
            },
        },
        {
            "generated_at": "2026-08-30T10:00:00Z",
            "goal_id": "goal-1",
            "agent_vision": {
                "schema_version": "goal_vision_replan_contract_v0",
                "agent_id": "agent-a",
                "state": "vision_closed",
                "vision_patch": {"acceptance_summary": "Agent A first vision."},
            },
            "vision_checkpoint": {
                "schema_version": "vision_checkpoint_v0",
                "satisfied": True,
                "decision": "patched",
                "triggers": [
                    {
                        "kind": "material_delivery_outcome",
                        "delivery_outcome": "outcome_progress",
                    }
                ],
            },
        },
    ]
    (runs_dir / "index.jsonl").write_text(
        "".join(json.dumps(run) + "\n" for run in runs),
        encoding="utf-8",
    )

    # Agent B's ACK and Agent B's claimed Todo must NOT settle Agent A's stage.
    projection_a = build_periodic_report_post_writeback_projection(
        payload={"state": {"path": str(state_path)}},
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-1",
        agent_id="agent-a",
    )
    assert "stage_completion" not in projection_a

    # Now make the Todo unclaimed and provide Agent A's own ACK in run history
    runs.insert(
        0,
        {
            "generated_at": "2026-08-30T11:30:00Z",
            "goal_id": "goal-1",
            "agent_vision": {
                "schema_version": "goal_vision_replan_contract_v0",
                "agent_id": "agent-a",
                "state": "active",
                "vision_patch": {"acceptance_summary": "Agent A next vision."},
            },
            "autonomous_replan_ack": {
                "recorded": True,
                "agent_id": "agent-a",
                "frontier_identity": "frontier-a",
                "semantic_delta": {
                    "accepted": True,
                    "outcomes": ["fresh_vision_path_outcome"],
                    "trigger_kinds": ["vision_successor_required"],
                    "obligation_id": "replan-a",
                },
            },
        },
    )
    (runs_dir / "index.jsonl").write_text(
        "".join(json.dumps(run) + "\n" for run in runs),
        encoding="utf-8",
    )
    state_path.write_text(
        """# Goal

## User Todo

## Agent Todo

- [ ] Analyze the next bounded family.
  <!-- loopx:todo todo_id=todo-unclaimed status=open task_class=advancement_task -->
""",
        encoding="utf-8",
    )

    projection_a_unclaimed = build_periodic_report_post_writeback_projection(
        payload={"state": {"path": str(state_path)}},
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-1",
        agent_id="agent-a",
    )
    receipt = projection_a_unclaimed["stage_completion"]
    assert receipt["transition"] == "successor_frontier_settled"
    assert receipt["agent_id"] == "agent-a"
    assert receipt["frontier_identity"] == "frontier-a"


def test_post_writeback_concurrent_exact_dispatch_lease_timeout_isolated(
    tmp_path: Path,
) -> None:
    calls = 0
    lock = threading.Lock()
    started = threading.Event()
    base = _hook()

    def producer(value: object) -> dict[str, object]:
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        time.sleep(0.3)
        return dict(base.producer(value))  # type: ignore[arg-type]

    hook = PostWritebackHookRegistration(
        hook_id=base.hook_id,
        capability_id=base.capability_id,
        event_kinds=base.event_kinds,
        intent_kinds=base.intent_kinds,
        requested_read_scope=base.requested_read_scope,
        producer=producer,
    )
    journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")
    results: dict[str, dict[str, object]] = {}

    def worker_slow() -> None:
        results["slow"] = dispatch_post_writeback_hooks(
            [hook], hook_input=_input(), journal=journal
        )

    t_slow = threading.Thread(target=worker_slow)
    t_slow.start()

    assert started.wait(timeout=5.0)

    # Second caller attempts exact dispatch with small lease timeout while producer is holding lease
    result_timeout = dispatch_post_writeback_hooks(
        [hook],
        hook_input=_input(),
        journal=journal,
        lease_timeout_seconds=0.05,
    )

    t_slow.join(timeout=5.0)
    result_slow = results["slow"]

    # Contention timeout is isolated: does not raise, preserves primary writeback, returns typed failure
    assert result_timeout["primary_writeback_preserved"] is True
    assert result_timeout["intent_count"] == 0
    assert result_timeout["invoked_count"] == 0
    assert len(result_timeout["failures"]) == 1
    assert result_timeout["failures"][0]["error_code"] == "lock_acquire_timeout"
    assert result_timeout["failures"][0]["hook_id"] == "periodic_report.stage_completion"

    # Slow worker completes successfully and records intent
    assert result_slow["primary_writeback_preserved"] is True
    assert result_slow["intent_count"] == 1
    assert result_slow["invoked_count"] == 1
    assert result_slow["failures"] == []

    # Total producer invocations is exactly 1
    assert calls == 1

    # Subsequent dispatch replays cleanly from terminal receipt without invoking producer
    replay = dispatch_post_writeback_hooks(
        [hook], hook_input=_input(), journal=journal
    )
    assert replay["intent_count"] == 1
    assert replay["invoked_count"] == 0
    assert replay["replayed_hooks"] == ["periodic_report.stage_completion"]
    assert replay["intents"] == result_slow["intents"]
    assert calls == 1


def test_post_writeback_lease_timeout_isolated_across_processes(
    tmp_path: Path,
) -> None:
    journal = PostWritebackHookReceiptJournal(tmp_path, "goal-1")
    hook = _hook()
    input_data = _input()
    dispatch_id = _post_writeback_dispatch_id(hook, input_data)

    script = """
import sys
import time
from pathlib import Path
from loopx.control_plane.capability_hooks import PostWritebackHookReceiptJournal

journal = PostWritebackHookReceiptJournal(Path(sys.argv[1]), sys.argv[2])
with journal.execution_lease(sys.argv[3]):
    print("READY", flush=True)
    time.sleep(10)
"""
    env = dict(os.environ)
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(Path.cwd())

    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), "goal-1", dispatch_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"

        result = dispatch_post_writeback_hooks(
            [hook],
            hook_input=input_data,
            journal=journal,
            lease_timeout_seconds=0.05,
        )

        assert result["primary_writeback_preserved"] is True
        assert result["intent_count"] == 0
        assert result["invoked_count"] == 0
        assert len(result["failures"]) == 1
        assert result["failures"][0]["error_code"] == "lock_acquire_timeout"
        assert result["failures"][0]["hook_id"] == "periodic_report.stage_completion"
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
