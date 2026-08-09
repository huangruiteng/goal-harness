"""Heartbeat prompt rule constants inside the heartbeat bounded context."""

from __future__ import annotations


DEFAULT_MATERIAL_QUEUE_RULE = "Do not consume the learning material queue unless the user explicitly asks."
DEFAULT_PERMISSION_RULE = "Do not ask for permissions when the current Codex session is already trusted."
USER_TODO_FINAL_MESSAGE_RULE = (
    "`interaction_contract.user_channel.notify` controls output: `NOTIFY` -> concrete "
    "action; otherwise quiet. `should_run`/due monitor and other-agent scoped todos "
    "are not user prompts. Only inside `NOTIFY`, `action_required` without an action -> "
    '"具体 user todo 未投影，需修复 LoopX 状态投影"; with `DONT_NOTIFY`, repair '
    "the projection internally and stay quiet."
)
HEARTBEAT_NOTIFICATION_RULE_SHORT = (
    "`user_channel.notify`: NOTIFY=Chinese action; DONT_NOTIFY=quiet. "
    "Due/peer gate != prompt; missing NOTIFY action->"
    "具体user todo未投影，需修复LoopX状态投影."
)
HEARTBEAT_VISION_WRITEBACK_RULE_SHORT = (
    "writeback: no-change=`surface_only`/no spend; "
    "unchanged->`--vision-unchanged-reason`; material->actual outcome."
)
SCHEDULER_HINT_APPLICATION_RULE = (
    "`scheduler_hint` no-spend. host_action=pause_or_delete_current_heartbeat -> "
    "automation_update stop once, verify, end; else apply_needed -> RRULE then "
    "ack/failure_hint; ack_needed -> ack."
)
SCHEDULER_HINT_COMPACT_RULE = (
    "host_action=pause_or_delete_current_heartbeat: automation_update stop; "
    "else RRULE apply/ack/fail. No spend."
)
SCHEDULER_HINT_THIN_RULE = (
    "host_action=pause_or_delete_current_heartbeat->automation_update stop(no-spend); "
    "else RRULE/ack/fail."
)
RUNTIME_CAPABILITY_PROJECTION_THIN_RULE = (
    "Observed capabilities -> `--available-capability`; never user gates."
)
RUNTIME_EXECUTION_ROUTING_RULE = (
    "Normal turns use CLI `interaction_contract`; use `loopx-project` for "
    "lifecycle/registry and `loopx-self-repair` for runtime/projection drift."
)
CODEX_NATIVE_GOAL_UNCHANGED_WAIT_RULE = """

Native Codex `/goal` owns its blocked state. At the matching
`scheduler_hint.unchanged_poll` limit, rerun quota once. If the same blocking
condition remains for the third consecutive Goal turn and no meaningful progress
is possible, call `update_goal` with `status=blocked`. This stops native Goal
continuation without spending or completing LoopX. Only user `/goal resume`
reactivates it; rerun quota after resume."""
