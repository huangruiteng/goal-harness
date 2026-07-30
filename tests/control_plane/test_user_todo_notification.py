from loopx.control_plane.todos.user_gate import (
    apply_scoped_user_gate_fallback_projection,
    build_user_todo_notification,
)


def test_user_gate_notification_repeats_until_resolved() -> None:
    summary = {
        "open_count": 1,
        "gate_open_items": [
            {
                "todo_id": "todo_gate",
                "task_class": "user_gate",
                "action_kind": "approve_release",
            }
        ],
    }

    assert build_user_todo_notification(
        summary,
        state="operator_gate",
        waiting_on="controller",
    ) == {
        "notify_user_on_gate": True,
        "open_todo_notify_reason": (
            "open user_gate todo requires owner decision before approve_release"
        ),
        "open_todo_notification_policy": "repeat_until_resolved",
    }


def test_waiting_user_todo_notification_does_not_force_repeat_policy() -> None:
    assert build_user_todo_notification(
        {"open_count": 1},
        state="waiting",
        waiting_on="controller",
    ) == {
        "notify_user_on_open_todo": True,
        "open_todo_notify_reason": "open user todo can resolve the user/controller blocker",
    }


def test_heartbeat_repeat_reason_owns_repeat_notification_policy() -> None:
    assert build_user_todo_notification(
        {"open_count": 1},
        state="eligible",
        waiting_on="",
        repeat_notification_required=True,
        repeat_notification_reason="repeat this owner action",
    ) == {
        "notify_user_on_open_todo": True,
        "open_todo_notify_reason": "repeat this owner action",
        "open_todo_notification_policy": "repeat_until_resolved",
    }


def test_closed_user_todo_summary_has_no_notification() -> None:
    assert (
        build_user_todo_notification(
            {"open_count": 0},
            state="waiting",
            waiting_on="",
        )
        == {}
    )


def test_scoped_user_gate_fallback_projects_executable_bypass() -> None:
    payload = {
        "decision": "skip",
        "effective_action": "monitor_quiet_skip",
        "should_run": False,
        "execution_obligation": {"source": "base"},
    }
    fallback = {
        "recommended_action": "advance the non-gated todo",
        "reason": "the user gate has a narrower action scope",
    }

    projected = apply_scoped_user_gate_fallback_projection(
        payload,
        fallback=fallback,
        replan_decision_allowed=False,
    )

    assert payload["decision"] == "skip"
    assert projected["decision"] == "safe_bypass_user_gate_fallback"
    assert projected["effective_action"] == "scoped_user_gate_fallback"
    assert projected["should_run"] is True
    assert projected["scoped_user_gate_fallback"] == fallback
    assert projected["safe_bypass_allowed"] is True
    assert projected["safe_bypass_kind"] == "scoped_user_gate_fallback"
    assert projected["actionable_by_codex"] is True
    assert projected["execution_obligation"] == {
        "source": "base",
        "must_attempt_work": True,
        "kind": "scoped_user_gate_fallback",
        "minimum": "one_non_gated_fallback_segment_after_user_gate_notice",
        "delivery_allowed": True,
        "notify_is_execution_gate": False,
        "contract": "scoped_user_gate_fallback",
        "contract_obligation": "advance the non-gated todo",
        "reason": "the user gate has a narrower action scope",
    }


def test_scoped_user_gate_fallback_does_not_override_replan() -> None:
    payload = {
        "decision": "autonomous_replan_required",
        "effective_action": "autonomous_replan_required",
        "should_run": True,
    }

    projected = apply_scoped_user_gate_fallback_projection(
        payload,
        fallback={"recommended_action": "advance the non-gated todo"},
        replan_decision_allowed=True,
    )

    assert projected is payload
    assert "scoped_user_gate_fallback" not in projected
