from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_prompt import render_cli_preflight, render_quota_guard_command, render_quota_spend_command


DEFAULT_MATERIAL_QUEUE_RULE = "Do not consume the learning material queue unless the user explicitly asks."
DEFAULT_PERMISSION_RULE = "Do not ask for permissions when the current Codex session is already trusted."


def build_heartbeat_prompt(
    *,
    goal_id: str,
    active_state: Path,
    material_queue_rule: str | None = None,
    permission_rule: str | None = None,
) -> dict[str, Any]:
    active_state_text = str(active_state.expanduser())
    resolved_material_rule = material_queue_rule or DEFAULT_MATERIAL_QUEUE_RULE
    resolved_permission_rule = permission_rule or DEFAULT_PERMISSION_RULE
    quota_guard_command = render_quota_guard_command(goal_id)
    quota_spend_command = render_quota_spend_command(goal_id, source="heartbeat")
    cli_preflight = render_cli_preflight()
    task_body = render_heartbeat_task_body(
        goal_id=goal_id,
        active_state=active_state_text,
        cli_preflight=cli_preflight,
        quota_guard_command=quota_guard_command,
        quota_spend_command=quota_spend_command,
        material_queue_rule=resolved_material_rule,
        permission_rule=resolved_permission_rule,
    )
    return {
        "ok": True,
        "goal_id": goal_id,
        "active_state": active_state_text,
        "quota_guard_command": quota_guard_command,
        "quota_spend_command": quota_spend_command,
        "cli_preflight": cli_preflight,
        "material_queue_rule": resolved_material_rule,
        "permission_rule": resolved_permission_rule,
        "task_body": task_body,
    }


def render_heartbeat_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    quota_guard_command: str,
    quota_spend_command: str,
    material_queue_rule: str,
    permission_rule: str,
) -> str:
    return f"""Advance `{goal_id}` using `{active_state}`.

Before spending delivery compute, first make the Goal Harness CLI reachable in
this automation shell, then run the quota guard:

```bash
{cli_preflight}
{quota_guard_command}
```

If that preflight still fails, do not do implementation work, adapter work,
file edits, research, project exploration, or quota spend in this turn. Return
a quiet heartbeat `DONT_NOTIFY` response with the exact preflight failure
reason.

If the result says `should_run=false`:

- If the payload says `state=operator_gate`, treat the gate as a user/controller
  interaction, not as a silent skip. Read `gate_prompt`, `operator_question`,
  `recommended_action`, `next_handoff_condition`, `missing_gates`,
  `user_todo_summary`, and `agent_todo_summary` from the payload. If the same
  unresolved gate has not already been asked in the recent visible thread,
  return heartbeat `NOTIFY`
  with one concise Chinese question that lists the gate and the expected reply
  format. If `user_todo_summary.open_count > 0`, the notification must list the
  existing open user todos even when there are no newly discovered user actions;
  never summarize this case as "no new user action". Do not execute
  `agent_command`, adapter work, write-control, production actions, or the
  gated path while asking.
- If the payload also says `safe_bypass_allowed=true` and the same gate has
  already been surfaced, the gate blocks only the gated delivery path. You may
  read the active state and do exactly one bounded safe-bypass step from the
  Priority Stack, such as read-only steering analysis, documentation, or another
  P0/P1 item that does not depend on that gate. If you do a safe-bypass step,
  validate it, write back progress/critic/next action, optionally refresh state,
  append exactly one spend event, and report compactly. If
  `user_todo_summary.open_count > 0`, that report must include the existing
  open user todos and must not say there is "no new user action". If
  `agent_todo_summary.open_count > 0`, the report should also name the first
  safe agent todo it can execute next. If no useful safe-bypass step exists,
  report the pending gate compactly instead of doing work.
- Otherwise, do not do implementation work, adapter work, file edits, research,
  or project exploration in this turn. Return a quiet heartbeat `DONT_NOTIFY`
  response with the skip reason.

If the result says `should_run=true`:

1. Read the active state, Priority Stack, recent progress, and critic.
2. Run a short steering audit before choosing work: list at least three
   plausible next-action candidates across different P0/P1/P2 lanes when
   useful; if the same topic has consumed several recent delivery slices, apply
   a continuation check and state why continuing still wins; keep compute quota
   separate from focus quota; record any losing high-value candidate that should
   not be forgotten.
3. Run the no-progress self-stop check before choosing delivery work. Inspect
   recent active-state progress and run history for consecutive eligible
   heartbeat turns. Count a turn as no-progress only when it produced no
   substantive artifact, no adapter or implementation progress, no new gate or
   user decision, no new validation signal, and only repeated
   status/brief-check/compact-checkpoint state edits. If 5 consecutive eligible
   heartbeats are no-progress loops, delete or pause this heartbeat automation
   through the Codex App automation management path, do not append a quota spend
   for that self-cancel turn, and return `NOTIFY` explaining that the automation
   was cancelled because it was spinning without progress.
4. Choose exactly one bounded, verifiable step from that audit.
5. Do that step only. Keep public/private boundaries intact. Public-safe repo
   publication is not an operator gate by itself: for routine public project
   work, commit, push, and PR creation may proceed autonomously after validation
   and a clean public/private boundary scan. Stop and surface a user/controller
   gate only for private or company-internal material, credentials, destructive
   git operations, production actions, or repository rules that explicitly
   require review.
6. Run the smallest useful validation.
7. Write back changed files, validation, critic, and next action to the active
   state. If the step discovers a concrete user/owner action, do not hide it in
   `Next Action`, a review doc, or chat. Add it to the active-state user todo
   queue with:

   ```bash
   goal-harness todo add --goal-id {goal_id} --role user --text "<public-safe user/owner action>"
   ```

   Use `--role agent` for project-agent follow-up work.
   For the full field contract, see `docs/project-agent-todo-contract.md` in
   the Goal Harness checkout.
8. If the dashboard or controller needs to see a state-only update, run:

   ```bash
   goal-harness refresh-state --goal-id {goal_id}
   ```

9. After validation and required state refresh are complete, append exactly one
   spend event:

   ```bash
   {quota_spend_command}
   ```

   Do not append spend for quiet `should_run=false` skips, preflight failures,
   pure dry-run previews, or duplicate accounting attempts. If
   `should_run=false` but `safe_bypass_allowed=true` and you actually completed
   a bounded safe-bypass step, append this same spend event once after
   validation/writeback.

10. Return a compact final report. Use heartbeat `NOTIFY` only for meaningful
    user visibility, such as a committed artifact, a user gate, a real blocker,
    or the automation self-stop. Otherwise use `DONT_NOTIFY`.

{material_queue_rule}
{permission_rule}"""


def render_heartbeat_prompt_markdown(payload: dict[str, Any]) -> str:
    return f"""# Heartbeat Automation Prompt

Copy this task body into a Codex App heartbeat automation.

````text
{payload.get("task_body", "")}
````

## Generator Inputs

- goal_id: `{payload.get("goal_id")}`
- active_state: `{payload.get("active_state")}`
- quota_guard_command: `{payload.get("quota_guard_command")}`
- quota_spend_command: `{payload.get("quota_spend_command")}`
- cli_preflight: `{payload.get("cli_preflight")}`
"""
