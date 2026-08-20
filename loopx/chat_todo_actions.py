"""Typed Chat actions for canonical Todo lifecycle transitions."""

from __future__ import annotations

from typing import Any

from .todos import complete_goal_todo, update_goal_todo


class ChatTodoActionMixin:
    """Keep Todo preview/apply parity separate from general orchestration."""

    def _run_todo_update(
        self, parameters: dict[str, Any], *, dry_run: bool
    ) -> dict[str, Any]:
        goal_id = str(parameters["goal_id"])
        operation = str(parameters.get("operation") or "edit")
        if operation == "complete":
            return complete_goal_todo(
                registry_path=self.registry_path,
                goal_id=goal_id,
                todo_id=str(parameters["todo_id"]),
                note=parameters.get("note"),
                no_followup=bool(parameters.get("no_followup", True)),
                successor_todo_ids=parameters.get("successor_todo_ids"),
                agent_id=parameters.get("agent_id"),
                authority_reason="owner-confirmed typed Chat action",
                dry_run=dry_run,
            )
        status = parameters.get("status")
        if operation == "block":
            status = "blocked"
        elif operation == "defer":
            status = "deferred"
        return update_goal_todo(
            registry_path=self.registry_path,
            goal_id=goal_id,
            todo_id=str(parameters["todo_id"]),
            text=parameters.get("text"),
            status=status,
            note=parameters.get("note"),
            claimed_by=(
                parameters.get("agent_id") if operation == "reassign" else None
            ),
            resume_when=parameters.get("resume_when"),
            successor_todo_ids=parameters.get("successor_todo_ids"),
            agent_id=parameters.get("agent_id"),
            authority_reason="owner-confirmed typed Chat action",
            dry_run=dry_run,
        )

    def _apply_todo_update(
        self, proposal_id: str, proposal: dict[str, Any], parameters: dict[str, Any]
    ) -> dict[str, Any]:
        from .chat_actions import _digest, _opaque

        goal_id = str(parameters["goal_id"])
        current_fingerprint = self._goal_state_fingerprint(goal_id)
        if current_fingerprint != proposal.get("expected_state_fingerprint"):
            stale = self.store.apply(
                proposal_id, current_state_fingerprint=current_fingerprint, receipt={}
            )
            return {"proposal": stale, "turn": None}
        operation = str(parameters.get("operation") or "edit")
        result = self._run_todo_update(parameters, dry_run=False)
        todo_id = _opaque(result.get("todo_id"), field="todo_id")
        receipt = {
            "receipt_id": _digest({"proposal_id": proposal_id, "todo_id": todo_id})[
                :32
            ],
            "outcome": (
                "todo_completed"
                if operation == "complete"
                else "todo_updated" if result.get("changed") else "todo_unchanged"
            ),
            "projection_verified": True,
            "resource_ids": {"goal_id": goal_id, "todo_id": todo_id},
        }
        stored = self.store.apply(
            proposal_id, current_state_fingerprint=current_fingerprint, receipt=receipt
        )
        return {"proposal": stored, "turn": None}
