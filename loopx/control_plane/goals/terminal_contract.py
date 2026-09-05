"""Typed terminal contract at the one-shot-host / LoopX boundary.

A one-shot Goal host (e.g. Ark Managed Agent) can tell the agent that local
delivery ends the host Goal. Without a typed contract at the boundary, the
nested LoopX-guided Goal still projects ordinary Todo, refresh, quota, and
Goal-settlement work, and the model wastes hours reconciling two terminal
protocols.

This module defines a provider-neutral terminal-disposition contract that
makes explicit:

- Who owns terminalization.
- Whether task-Todo closeout / LoopX Goal closeout / final evidence writeback
  are agent-required / host-owned / not applicable.
- The exact Goal and provider/session identity to which the disposition binds.
- Which terminal evidence proves that the host-owned path may run.

When a host-owned disposition is admitted: persist it, project it
consistently, don't present ordinary agent settlement as competing, let the
host atomically record or tear down isolated Todo/Goal state, and reject
unsupported/contradictory dispositions at admission.
"""

from __future__ import annotations

from typing import Any

TERMINAL_CONTRACT_SCHEMA_VERSION = "loopx_goal_terminal_contract_v0"

TERMINAL_OWNERSHIP_VALUES = frozenset(
    {
        "agent",
        "host",
        "not_applicable",
    }
)

CLOSEOUT_OWNER_VALUES = frozenset(
    {
        "agent_required",
        "host_owned",
        "not_applicable",
    }
)

TERMINAL_EVIDENCE_KIND_VALUES = frozenset(
    {
        "host_delivery_receipt",
        "host_submission_confirmation",
        "not_applicable",
    }
)


def build_terminal_contract(
    *,
    host_surface: str,
    goal_id: str,
    agent_id: str | None,
    provider_session_id: str | None = None,
) -> dict[str, Any]:
    """Build the typed terminal contract for a guided Goal.

    For one-shot host surfaces (ark-managed-agent, deepseek-harness-native),
    the host owns terminalization: the agent must not project ordinary
    LoopX settlement after validated local delivery.
    """
    ownership = _terminal_ownership_for_host(host_surface)
    return {
        "schema_version": TERMINAL_CONTRACT_SCHEMA_VERSION,
        "terminal_ownership": ownership,
        "task_todo_closeout": _task_todo_closeout_for(ownership),
        "loopx_goal_closeout": _loopx_goal_closeout_for(ownership),
        "final_evidence_writeback": _final_evidence_writeback_for(ownership),
        "bound_goal_id": goal_id,
        "bound_agent_id": agent_id,
        "bound_provider_session_id": provider_session_id,
        "host_surface": host_surface,
        "terminal_evidence": _terminal_evidence_for(ownership),
    }


def _terminal_ownership_for_host(host_surface: str) -> str:
    if host_surface in {"ark-managed-agent", "deepseek-harness-native"}:
        return "host"
    if host_surface in {"manual", "other-agent"}:
        return "not_applicable"
    return "agent"


def _task_todo_closeout_for(ownership: str) -> str:
    if ownership == "host":
        return "host_owned"
    if ownership == "not_applicable":
        return "not_applicable"
    return "agent_required"


def _loopx_goal_closeout_for(ownership: str) -> str:
    if ownership == "host":
        return "host_owned"
    if ownership == "not_applicable":
        return "not_applicable"
    return "agent_required"


def _final_evidence_writeback_for(ownership: str) -> str:
    if ownership == "host":
        return "host_owned"
    if ownership == "not_applicable":
        return "not_applicable"
    return "agent_required"


def _terminal_evidence_for(ownership: str) -> dict[str, Any]:
    if ownership == "host":
        return {
            "kind": "host_submission_confirmation",
            "description": (
                "The host runtime confirms the Goal submission was accepted. "
                "That confirmation is the terminal evidence; the agent must "
                "not project ordinary LoopX settlement afterward."
            ),
        }
    return {"kind": "not_applicable", "description": None}


def validate_terminal_contract(contract: Any) -> list[str]:
    """Validate a terminal contract. Returns a list of error strings."""
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["terminal_contract must be an object"]

    schema_version = contract.get("schema_version")
    if schema_version != TERMINAL_CONTRACT_SCHEMA_VERSION:
        errors.append(
            f"terminal_contract.schema_version must be "
            f"{TERMINAL_CONTRACT_SCHEMA_VERSION!r}"
        )

    ownership = contract.get("terminal_ownership")
    if ownership not in TERMINAL_OWNERSHIP_VALUES:
        errors.append(
            f"terminal_contract.terminal_ownership must be one of "
            f"{sorted(TERMINAL_OWNERSHIP_VALUES)}; got {ownership!r}"
        )

    for field in ("task_todo_closeout", "loopx_goal_closeout", "final_evidence_writeback"):
        value = contract.get(field)
        if value not in CLOSEOUT_OWNER_VALUES:
            errors.append(
                f"terminal_contract.{field} must be one of "
                f"{sorted(CLOSEOUT_OWNER_VALUES)}; got {value!r}"
            )

    bound_goal_id = contract.get("bound_goal_id")
    if not bound_goal_id or not isinstance(bound_goal_id, str):
        errors.append("terminal_contract.bound_goal_id must be a non-empty string")

    evidence = contract.get("terminal_evidence")
    if not isinstance(evidence, dict):
        errors.append("terminal_contract.terminal_evidence must be an object")
    elif evidence.get("kind") not in TERMINAL_EVIDENCE_KIND_VALUES:
        errors.append(
            f"terminal_contract.terminal_evidence.kind must be one of "
            f"{sorted(TERMINAL_EVIDENCE_KIND_VALUES)}"
        )

    # Consistency: host-owned closeouts must not coexist with agent ownership.
    if ownership == "agent":
        for field in ("task_todo_closeout", "loopx_goal_closeout", "final_evidence_writeback"):
            if contract.get(field) == "host_owned":
                errors.append(
                    f"terminal_contract.{field} cannot be host_owned when "
                    f"terminal_ownership is agent"
                )
    elif ownership == "host":
        for field in ("task_todo_closeout", "loopx_goal_closeout", "final_evidence_writeback"):
            if contract.get(field) == "agent_required":
                errors.append(
                    f"terminal_contract.{field} cannot be agent_required when "
                    f"terminal_ownership is host"
                )

    return errors


def is_host_owned_terminal(contract: Any) -> bool:
    """Return True when the terminal contract declares host-owned closeout."""
    if not isinstance(contract, dict):
        return False
    return (
        contract.get("terminal_ownership") == "host"
        and contract.get("loopx_goal_closeout") == "host_owned"
    )


def terminal_contract_summary(contract: dict[str, Any]) -> str:
    """Render a compact human-readable summary of the terminal contract."""
    if not isinstance(contract, dict):
        return "terminal_contract: invalid"
    ownership = contract.get("terminal_ownership", "?")
    goal_id = contract.get("bound_goal_id", "?")
    return (
        f"terminal_contract: ownership={ownership} "
        f"goal={goal_id} "
        f"todo_closeout={contract.get('task_todo_closeout', '?')} "
        f"goal_closeout={contract.get('loopx_goal_closeout', '?')} "
        f"evidence_writeback={contract.get('final_evidence_writeback', '?')}"
    )


def render_terminal_contract_markdown(contract: dict[str, Any]) -> str:
    """Render the terminal contract section for the guided start markdown.

    Returns an empty string when the contract is not a host-owned terminal
    contract. The caller is responsible for inserting the returned block
    into the larger guided-start markdown document.
    """
    if not isinstance(contract, dict):
        return ""
    ownership = contract.get("terminal_ownership", "")
    todo_closeout = contract.get("task_todo_closeout", "")
    goal_closeout = contract.get("loopx_goal_closeout", "")
    evidence_writeback = contract.get("final_evidence_writeback", "")
    evidence = contract.get("terminal_evidence", {})
    evidence_kind = evidence.get("kind", "") if isinstance(evidence, dict) else ""
    evidence_desc = evidence.get("description", "") if isinstance(evidence, dict) else ""
    lines = [
        "",
        "## Terminal Contract",
        "",
        f"- ownership: `{ownership}`",
        f"- task_todo_closeout: `{todo_closeout}`",
        f"- loopx_goal_closeout: `{goal_closeout}`",
        f"- final_evidence_writeback: `{evidence_writeback}`",
        f"- terminal_evidence_kind: `{evidence_kind}`",
    ]
    if evidence_desc:
        lines.append(f"- terminal_evidence: {evidence_desc}")
    if ownership == "host":
        lines.append(
            "\nThe host owns terminalization. After validated local delivery, "
            "do not project ordinary LoopX settlement (Todo closeout, "
            "Goal closeout, or evidence writeback). Let the host atomically "
            "record or tear down isolated Todo/Goal state."
        )
    return "\n".join(lines) + "\n"
