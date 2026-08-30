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
from .adapters import (
    build_periodic_report_document,
    build_periodic_report_source_result,
)
from .bindings import build_periodic_report_generation_bundle
from .core import _reject_raw_keys
from .post_writeback_hook import (
    PERIODIC_REPORT_POST_WRITEBACK_HOOK_ID,
    PERIODIC_REPORT_TRIGGER_EVALUATION_INTENT,
    evaluate_periodic_report_trigger_evaluation_intent,
)


PENDING_INTENT_SCHEMA = "pending_capability_intent_projection_v0"
CONSUMPTION_RECEIPT_SCHEMA = "periodic_report_intent_consumption_receipt_v0"
EDITORIAL_REQUEST_SCHEMA = "periodic_report_editorial_request_v0"
EDITORIAL_RESPONSE_SCHEMA = "periodic_report_editorial_response_v0"
HOOK_ID = "periodic_report.pending_intent"
CAPABILITY_ID = "periodic-report"
_DISPATCH_RE = re.compile(r"^pwh_[0-9a-f]{64}\.json$")
_IDENTITY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,127}$")
_CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_ANALYSIS_SECTION_CONTRACT = (
    ("overview", "全景判断"),
    ("problem_map", "问题版图"),
    ("causal_analysis", "重点因果下钻"),
    ("coverage_and_actions", "版本覆盖与处置"),
    ("next_actions", "下一步"),
)
_META_ACTION_KINDS = {
    "consume_periodic_report_intent",
    "repair_periodic_report_intent_consumption",
    "repair_periodic_report_editorial",
}
_SECTION_CONTENT_KINDS = {
    "overview": "decision",
    "problem_map": "risk",
    "causal_analysis": "progress",
    "coverage_and_actions": "outcome",
    "next_actions": "next_action",
}


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


def _editorial_request_path(
    runtime_root: Path, goal_id: str, intent: Mapping[str, Any]
) -> Path:
    return _receipt_path(runtime_root, goal_id, intent).parent / "editorial_request.json"


def _editorial_response_path(
    runtime_root: Path, goal_id: str, intent: Mapping[str, Any]
) -> Path:
    return _receipt_path(runtime_root, goal_id, intent).parent / "editorial.json"


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
                    "Prepare the typed report facts, author the required Chinese "
                    "analysis narrative, then freeze one locally validated draft."
                ),
                "command": (
                    "loopx periodic-report consume-pending "
                    f"--goal-id {goal_id} --agent-id {normalized_agent_id} --execute"
                ),
                "generation_authorized": True,
                "external_delivery_authorized": False,
                "agent_read_required": True,
            },
        }

    return InteractionProjectionHookRegistration(
        hook_id=HOOK_ID,
        capability_id=CAPABILITY_ID,
        projection_slots=("pending_capability_intent",),
        requested_read_scope=("post_writeback_intent_journal",),
        producer=produce,
    )


def _progress_facts(
    *, registry_path: Path, goal_id: str, agent_id: str, completed_at: str
) -> list[dict[str, Any]]:
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
    facts: list[dict[str, Any]] = []
    reportable_done = [
        item
        for item in done
        if str(item.get("action_kind") or "") not in _META_ACTION_KINDS
    ]
    for index, item in enumerate(reportable_done[:12]):
        summary = " ".join(
            str(
                item.get("evidence")
                or item.get("note")
                or item.get("text")
                or ""
            ).split()
        )
        title = " ".join(
            str(item.get("text") or "Completed project work").split()
        )
        facts.append(
            {
                "fact_id": f"completed_{index + 1}",
                "title": title[:500],
                "summary": summary[:1000]
                or "Validated completion is durably recorded.",
                "status": "done",
                "completed_at": str(
                    item.get("completed_at") or item.get("updated_at") or ""
                ),
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
        and str(item.get("action_kind") or "") not in _META_ACTION_KINDS
    ]
    if open_items:
        next_item = open_items[0]
        facts.append(
            {
                "fact_id": "next_action",
                "title": "Open successor",
                "summary": " ".join(str(next_item.get("text") or "").split())[:1000],
                "status": "open",
                "source_ref": f"todo:{next_item.get('todo_id')}",
            }
        )
    if not facts:
        raise ValueError("periodic-report has no public-safe progress items")
    return facts


def _build_editorial_request(
    *,
    intent: Mapping[str, Any],
    goal_id: str,
    agent_id: str,
    completed_at: str,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": EDITORIAL_REQUEST_SCHEMA,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "intent_digest": _canonical_digest(intent),
        "language": "zh-CN",
        "narrative_contract": {
            "contract_id": "analysis_from_overview_to_depth_v1",
            "section_order": [item[0] for item in _ANALYSIS_SECTION_CONTRACT],
            "section_titles": dict(_ANALYSIS_SECTION_CONTRACT),
            "requirements": [
                "Lead with the current overall judgment, not a work log.",
                "Map the complete problem space before selecting deep dives.",
                "Trace the highest-value findings to evidence-backed causes.",
                "Separate current-version coverage from historical evidence.",
                "Keep report-building work out of the analysis mainline.",
                "Write audience-facing Chinese while preserving necessary technical terms.",
            ],
        },
        "completed_at": completed_at,
        "facts": facts,
        "boundary": {
            "agent_authors_business_judgment": True,
            "cli_validates_and_freezes": True,
            "external_writes_performed": False,
        },
    }
    request["request_digest"] = _canonical_digest(request)
    return request


def _load_frozen_editorial_request(
    *,
    request_path: Path,
    intent_digest: str,
    goal_id: str,
    agent_id: str,
) -> dict[str, Any] | None:
    if not request_path.is_file():
        return None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("periodic-report editorial request is unreadable") from exc
    if not isinstance(request, Mapping):
        raise ValueError("periodic-report editorial request must be an object")
    request = dict(request)
    recorded_digest = request.pop("request_digest", None)
    if (
        request.get("schema_version") != EDITORIAL_REQUEST_SCHEMA
        or request.get("intent_digest") != intent_digest
        or request.get("goal_id") != goal_id
        or request.get("agent_id") != agent_id
        or recorded_digest != _canonical_digest(request)
    ):
        raise ValueError("periodic-report editorial request identity is invalid")
    request["request_digest"] = recorded_digest
    return request


def _chinese_density(value: object) -> float:
    text = str(value or "")
    chinese = len(_CHINESE_RE.findall(text))
    letters = sum(character.isalpha() for character in text)
    return chinese / max(letters, 1)


def _load_editorial_response(
    *, request: Mapping[str, Any], response_path: Path
) -> dict[str, Any]:
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("periodic-report editorial response is unreadable") from exc
    if not isinstance(response, Mapping):
        raise ValueError("periodic-report editorial response must be an object")
    _reject_raw_keys(response, "periodic-report editorial response")
    if (
        response.get("schema_version") != EDITORIAL_RESPONSE_SCHEMA
        or response.get("request_digest") != request.get("request_digest")
        or response.get("language") != "zh-CN"
    ):
        raise ValueError("periodic-report editorial response identity is invalid")
    title = " ".join(str(response.get("title") or "").split())
    if not title or _chinese_density(title) < 0.45:
        raise ValueError("periodic-report editorial title must be Chinese-first")
    raw_sections = response.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("periodic-report editorial sections must be a list")
    expected_ids = [item[0] for item in _ANALYSIS_SECTION_CONTRACT]
    section_ids = [
        str(section.get("section_id") or "")
        for section in raw_sections
        if isinstance(section, Mapping)
    ]
    if section_ids != expected_ids or len(raw_sections) != len(expected_ids):
        raise ValueError(
            "periodic-report editorial sections must follow the overview-to-depth contract"
        )
    allowed_refs = {
        str(fact.get("source_ref") or "")
        for fact in request.get("facts") or []
        if isinstance(fact, Mapping)
    }
    normalized_sections: list[dict[str, Any]] = []
    narrative_text: list[str] = [title]
    item_total = 0
    for order, ((section_id, expected_title), raw_section) in enumerate(
        zip(_ANALYSIS_SECTION_CONTRACT, raw_sections, strict=True), start=1
    ):
        if not isinstance(raw_section, Mapping):
            raise ValueError("periodic-report editorial section is invalid")
        section_title = " ".join(str(raw_section.get("title") or "").split())
        if section_title != expected_title:
            raise ValueError(
                f"periodic-report editorial section {section_id} title is invalid"
            )
        raw_items = raw_section.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError(
                f"periodic-report editorial section {section_id} must not be empty"
            )
        normalized_items: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                raise ValueError("periodic-report editorial item is invalid")
            item = dict(raw_item)
            if item.get("item_id") is not None:
                raise ValueError(
                    "periodic-report editorial item_id is assigned by the consumer"
                )
            if item.get("value_rank") is not None or item.get("content_kind") is not None:
                raise ValueError(
                    "periodic-report editorial ordering and semantics are assigned by the consumer"
                )
            source_ref = str(item.get("source_ref") or "")
            if source_ref not in allowed_refs:
                raise ValueError(
                    "periodic-report editorial item must reference a supplied fact"
                )
            item["item_id"] = f"{section_id}_{index + 1}"
            item["value_rank"] = order * 10 + index
            item["content_kind"] = _SECTION_CONTENT_KINDS[section_id]
            narrative_text.extend(
                [str(item.get("title") or ""), str(item.get("summary") or "")]
            )
            if section_id == "causal_analysis":
                details = item.get("details")
                if not isinstance(details, list) or len(details) < 2:
                    raise ValueError(
                        "causal analysis items require at least two evidence/boundary details"
                    )
            normalized_items.append(item)
            item_total += 1
        normalized_sections.append(
            {
                "section_id": section_id,
                "title": section_title,
                "order": order * 10,
                "items": normalized_items,
            }
        )
    if item_total < 6 or _chinese_density(" ".join(narrative_text)) < 0.45:
        raise ValueError(
            "periodic-report editorial response must contain a substantive Chinese narrative"
        )
    highlights = response.get("highlights")
    if not isinstance(highlights, list) or not 2 <= len(highlights) <= 4:
        raise ValueError("periodic-report editorial response requires 2-4 highlights")
    highlight_text = " ".join(
        f"{highlight.get('value', '')} {highlight.get('label', '')} "
        f"{highlight.get('detail', '')}"
        for highlight in highlights
        if isinstance(highlight, Mapping)
    )
    if _chinese_density(highlight_text) < 0.45:
        raise ValueError(
            "periodic-report editorial highlights must be Chinese-first"
        )
    return {
        "title": title,
        "editorial": {
            "language": "zh-CN",
            "kicker": str(response.get("kicker") or "阶段分析周报"),
            "period_label": str(response.get("period_label") or ""),
            "highlights": highlights,
        },
        "sections": normalized_sections,
    }


def _build_authored_source(
    authored: Mapping[str, Any], *, completed_at: str
) -> dict[str, Any]:
    return build_periodic_report_source_result(
        source_id="project_progress",
        source_kind="validated_project_progress",
        status="complete",
        observed_at=completed_at,
        sections=list(authored["sections"]),
        retryable=False,
    )


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
    facts = _progress_facts(
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=agent_id,
        completed_at=completed_at,
    )
    request_path = _editorial_request_path(runtime_root, goal_id, intent)
    response_path = _editorial_response_path(runtime_root, goal_id, intent)
    intent_digest = _canonical_digest(intent)
    editorial_request = _load_frozen_editorial_request(
        request_path=request_path,
        intent_digest=intent_digest,
        goal_id=goal_id,
        agent_id=agent_id,
    ) or _build_editorial_request(
        intent=intent,
        goal_id=goal_id,
        agent_id=agent_id,
        completed_at=completed_at,
        facts=facts,
    )
    if not response_path.is_file():
        result = {
            "ok": True,
            "schema_version": CONSUMPTION_RECEIPT_SCHEMA,
            "status": "editorial_required",
            "goal_id": goal_id,
            "agent_id": agent_id,
            "intent_digest": intent_digest,
            "agent_read_required": True,
            "editorial_contract": editorial_request["narrative_contract"],
            "editorial_request_path": str(request_path),
            "editorial_response_path": str(response_path),
            "external_writes_performed": False,
        }
        if execute:
            request_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(request_path, editorial_request)
        return result
    authored = _load_editorial_response(
        request=editorial_request,
        response_path=response_path,
    )
    source = _build_authored_source(authored, completed_at=completed_at)
    profile_ref = payload["profile_ref"]
    document = build_periodic_report_document(
        title=str(authored["title"]),
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
        editorial=dict(authored["editorial"]),
        trigger_receipt=trigger,
    )
    markdown = render_periodic_report_markdown(document)
    html = render_periodic_report_html(document)
    bundle = build_periodic_report_generation_bundle(
        document=document, artifacts=[markdown, html]
    )
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
            "language_is_zh_cn": True,
            "analysis_narrative_validated": True,
            "evidence_lineage_validated": True,
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
            "[P0] 审阅并批准精确冻结的中文阶段分析周报 "
            f"{generation['generation_id']}；批准前不得发布妙搭或发送群消息。"
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
