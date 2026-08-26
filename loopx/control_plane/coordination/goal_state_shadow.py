"""Bridge the legacy Markdown goal state into a coordination bootstrap head.

This is the read side of the RFC section 11 shadow: it projects the current
``ACTIVE_GOAL_STATE.md`` text through loopx's own todo projection and admits
exactly the open, unclaimed agent todos into an explicit ``bootstrap_head``.
Nothing is written back.

It lives apart from ``head`` deliberately: the head module is the pure v0
document codec with a stdlib-plus-core import closure and sits inside the
repository's strict type gate, while this bridge is the one place the
coordination contract reaches into the untyped legacy projection world
(`todos.contract`, ``todos.handoff_mode``, the active-state parser). When
that world joins the typed gate, this module follows.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..todos.contract import normalize_todo_claimed_by, normalize_todo_id
from ..todos.handoff_mode import goal_handoff_mode
from .authority_core import HandoffMode
from .head import HeadValidationError, bootstrap_head


def _static_projection_digest(allowed_agent_ids: list[str]) -> str:
    encoded = json.dumps(sorted(allowed_agent_ids), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def bootstrap_head_from_goal_state(
    state_text: str,
    *,
    goal_id: str,
    repository: str,
    code_revision: str,
    allowed_agent_ids: list[str],
    store_binding: str,
    with_report: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Shadow the current Markdown active state into a bootstrap head.

    Claimed and done todos are reported, never silently dropped; a
    ``soft_claim`` goal fails closed instead of having its declared no-lease
    semantics silently inverted by shared ``claim_work``.
    """

    from ..todos.active_state_todo_parser import parse_active_state_todos

    source_mode = goal_handoff_mode(state_text)
    if source_mode == HandoffMode.SOFT_CLAIM.value:
        raise HeadValidationError(
            "a soft_claim goal cannot bootstrap into shared authority: its"
            " declared mode rejects lease minting, which shared claim_work"
            " performs on every accepted claim"
        )
    projected = parse_active_state_todos(state_text)
    skipped: dict[str, str] = {}
    todos: dict[str, Any] = {}
    for item in projected["agent_todos"]["items"]:
        todo_id = normalize_todo_id(item.get("todo_id"))
        if not todo_id:
            continue
        if item.get("done"):
            skipped[todo_id] = "done"
            continue
        if normalize_todo_claimed_by(item.get("claimed_by")):
            skipped[todo_id] = "claimed"
            continue
        todos[todo_id] = {
            "todo_revision": 0,
            "status": "open",
            "claimed_by": None,
            "eligibility": {
                "authorization_projection_revision": 0,
                "authorization_projection_digest": _static_projection_digest(
                    allowed_agent_ids
                ),
                "allowed_agent_ids": list(allowed_agent_ids),
                "dependencies_satisfied": True,
                "dependency_revision": 0,
                "gates_open": True,
                "gate_revision": 0,
            },
            "repository": repository,
            "code_revision": code_revision,
            "last_lease_epoch": 0,
        }
    head = bootstrap_head(goal_id, todos, store_binding=store_binding)
    if not with_report:
        return head
    report = {
        "skipped": skipped,
        "source_handoff_mode": source_mode,
        "admitted": sorted(todos),
    }
    return head, report
