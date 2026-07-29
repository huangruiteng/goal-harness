from loopx.control_plane.todos.user_gate import build_user_todo_notification


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
