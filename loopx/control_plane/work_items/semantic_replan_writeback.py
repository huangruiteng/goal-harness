"""Write-time qualification for open semantic replan obligations."""

from __future__ import annotations

from typing import Any

from ..goals.goal_frontier import (
    build_goal_frontier_projection_context_from_status,
)
from ..status.autonomous_replan_projection import (
    autonomous_replan_obligation_from_runs,
)
from ..todos.active_state_todo_parser import parse_active_state_todos
from .progress_observation import semantic_delta_from_writeback
from .work_lane_context import build_work_lane_context_contract


def _obligation_was_created_by_current_completion(
    obligation: dict[str, Any],
    *,
    agent_todos: dict[str, Any] | None,
    completion_todo_id: str | None,
    completion_turn_key: str | None,
) -> bool:
    """Keep a new successor obligation for the next decision boundary.

    A validated Turn completes its Todo before its refresh row is written.  The
    completion can therefore create a ``completed_advancement_without_successor``
    obligation inside the same transaction.  That new obligation did not exist
    when the Turn began and must govern the next decision, not reject the
    completion that caused it.

    The exemption is deliberately narrow and causal: every trigger must name
    the Todo completed by this exact Turn, and the current durable Todo row must
    carry the same completion identity.  Any older or mixed obligation remains
    write-gated.
    """

    safe_todo_id = str(completion_todo_id or "").strip()
    safe_turn_key = str(completion_turn_key or "").strip()
    if not safe_todo_id or not safe_turn_key or not isinstance(agent_todos, dict):
        return False
    triggers = obligation.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        return False
    if any(
        not isinstance(trigger, dict)
        or trigger.get("kind") != "completed_advancement_without_successor"
        or str(trigger.get("todo_id") or "").strip() != safe_todo_id
        for trigger in triggers
    ):
        return False
    items = agent_todos.get("items")
    return any(
        isinstance(item, dict)
        and str(item.get("todo_id") or "").strip() == safe_todo_id
        and item.get("status") == "done"
        and str(item.get("completion_turn_key") or "").strip() == safe_turn_key
        for item in items or []
    )


def qualify_replan_writeback(
    *,
    newest_first_runs: list[dict[str, Any]] | None,
    state_text: str,
    agent_id: str,
    goal_id: str,
    progress_observation: dict[str, Any] | None = None,
    registry_goal: dict[str, Any] | None = None,
    agent_vision: dict[str, Any] | None = None,
    completion_todo_id: str | None = None,
    completion_turn_key: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the shared open obligation and the writeback's typed delta.

    The write path deliberately reuses quota's goal-frontier reducer. It does
    not classify maintenance from prose and therefore sees obligations derived
    from run history, agent vision, and final-outcome checkpoints alike.
    """

    safe_agent_id = str(agent_id or "").strip()
    if not safe_agent_id:
        return None, None
    todo_projection = parse_active_state_todos(state_text, item_limit=None)
    agent_todos = todo_projection.get("agent_todos")
    run_obligation = autonomous_replan_obligation_from_runs(
        newest_first_runs,
        agent_todos=agent_todos,
        agent_id=safe_agent_id,
    )
    status_payload = {
        "run_history": {
            "goals": [
                {
                    "id": goal_id,
                    "latest_runs": list(newest_first_runs or []),
                }
            ]
        }
    }
    context = build_goal_frontier_projection_context_from_status(
        goal_id=goal_id,
        agent_id=safe_agent_id,
        status_payload=status_payload,
        item={
            **(
                {"autonomous_replan_obligation": run_obligation}
                if run_obligation
                else {}
            )
        },
        project_asset=None,
        user_todo_summary=todo_projection.get("user_todos"),
        agent_todo_summary=agent_todos,
        work_lane_contract=build_work_lane_context_contract(
            {"progress_scope": "primary_goal"},
            agent_todo_summary=agent_todos,
        ),
        neutral_replan_ack_classifications=set(),
        registered_agent_ids=[safe_agent_id],
        goal_status=str((registry_goal or {}).get("status") or "active"),
        agent_profile=None,
    )
    obligation = context.get("replan_obligation")
    if not obligation:
        return None, None
    if _obligation_was_created_by_current_completion(
        obligation,
        agent_todos=agent_todos,
        completion_todo_id=completion_todo_id,
        completion_turn_key=completion_turn_key,
    ):
        return None, None
    return obligation, semantic_delta_from_writeback(
        obligation=obligation,
        progress_observation=progress_observation,
        agent_vision=agent_vision,
    )


def enforce_open_replan_writeback(
    *,
    newest_first_runs: list[dict[str, Any]] | None,
    state_text: str,
    agent_id: str,
    goal_id: str,
    progress_observation: dict[str, Any] | None = None,
    registry_goal: dict[str, Any] | None = None,
    agent_vision: dict[str, Any] | None = None,
    completion_todo_id: str | None = None,
    completion_turn_key: str | None = None,
) -> dict[str, Any] | None:
    """Fail closed unless concrete typed evidence satisfies the open replan."""

    obligation, semantic_delta = qualify_replan_writeback(
        newest_first_runs=newest_first_runs,
        state_text=state_text,
        agent_id=agent_id,
        goal_id=goal_id,
        progress_observation=progress_observation,
        registry_goal=registry_goal,
        agent_vision=agent_vision,
        completion_todo_id=completion_todo_id,
        completion_turn_key=completion_turn_key,
    )
    if not obligation:
        return None
    if isinstance(semantic_delta, dict) and semantic_delta.get("accepted") is True:
        return semantic_delta
    raise ValueError(
        "an open autonomous replan obligation requires a typed semantic delta; "
        "this writeback does not change an accepted surface, hypothesis, probe "
        "family, concrete blocker, coverage-backed terminal, or required vision "
        "outcome. Host-projected replan context is authoritative; write a typed "
        "progress observation or a fresh evidence-linked vision path outcome."
    )
