from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.periodic_report.pending_intent import (
    consume_pending_periodic_report_intent,
    pending_periodic_report_intents,
    periodic_report_pending_intent_interaction_hook,
)
from loopx.capabilities.periodic_report.project_progress_snapshot import (
    build_project_progress_snapshot,
)
from loopx.todos import add_goal_todo, complete_goal_todo
from loopx.status import collect_status, parse_active_state_todos
from loopx.quota import build_quota_should_run
from loopx.control_plane.capability_hooks import dispatch_interaction_projection_hooks
from loopx.control_plane.quota.live_decision import (
    _apply_pending_capability_intent_precedence,
)


GOAL_ID = "report-goal"
AGENT_ID = "report-agent"


def _intent() -> dict[str, object]:
    return {
        "schema_version": "loopx_capability_intent_v0",
        "intent_kind": "periodic_report.trigger_evaluation",
        "idempotency_key": "periodic-report:stage-example",
        "source_receipt_id": "pwr_example",
        "payload": {
            "schema_version": "periodic_report_trigger_evaluation_intent_v0",
            "stage_completion": {
                "schema_version": "periodic_report_stage_completion_receipt_v0",
                "stage_identity": "stage-example",
                "agent_id": AGENT_ID,
                "closed_vision_revision": "2026-08-30T09:00:00Z",
                "frontier_identity": "validated-goal-terminal",
                "transition": "goal_terminal",
                "completed_at": "2026-08-30T09:00:00Z",
                "acceptance": "validated",
                "outcome_checkpoint_satisfied": True,
                "durable_writeback_required": True,
                "evidence_refs": ["goal_terminal_state_v0"],
            },
            "profile_ref": {
                "profile_id": "weekly_progress",
                "profile_version": "v1",
                "profile_digest": "sha256:" + "1" * 64,
            },
            "trigger_policy": {
                "enabled_kinds": ["bounded_segment_milestone"],
                "minimum_interval_seconds": 0,
            },
            "generation_authorized": False,
            "external_delivery_authorized": False,
        },
        "requested_write_scope": [],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state = project / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    state.write_text(
        """---
status: active
---

# Active Goal State

## User Todo

## Agent Todo

- [x] Finish the bounded analysis.
  <!-- loopx:todo todo_id=todo_finished status=done task_class=advancement_task claimed_by=report-agent evidence=validated-analysis-outcome updated_at=2026-08-30T09:00:00Z -->
""",
        encoding="utf-8",
    )
    registry = project / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(project),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sidecar_dir = runtime / "goals" / GOAL_ID / "post_writeback_hooks"
    sidecar_dir.mkdir(parents=True)
    sidecar = sidecar_dir / ("pwh_" + "a" * 64 + ".json")
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": "loopx_post_writeback_capability_hook_receipt_v0",
                "dispatch_id": sidecar.stem,
                "hook_id": "periodic_report.runtime_trigger",
                "capability_id": "periodic-report",
                "source_receipt_id": "pwr_example",
                "status": "intent_recorded",
                "intent": _intent(),
                "error_code": None,
                "attempt_count": 1,
                "recorded_at": "2026-08-30T09:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    return registry, runtime


def _write_editorial_response(first: dict[str, object]) -> None:
    request_path = Path(str(first["editorial_request_path"]))
    response_path = Path(str(first["editorial_response_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source_ref = request["facts"][0]["source_ref"]
    response = {
        "schema_version": "periodic_report_editorial_response_v0",
        "request_digest": request["request_digest"],
        "language": "zh-CN",
        "title": "项目阶段分析周报",
        "kicker": "阶段分析周报",
        "period_label": request["actual_work_window"]["period_label"],
        "highlights": [
            {
                "highlight_id": "coverage",
                "value": "全景",
                "label": "问题覆盖",
                "tone": "positive",
            },
            {
                "highlight_id": "depth",
                "value": "因果",
                "label": "重点下钻",
                "tone": "neutral",
            },
        ],
        "sections": [
            {
                "section_id": "overview",
                "title": "全景判断",
                "items": [
                    {
                        "title": "阶段分析已经形成完整判断",
                        "summary": "当前证据已经覆盖全景分类、重点因果与后续处置。",
                        "source_ref": source_ref,
                    }
                ],
            },
            {
                "section_id": "problem_map",
                "title": "问题版图",
                "items": [
                    {
                        "title": "问题已按影响与证据分层",
                        "summary": "主问题、次要问题与待确认边界已经拆开呈现。",
                        "source_ref": source_ref,
                    }
                ],
            },
            {
                "section_id": "causal_analysis",
                "title": "重点因果下钻",
                "items": [
                    {
                        "title": "最高价值问题已下钻到最窄责任层",
                        "summary": "结论由完成回执支撑，并保留尚未证明的边界。",
                        "source_ref": source_ref,
                        "details": [
                            {"label": "证据", "text": "完成事实已持久化。"},
                            {"label": "边界", "text": "不外推到未验证范围。"},
                        ],
                    },
                    {
                        "title": "跨项共因已经与单点问题分离",
                        "summary": "处置优先级不再由 Todo 时间顺序决定。",
                        "source_ref": source_ref,
                        "details": [
                            {"label": "共因", "text": "证据链可跨条目复核。"},
                            {"label": "单点", "text": "局部现象单独保留。"},
                        ],
                    },
                ],
            },
            {
                "section_id": "coverage_and_actions",
                "title": "版本覆盖与处置",
                "items": [
                    {
                        "title": "历史证据与当前覆盖已经分开",
                        "summary": "当前版本只声明已有证据能证明的覆盖范围。",
                        "source_ref": source_ref,
                    }
                ],
            },
            {
                "section_id": "next_actions",
                "title": "下一步",
                "items": [
                    {
                        "title": "按影响与可证伪性推进下一阶段",
                        "summary": "优先验证能覆盖多个问题族的修复。",
                        "source_ref": source_ref,
                    }
                ],
            },
        ],
    }
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")


def _reject_approval(
    *, state_path: Path, approval_todo_id: str, updated_at: str
) -> None:
    updated_lines: list[str] = []
    for line in state_path.read_text(encoding="utf-8").splitlines():
        if approval_todo_id in line and "loopx:todo" in line:
            line = line.replace("status=open", "status=done")
            line = line.replace(
                " -->",
                f" decision_outcome=reject completed_at={updated_at} "
                f"updated_at={updated_at} -->",
            )
        updated_lines.append(line)
    state_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _append_cancelled_approval(
    *, state_path: Path, approval_scope: str, updated_at: str
) -> None:
    state = state_path.read_text(encoding="utf-8")
    cancellation = (
        "\n- [x] Cancel the superseded report payload.\n"
        "  <!-- loopx:todo todo_id=todo_cancelled status=done "
        "task_class=user_gate action_kind=cancel_periodic_report_payload "
        f"decision_scope={approval_scope} decision_outcome=cancel "
        f"bound_agent={AGENT_ID} blocks_agent={AGENT_ID} "
        f"completed_at={updated_at} updated_at={updated_at} -->\n"
    )
    state = state.replace("\n## Agent Todo\n", cancellation + "\n## Agent Todo\n")
    state_path.write_text(state, encoding="utf-8")


def test_pending_intent_projects_a_ts_validated_governed_action(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)

    dispatch = dispatch_interaction_projection_hooks(
        [
            periodic_report_pending_intent_interaction_hook(
                registry_path=registry,
                runtime_root=runtime,
                goal_id=GOAL_ID,
                agent_id=AGENT_ID,
            )
        ]
    )

    projection = dispatch["projections"]["pending_capability_intent"]
    assert projection["state"] == "pending"
    assert projection["generation_authorized"] is True
    assert projection["external_delivery_authorized"] is False
    assert projection["agent_read_required"] is True
    assert "consume-pending" in projection["command"]

    quiet = {
        "decision": "skip",
        "should_run": False,
        "state": "terminal_no_followup",
        "effective_action": "terminal_no_followup",
        "interaction_contract": {
            "mode": "terminal_no_followup",
            "agent_channel": {"must_attempt": False, "quiet_noop_allowed": True},
        },
    }
    _apply_pending_capability_intent_precedence(quiet, projection)
    assert quiet["effective_action"] == "governed_capability_intent"
    assert quiet["should_run"] is True
    assert quiet["interaction_contract"]["agent_channel"]["must_attempt"] is True
    assert quiet["interaction_contract"]["agent_channel"]["quiet_noop_allowed"] is False
    assert quiet["interaction_contract"]["cli_channel"]["next_cli_actions"] == [
        projection["command"]
    ]

    gated = {
        "decision": "skip",
        "should_run": False,
        "state": "operator_gate",
        "requires_user_action": True,
        "action_required": True,
        "open_count": 1,
        "interaction_contract": {
            "mode": "user_gate",
            "user_channel": {"action_required": True, "notify": "NOTIFY"},
            "agent_channel": {"must_attempt": False, "quiet_noop_allowed": True},
        },
    }
    _apply_pending_capability_intent_precedence(gated, projection)
    assert gated["requires_user_action"] is True
    assert gated["open_count"] == 1
    assert gated["interaction_contract"]["user_channel"] == {
        "action_required": True,
        "notify": "NOTIFY",
    }
    assert gated["interaction_contract"]["agent_channel"]["must_attempt"] is True


def test_consumption_is_local_and_exact_replay_does_not_duplicate_gate(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)

    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    assert required["status"] == "editorial_required"
    assert Path(required["editorial_request_path"]).is_file()
    assert not Path(required["editorial_response_path"]).exists()
    state_before = (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(
        encoding="utf-8"
    )
    assert "approve_periodic_report_payload" not in state_before
    _write_editorial_response(required)
    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    replay = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert first["status"] == "approval_pending"
    assert first["external_writes_performed"] is False
    assert first["content_checks"] == {
        "schema_version": "periodic_report_content_checks_v0",
        "document_normalized": True,
        "artifact_digests_verified": True,
        "html_self_contained": True,
        "matching_document_digest": True,
        "language_is_zh_cn": True,
        "analysis_narrative_validated": True,
        "evidence_lineage_validated": True,
        "external_writes_performed": False,
    }
    assert Path(first["artifacts"]["html_path"]).is_file()
    assert Path(first["artifacts"]["markdown_path"]).is_file()
    assert Path(first["artifacts"]["generation_bundle_path"]).is_file()
    html = Path(first["artifacts"]["html_path"]).read_text(encoding="utf-8")
    assert "本期结论：阶段分析已经形成完整判断" in html
    assert "当前风险：问题已按影响与证据分层" in html
    assert "下一步：按影响与可证伪性推进下一阶段" in html
    assert replay["status"] == "no_pending_intent"
    assert (
        pending_periodic_report_intents(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        == []
    )
    state = (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
    assert state.count("approve_periodic_report_payload") == 1
    assert "批准前不得发布妙搭或发送群消息" in state
    parsed = parse_active_state_todos(state)
    delivery = next(
        item
        for item in parsed["agent_todos"]["items"]
        if item.get("todo_id") == first["delivery_todo_id"]
    )
    gate = next(
        item
        for item in parsed["user_todos"]["items"]
        if item.get("todo_id") == first["approval_todo_id"]
    )
    assert delivery["status"] == "blocked"
    assert delivery["action_kind"] == "deliver_periodic_report_goal_channel"
    assert delivery["required_decision_scopes"][0]["scope_key"].startswith(
        "periodic_report_"
    )
    assert gate["unblocks_todo_id"] == delivery["todo_id"]

    completion = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(first["approval_todo_id"]),
        role="user",
        agent_id=AGENT_ID,
        decision_outcome="approve",
        evidence="owner approved the exact frozen report payload",
    )
    assert completion["unblock_resume"]["state"] == "resumed"
    approved = parse_active_state_todos(
        (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
    )
    delivery_after = next(
        item
        for item in approved["agent_todos"]["items"]
        if item.get("todo_id") == first["delivery_todo_id"]
    )
    assert delivery_after["status"] == "open"
    assert delivery_after.get("required_decision_scopes", []) == []
    status = collect_status(
        registry_path=registry,
        runtime_root_override=str(runtime),
        scan_roots=[registry.parent],
        limit=20,
        goal_id=GOAL_ID,
    )
    quota = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        available_capabilities=["network", "lark_bot_message_write"],
    )
    assert quota["selected_todo"]["todo_id"] == delivery_after["todo_id"], quota
    assert quota["user_todo_summary"]["open_count"] == 0


def test_consumption_uses_the_stage_progress_snapshot(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)
    sidecar = next(
        (runtime / "goals" / GOAL_ID / "post_writeback_hooks").glob("*.json")
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["intent"]["payload"]["project_progress"] = build_project_progress_snapshot(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        completed_at="2026-08-30T09:00:00Z",
    )
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Follow-up work added after stage completion",
        claimed_by=AGENT_ID,
        agent_id=AGENT_ID,
    )

    result = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    assert result["status"] == "editorial_required"
    request = json.loads(
        Path(result["editorial_request_path"]).read_text(encoding="utf-8")
    )
    facts = request["facts"]

    assert any("Finish the bounded analysis" in fact["title"] for fact in facts)
    completed_fact = next(
        fact for fact in facts if "Finish the bounded analysis" in fact["title"]
    )
    assert completed_fact["completed_at"] == "2026-08-30T09:00:00Z"
    assert request["actual_work_window"]["period_label"] == (
        "2026-08-30 17:00（北京时间）"
    )
    assert not any(
        "Follow-up work added after stage completion" in fact["title"] for fact in facts
    )


def test_consumption_rejects_snapshot_outcome_after_stage_completion(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    sidecar = next(
        (runtime / "goals" / GOAL_ID / "post_writeback_hooks").glob("*.json")
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["intent"]["payload"]["project_progress"] = {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": GOAL_ID,
        "observed_at": "2026-08-30T09:00:00Z",
        "language": "zh-CN",
        "items": [
            {
                "item_id": "completed_1",
                "title": "Future outcome",
                "summary": "This timestamp is outside the frozen stage.",
                "content_kind": "outcome",
                "value_rank": 10,
                "source_ref": "todo:future",
                "completed_at": "2026-08-30T09:00:01Z",
            }
        ],
    }
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot timestamp is invalid"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )


def test_consumption_recovers_when_gate_precedes_receipt_write(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)

    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    _write_editorial_response(required)
    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    receipt_path = Path(first["artifacts"]["html_path"]).parent / "receipt.json"
    receipt_path.unlink()

    recovered = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert recovered["status"] == "approval_pending"
    assert recovered["generation_receipt"] == first["generation_receipt"]
    state = (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
    assert state.count("approve_periodic_report_payload") == 1


def test_rejected_approval_reopens_the_intent_in_a_fresh_attempt(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    _write_editorial_response(required)
    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    state_path = registry.parent / "ACTIVE_GOAL_STATE.md"
    _reject_approval(
        state_path=state_path,
        approval_todo_id=str(first["approval_todo_id"]),
        updated_at="2026-08-30T10:00:00Z",
    )

    reopened = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert reopened["status"] == "editorial_required"
    assert reopened["editorial_request_path"] != required["editorial_request_path"]
    assert "retry-" in reopened["editorial_request_path"]
    assert not Path(reopened["editorial_response_path"]).exists()
    _write_editorial_response(reopened)
    second = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    assert second["status"] == "approval_pending"
    assert second["approval_todo_id"] != first["approval_todo_id"]
    assert (
        state_path.read_text(encoding="utf-8").count("approve_periodic_report_payload")
        == 2
    )
    assert (
        pending_periodic_report_intents(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        == []
    )

    _reject_approval(
        state_path=state_path,
        approval_todo_id=str(second["approval_todo_id"]),
        updated_at="2026-08-30T11:00:00Z",
    )
    reopened_again = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    assert reopened_again["status"] == "editorial_required"
    assert reopened_again["editorial_request_path"] not in {
        required["editorial_request_path"],
        reopened["editorial_request_path"],
    }
    assert "retry-" in reopened_again["editorial_request_path"]


def test_later_cancel_reopens_an_already_approved_generation(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    _write_editorial_response(required)
    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    state_path = registry.parent / "ACTIVE_GOAL_STATE.md"
    state = state_path.read_text(encoding="utf-8").replace(
        "status=open task_class=user_gate action_kind=approve_periodic_report_payload",
        "status=done task_class=user_gate action_kind=approve_periodic_report_payload "
        "decision_outcome=approve completed_at=2026-08-30T10:00:00Z",
    )
    state_path.write_text(state, encoding="utf-8")
    _append_cancelled_approval(
        state_path=state_path,
        approval_scope=str(first["approval_scope"]),
        updated_at="2026-08-30T10:05:00Z",
    )

    reopened = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert reopened["status"] == "editorial_required"
    assert reopened["editorial_request_path"] != required["editorial_request_path"]
    assert "retry-" in reopened["editorial_request_path"]


def test_consumption_rejects_english_or_flat_editorial_response(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    _write_editorial_response(required)
    response_path = Path(required["editorial_response_path"])
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["title"] = "Weekly project report"
    response_path.write_text(json.dumps(response), encoding="utf-8")

    with pytest.raises(ValueError, match="title must be Chinese-first"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )

    _write_editorial_response(required)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["period_label"] = "2026-08-23 — 2026-08-30"
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="must match the actual work window"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )

    _write_editorial_response(required)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["title"] = "项目阶段分析周报"
    response["sections"] = response["sections"][::-1]
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="overview-to-depth contract"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )

    _write_editorial_response(required)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["sections"][0]["items"][0]["item_id"] = "authored_id"
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="item_id is assigned by the consumer"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )

    _write_editorial_response(required)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["raw_content"] = "must not enter a frozen report"
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden raw/private field"):
        consume_pending_periodic_report_intent(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            execute=True,
        )


def test_consumption_reuses_the_exact_frozen_fact_request(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)
    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    request_path = Path(required["editorial_request_path"])
    original = request_path.read_text(encoding="utf-8")
    state_path = registry.parent / "ACTIVE_GOAL_STATE.md"
    state_path.write_text(
        state_path.read_text(encoding="utf-8").replace(
            "validated-analysis-outcome", "later-mutable-registry-prose"
        ),
        encoding="utf-8",
    )

    replay = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert replay["status"] == "editorial_required"
    assert request_path.read_text(encoding="utf-8") == original


def test_consumption_derives_the_period_from_actual_report_facts(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    state_path = registry.parent / "ACTIVE_GOAL_STATE.md"
    state_path.write_text(
        state_path.read_text(encoding="utf-8").replace(
            "updated_at=2026-08-30T09:00:00Z",
            "updated_at=2026-08-29T22:42:26+08:00",
        ),
        encoding="utf-8",
    )

    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    request = json.loads(
        Path(required["editorial_request_path"]).read_text(encoding="utf-8")
    )

    assert request["actual_work_window"] == {
        "start_at": "2026-08-29T14:42:26+00:00",
        "end_at": "2026-08-30T09:00:00+00:00",
        "period_label": "2026-08-29 22:42 — 2026-08-30 17:00（北京时间）",
        "source": "agent_run_history_or_report_facts",
    }


def test_consumption_prefers_real_agent_run_start_over_completion_timestamps(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)
    run_dir = runtime / "goals" / GOAL_ID / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "index.jsonl").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-29T19:24:27+08:00",
                "agent_id": AGENT_ID,
                "classification": "state_refreshed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    required = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    request = json.loads(
        Path(required["editorial_request_path"]).read_text(encoding="utf-8")
    )

    assert request["actual_work_window"]["start_at"] == ("2026-08-29T11:24:27+00:00")
    assert request["actual_work_window"]["period_label"] == (
        "2026-08-29 19:24 — 2026-08-30 17:00（北京时间）"
    )


def test_cross_agent_or_malformed_intent_fails_closed(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)
    assert (
        pending_periodic_report_intents(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id="other-agent",
        )
        == []
    )
    sidecar = next(
        (runtime / "goals" / GOAL_ID / "post_writeback_hooks").glob("*.json")
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["intent"]["requested_write_scope"] = ["external_delivery"]
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        pending_periodic_report_intents(
            registry_path=registry,
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        == []
    )
