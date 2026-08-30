from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ...control_plane.capability_hooks import (
    INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION,
    InteractionProjectionHookRegistration,
)
from ...control_plane.todos.active_state_todo_parser import parse_active_state_todos
from ...registry import atomic_write_json, find_registry_goal, read_json, resolve_state_file
from ...todos import add_goal_todo
from ...presentation.renderers.periodic_report_html import render_periodic_report_html
from ...presentation.renderers.periodic_report_markdown import (
    render_periodic_report_markdown,
)
from .adapters import build_periodic_report_document
from .bindings import build_periodic_report_generation_bundle
from .post_writeback_hook import (
    PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
    PERIODIC_REPORT_TRIGGER_EVALUATION_INTENT,
    evaluate_periodic_report_trigger_evaluation_intent,
)
from .project_progress import build_project_progress_periodic_report_source


PENDING_INTENT_SCHEMA = "pending_capability_intent_projection_v0"
CONSUMPTION_RECEIPT_SCHEMA = "periodic_report_intent_consumption_receipt_v0"
HOOK_ID = "periodic_report.pending_intent"
CAPABILITY_ID = "periodic-report"
_DISPATCH_RE = re.compile(r"^pwh_[0-9a-f]{64}\.json$")
_IDENTITY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,127}$")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _intent_key(intent: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        str(intent.get("idempotency_key") or "").encode("utf-8")
    ).hexdigest()[:24]


def _receipt_path(runtime_root: Path, goal_id: str, intent: Mapping[str, Any]) -> Path:
    return (
        runtime_root
        / "goals"
        / goal_id
        / "periodic_reports"
        / _intent_key(intent)
        / "receipt.json"
    )


def _valid_sidecar_intent(
    value: object, *, dispatch_id: str, goal_id: str, agent_id: str
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if (
        value.get("schema_version") != POST_WRITEBACK_HOOK_RECEIPT_SCHEMA_VERSION
        or value.get("dispatch_id") != dispatch_id
        or value.get("status") != "intent_recorded"
        or value.get("hook_id") != PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID
        or value.get("capability_id") != CAPABILITY_ID
        or value.get("error_code") is not None
        or type(value.get("attempt_count")) is not int
        or int(value["attempt_count"]) < 1
    ):
        return None
    intent = value.get("intent")
    if not isinstance(intent, Mapping):
        return None
    if intent.get("source_receipt_id") != value.get("source_receipt_id"):
        return None
    try:
        decision = evaluate_periodic_report_trigger_evaluation_intent(intent)
    except ValueError:
        return None
    if decision.get("eligible") is not True:
        return None
    payload = intent.get("payload")
    stage = payload.get("stage_completion") if isinstance(payload, Mapping) else None
    if not isinstance(stage, Mapping) or stage.get("agent_id") != agent_id:
        return None
    if not goal_id or not agent_id:
        return None
    return dict(intent)


def pending_periodic_report_intents(
    *, runtime_root: Path, goal_id: str, agent_id: str
) -> list[dict[str, Any]]:
    """Read only exact, eligible, unconsumed intents for one Goal/Agent."""

    if not _IDENTITY_RE.fullmatch(goal_id) or not _IDENTITY_RE.fullmatch(agent_id):
        return []
    sidecars = runtime_root / "goals" / goal_id / "post_writeback_hooks"
    if not sidecars.is_dir():
        return []
    pending: list[dict[str, Any]] = []
    for path in sorted(sidecars.iterdir()):
        if not path.is_file() or not _DISPATCH_RE.fullmatch(path.name):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        intent = _valid_sidecar_intent(
            value,
            dispatch_id=path.stem,
            goal_id=goal_id,
            agent_id=agent_id,
        )
        if intent is None:
            continue
        receipt_path = _receipt_path(runtime_root, goal_id, intent)
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                receipt = None
            if (
                isinstance(receipt, Mapping)
                and receipt.get("schema_version") == CONSUMPTION_RECEIPT_SCHEMA
                and receipt.get("intent_digest") == _canonical_digest(intent)
                and receipt.get("status") == "approval_pending"
            ):
                continue
        pending.append(intent)
    return pending


def periodic_report_pending_intent_interaction_hook(
    *, runtime_root: Path, goal_id: str, agent_id: str | None
) -> InteractionProjectionHookRegistration:
    normalized_agent_id = str(agent_id or "").strip()

    def produce() -> Mapping[str, Any]:
        intents = (
            pending_periodic_report_intents(
                runtime_root=runtime_root,
                goal_id=goal_id,
                agent_id=normalized_agent_id,
            )
            if normalized_agent_id
            else []
        )
        if not intents:
            return {
                "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
                "hook_id": HOOK_ID,
                "capability_id": CAPABILITY_ID,
                "phase": "interaction_projection",
                "status": "not_applicable",
                "projection_slot": None,
                "payload": None,
            }
        intent = intents[0]
        return {
            "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": HOOK_ID,
            "capability_id": CAPABILITY_ID,
            "phase": "interaction_projection",
            "status": "candidate",
            "projection_slot": "pending_capability_intent",
            "payload": {
                "schema_version": PENDING_INTENT_SCHEMA,
                "capability_id": CAPABILITY_ID,
                "intent_kind": PERIODIC_REPORT_TRIGGER_EVALUATION_INTENT,
                "idempotency_key": str(intent["idempotency_key"]),
                "intent_digest": _canonical_digest(intent),
                "goal_id": goal_id,
                "agent_id": normalized_agent_id,
                "state": "pending",
                "action_kind": "consume_periodic_report_intent",
                "action_summary": (
                    "Generate and validate the pending local periodic-report draft, "
                    "then create one exact-digest approval gate."
                ),
                "command": (
                    "loopx periodic-report consume-pending "
                    f"--goal-id {goal_id} --agent-id {normalized_agent_id} --execute"
                ),
                "generation_authorized": True,
                "external_delivery_authorized": False,
            },
        }

    return InteractionProjectionHookRegistration(
        hook_id=HOOK_ID,
        capability_id=CAPABILITY_ID,
        projection_slots=("pending_capability_intent",),
        requested_read_scope=("post_writeback_intent_journal",),
        producer=produce,
    )


def _progress_projection(
    *, registry_path: Path, goal_id: str, agent_id: str, completed_at: str
) -> dict[str, Any]:
    registry = read_json(registry_path)
    goal = find_registry_goal(registry, goal_id)
    if not isinstance(goal, Mapping):
        raise ValueError("periodic-report Goal is not registered")
    repo = Path(str(goal.get("repo") or "")).expanduser()
    state_path = resolve_state_file(repo, str(goal.get("state_file") or ""))
    if state_path is None or not state_path.is_file():
        raise ValueError("periodic-report active state is unavailable")
    parsed = parse_active_state_todos(
        state_path.read_text(encoding="utf-8"),
        goal=dict(goal),
        state_path=state_path,
        item_limit=None,
    )
    agent_summary = parsed.get("agent_todos")
    items = agent_summary.get("items") if isinstance(agent_summary, Mapping) else []
    stage_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))

    def not_after_stage(item: Mapping[str, Any]) -> bool:
        raw = str(item.get("completed_at") or item.get("updated_at") or "").strip()
        if not raw:
            return False
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")) <= stage_time
        except ValueError:
            return False

    done = [
        dict(item)
        for item in items or []
        if isinstance(item, Mapping)
        and item.get("status") == "done"
        and str(item.get("claimed_by") or "") == agent_id
        and not_after_stage(item)
    ]
    done.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    progress_items: list[dict[str, Any]] = []
    for index, item in enumerate(done[:6]):
        summary = " ".join(str(item.get("evidence") or item.get("note") or item.get("text") or "").split())
        title = " ".join(str(item.get("text") or "Completed project work").split())
        progress_items.append(
            {
                "item_id": f"completed_{index + 1}",
                "title": title[:240],
                "summary": summary[:360] or "Validated completion is durably recorded.",
                "content_kind": "outcome",
                "value_rank": 10 + index,
                "source_ref": f"todo:{item.get('todo_id')}",
            }
        )
    open_items = [
        dict(item)
        for item in items or []
        if isinstance(item, Mapping)
        and item.get("status") == "open"
        and str(item.get("claimed_by") or "") == agent_id
        and item.get("task_class") != "continuous_monitor"
        and item.get("action_kind")
        not in {
            "consume_periodic_report_intent",
            "repair_periodic_report_intent_consumption",
        }
    ]
    if open_items:
        next_item = open_items[0]
        progress_items.append(
            {
                "item_id": "next_action",
                "title": "Next action",
                "summary": " ".join(str(next_item.get("text") or "").split())[:360],
                "content_kind": "next_action",
                "value_rank": 90,
                "source_ref": f"todo:{next_item.get('todo_id')}",
            }
        )
    if not progress_items:
        raise ValueError("periodic-report has no public-safe progress items")
    return {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": goal_id,
        "observed_at": completed_at,
        "language": "zh-CN",
        "items": progress_items,
    }


def consume_pending_periodic_report_intent(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    agent_id: str,
    execute: bool,
) -> dict[str, Any]:
    intents = pending_periodic_report_intents(
        runtime_root=runtime_root, goal_id=goal_id, agent_id=agent_id
    )
    if not intents:
        return {
            "ok": True,
            "schema_version": CONSUMPTION_RECEIPT_SCHEMA,
            "status": "no_pending_intent",
            "external_writes_performed": False,
        }
    intent = intents[0]
    trigger = evaluate_periodic_report_trigger_evaluation_intent(intent)
    payload = intent["payload"]
    stage = payload["stage_completion"]
    completed_at = str(stage["completed_at"])
    end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    source = build_project_progress_periodic_report_source(
        _progress_projection(
            registry_path=registry_path,
            goal_id=goal_id,
            agent_id=agent_id,
            completed_at=completed_at,
        )
    )
    profile_ref = payload["profile_ref"]
    document = build_periodic_report_document(
        title="项目阶段周报",
        generated_at=completed_at,
        period_window={
            "start_at": (end - timedelta(days=7)).isoformat(),
            "end_at": end.isoformat(),
        },
        profile={
            "profile_id": profile_ref["profile_id"],
            "profile_version": profile_ref["profile_version"],
        },
        sources=[source],
        editorial={"language": "zh-CN"},
        trigger_receipt=trigger,
    )
    markdown = render_periodic_report_markdown(document)
    html = render_periodic_report_html(document)
    bundle = build_periodic_report_generation_bundle(
        document=document, artifacts=[markdown, html]
    )
    intent_digest = _canonical_digest(intent)
    generation = bundle["generation_receipt"]
    digest_suffix = str(generation["generation_id"]).split("_")[-1][:16]
    result: dict[str, Any] = {
        "ok": True,
        "schema_version": CONSUMPTION_RECEIPT_SCHEMA,
        "status": "preview",
        "goal_id": goal_id,
        "agent_id": agent_id,
        "intent_digest": intent_digest,
        "generation_receipt": generation,
        "content_checks": {
            "schema_version": "periodic_report_content_checks_v0",
            "document_normalized": True,
            "artifact_digests_verified": True,
            "html_self_contained": html.get("external_dependencies") == [],
            "matching_document_digest": (
                html.get("document_digest") == markdown.get("document_digest")
            ),
            "external_writes_performed": False,
        },
        "approval_scope": f"direction:action:periodic_report_{digest_suffix}",
        "external_writes_performed": False,
    }
    if not execute:
        return result

    receipt_path = _receipt_path(runtime_root, goal_id, intent)
    artifact_dir = receipt_path.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = artifact_dir / "report.md"
    html_path = artifact_dir / "report.html"
    markdown_path.write_text(str(markdown["content"]), encoding="utf-8")
    html_path.write_text(str(html["content"]), encoding="utf-8")
    gate = add_goal_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        role="user",
        text=(
            "[P0] Review and approve the exact local periodic-report draft "
            f"{generation['generation_id']} before any Miaoda publication or group delivery."
        ),
        note=(
            f"HTML digest {html['content_digest']}; Markdown digest "
            f"{markdown['content_digest']}; approval grants only the exact frozen payload."
        ),
        task_class="user_gate",
        action_kind="approve_periodic_report_payload",
        decision_scope=f"direction:action:periodic_report_{digest_suffix}",
        bound_agent=agent_id,
        blocks_agent=agent_id,
        agent_id=agent_id,
    )
    durable = {
        **result,
        "status": "approval_pending",
        "approval_todo_id": gate.get("todo_id"),
        "artifacts": {
            "html_path": str(html_path),
            "html_digest": html["content_digest"],
            "markdown_path": str(markdown_path),
            "markdown_digest": markdown["content_digest"],
        },
    }
    atomic_write_json(receipt_path, durable)
    return durable


__all__ = [
    "consume_pending_periodic_report_intent",
    "pending_periodic_report_intents",
    "periodic_report_pending_intent_interaction_hook",
]
