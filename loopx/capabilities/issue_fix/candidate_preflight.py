from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...control_plane.runtime.public_safety import public_safe_compact_text
from .metadata_preview import normalise_github_issue_reference

ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION = (
    "issue_fix_candidate_preflight_input_v0"
)
ISSUE_FIX_CANDIDATE_PREFLIGHT_SCHEMA_VERSION = "issue_fix_candidate_preflight_v0"

_TERMINAL_DOMAIN_STATES = {"closed", "done", "resolved", "superseded", "terminal"}
_IMPLEMENTATION_RELATIONS = {"implementation", "implements", "fix_candidate"}
_REQUIRED_EVIDENCE_FIELDS = ("numeric_pr_evidence", "semantic_pr_evidence")
_EVIDENCE_QUERY_SCOPES = {
    "numeric_pr_evidence": "issue_specific_all_states",
    "semantic_pr_evidence": "issue_specific_current_revision",
}


def candidate_preflight_input_contract() -> dict[str, Any]:
    """Describe the compact prior-work evidence required before implementation."""

    return {
        "schema_version": ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION,
        "required_before_implementation": True,
        "required_evidence_fields": list(_REQUIRED_EVIDENCE_FIELDS),
        "evidence_receipts": {
            field: {
                "cardinality": "one_receipt_object",
                "required_fields": [
                    "repo",
                    "issue_ref",
                    "query_scope",
                    "complete",
                    "truncated",
                    "rows",
                ],
                "query_scope": query_scope,
                "negative_result_rule": (
                    "rows may be empty only when complete=true and truncated=false"
                ),
            }
            for field, query_scope in _EVIDENCE_QUERY_SCOPES.items()
        },
        "evidence_receipt_rule": (
            "issue-specific complete non-truncated query receipts only"
        ),
        "semantic_evidence_rule": "current_revision_verified candidates only",
        "decision_rule": "only proceed may start a new implementation",
    }


def _safe_ref(value: object, *, field: str) -> str:
    compact = public_safe_compact_text(str(value or ""), limit=220)
    if not compact:
        raise ValueError(f"{field} must be a compact public-safe value")
    return compact


def _normalise_issue_ref(repo: str, value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(
            normalise_github_issue_reference(
                repo=repo,
                issue_ref=text,
                url=None,
            )["issue_ref"]
        )
    except ValueError:
        return None


def _matching_pr_rows(
    rows: object,
    *,
    repo: str,
    issue_ref: str,
    semantic: bool,
) -> list[dict[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    matches: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row_repo = str(raw.get("repo") or repo).strip()
        if row_repo.casefold() != repo.casefold():
            continue
        refs = raw.get("related_issue_refs") if semantic else raw.get(
            "closing_issue_refs"
        )
        if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
            continue
        normalised_refs = {
            ref
            for ref in (_normalise_issue_ref(repo, value) for value in refs)
            if ref
        }
        if issue_ref not in normalised_refs:
            continue
        if semantic:
            relation = str(raw.get("relation") or "").strip().casefold()
            if relation not in _IMPLEMENTATION_RELATIONS:
                continue
            if raw.get("current_revision_verified") is not True:
                continue
        matches.append(
            {
                "pr_ref": _safe_ref(raw.get("pr_ref"), field="pr_ref"),
                "state": str(raw.get("state") or "UNKNOWN").strip().upper(),
                "url": public_safe_compact_text(str(raw.get("url") or ""), limit=220),
                "evidence_kind": (
                    "semantic_implementation" if semantic else "numeric_closing_reference"
                ),
                "current_revision_verified": (
                    raw.get("current_revision_verified") is True if semantic else None
                ),
            }
        )
    return matches


def _unverified_semantic_rows(
    rows: object,
    *,
    repo: str,
    issue_ref: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    candidates: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row_repo = str(raw.get("repo") or repo).strip()
        if row_repo.casefold() != repo.casefold():
            continue
        refs = raw.get("related_issue_refs")
        if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
            continue
        normalised_refs = {
            ref
            for ref in (_normalise_issue_ref(repo, value) for value in refs)
            if ref
        }
        relation = str(raw.get("relation") or "").strip().casefold()
        if (
            issue_ref not in normalised_refs
            or relation not in _IMPLEMENTATION_RELATIONS
            or raw.get("current_revision_verified") is True
        ):
            continue
        candidates.append(
            {
                "pr_ref": _safe_ref(raw.get("pr_ref"), field="pr_ref"),
                "state": str(raw.get("state") or "UNKNOWN").strip().upper(),
                "url": public_safe_compact_text(str(raw.get("url") or ""), limit=220),
                "evidence_kind": "semantic_candidate_unverified",
                "current_revision_verified": False,
            }
        )
    return candidates


def _evidence_rows(
    raw: object,
    *,
    field: str,
    repo: str,
    issue_ref: str,
) -> Sequence[object]:
    if not isinstance(raw, Mapping):
        raise TypeError(
            f"{field} must be one evidence receipt object, not a list; "
            f"required query_scope is {_EVIDENCE_QUERY_SCOPES[field]}"
        )
    receipt_repo = str(raw.get("repo") or "").strip()
    receipt_issue = _normalise_issue_ref(repo, raw.get("issue_ref"))
    if receipt_repo.casefold() != repo.casefold() or receipt_issue != issue_ref:
        raise ValueError(f"{field} receipt must match repo and issue_ref")
    expected_scope = _EVIDENCE_QUERY_SCOPES[field]
    if raw.get("query_scope") != expected_scope:
        raise ValueError(f"{field} query_scope must be {expected_scope}")
    if raw.get("complete") is not True or raw.get("truncated") is not False:
        raise ValueError(f"{field} receipt must be complete and non-truncated")
    rows = raw.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError(f"{field}.rows must be a list")
    return rows


def _domain_projection(
    raw: object,
    *,
    repo: str,
    issue_ref: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    row_repo = str(raw.get("repo") or repo).strip()
    row_issue = _normalise_issue_ref(repo, raw.get("issue_ref"))
    if row_repo.casefold() != repo.casefold() or row_issue != issue_ref:
        return None
    decision = raw.get("decision")
    route = (
        str(decision.get("route") or "").strip()
        if isinstance(decision, Mapping)
        else str(raw.get("route") or "").strip()
    )
    state = str(raw.get("status") or raw.get("state") or "").strip().casefold()
    return {
        "route": route,
        "terminal": raw.get("terminal") is True or state in _TERMINAL_DOMAIN_STATES,
        "state": state or None,
    }


def _source_receipt_projection(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    maintainer_refs = raw.get("maintainer_comment_refs")
    refs = (
        [
            public_safe_compact_text(str(value or ""), limit=220)
            for value in maintainer_refs
        ]
        if isinstance(maintainer_refs, Sequence)
        and not isinstance(maintainer_refs, (str, bytes))
        else []
    )
    return {
        "schema_version": public_safe_compact_text(
            str(raw.get("schema_version") or ""), limit=120
        )
        or None,
        "provider": public_safe_compact_text(
            str(raw.get("provider") or ""), limit=120
        )
        or None,
        "observed_at": public_safe_compact_text(
            str(raw.get("observed_at") or ""), limit=120
        )
        or None,
        "maintainer_comment_refs": [ref for ref in refs if ref][:100],
        "external_reads_performed": raw.get("external_reads_performed") is True,
        "external_writes_performed": raw.get("external_writes_performed") is True,
        "raw_provider_payload_captured": (
            raw.get("raw_provider_payload_captured") is True
        ),
        "credentials_captured": raw.get("credentials_captured") is True,
    }


def build_issue_fix_candidate_preflight_packet(
    *,
    repo: str,
    issue_ref: str,
    input_payload: Mapping[str, Any] | None,
    generated_at: str | None,
) -> dict[str, Any]:
    """Reconcile compact prior work before an issue becomes runnable.

    The caller owns provider queries. This seam performs no network, memory, or
    repository reads and treats semantic PR evidence as actionable only after
    current-revision verification.
    """

    reference = normalise_github_issue_reference(
        repo=repo,
        issue_ref=issue_ref,
        url=None,
    )
    canonical_repo = str(reference["repo"])
    canonical_issue_ref = str(reference["issue_ref"])
    configured = input_payload is not None
    payload = input_payload or {}
    if configured and payload.get("schema_version") != (
        ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION
    ):
        raise ValueError(
            "candidate preflight input schema_version must be "
            "issue_fix_candidate_preflight_input_v0"
        )
    missing_evidence = [
        field for field in _REQUIRED_EVIDENCE_FIELDS if field not in payload
    ]
    if configured and missing_evidence:
        raise ValueError(
            "candidate preflight input requires evidence fields: "
            f"{missing_evidence}"
        )

    domain = _domain_projection(
        payload.get("domain_state"),
        repo=canonical_repo,
        issue_ref=canonical_issue_ref,
    )
    numeric: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    unverified_semantic: list[dict[str, Any]] = []
    if configured:
        numeric = _matching_pr_rows(
            _evidence_rows(
                payload.get("numeric_pr_evidence"),
                field="numeric_pr_evidence",
                repo=canonical_repo,
                issue_ref=canonical_issue_ref,
            ),
            repo=canonical_repo,
            issue_ref=canonical_issue_ref,
            semantic=False,
        )
        semantic = _matching_pr_rows(
            _evidence_rows(
                payload.get("semantic_pr_evidence"),
                field="semantic_pr_evidence",
                repo=canonical_repo,
                issue_ref=canonical_issue_ref,
            ),
            repo=canonical_repo,
            issue_ref=canonical_issue_ref,
            semantic=True,
        )
        unverified_semantic = _unverified_semantic_rows(
            payload.get("semantic_pr_evidence", {}).get("rows"),
            repo=canonical_repo,
            issue_ref=canonical_issue_ref,
        )
    existing_prs = numeric + [
        row for row in semantic if row["pr_ref"] not in {item["pr_ref"] for item in numeric}
    ]

    route = "proceed"
    reason_codes: list[str] = []
    if domain and domain["terminal"]:
        route = "skip"
        reason_codes.append("terminal_domain_state")
    else:
        open_prs = [row for row in existing_prs if row["state"] == "OPEN"]
        merged_prs = [row for row in existing_prs if row["state"] == "MERGED"]
        closed_prs = [row for row in existing_prs if row["state"] == "CLOSED"]
        if merged_prs:
            route = "skip"
            reason_codes.append("merged_implementation_pr")
        elif open_prs:
            route = "reuse_existing_pr"
            reason_codes.append("open_implementation_pr")
        elif closed_prs:
            route = "comment_only"
            reason_codes.append("closed_implementation_pr_requires_disposition")
        elif unverified_semantic:
            route = "comment_only"
            reason_codes.append(
                "semantic_candidate_requires_current_revision_verification"
            )
        elif (
            domain
            and domain["route"] == "comment_only"
            and isinstance(payload.get("source_receipt"), Mapping)
            and payload["source_receipt"].get("maintainer_comment_refs")
        ):
            route = "comment_only"
            reason_codes.append("maintainer_comment_requires_disposition")
        elif domain and domain["route"] == "comment_only":
            route = "comment_only"
            reason_codes.append("existing_comment_only_domain_route")
        elif domain and domain["route"] == "triage_only":
            route = "skip"
            reason_codes.append("existing_triage_only_domain_route")
        else:
            reason_codes.append("no_prior_work_conflict")

    recall = payload.get("agentic_recall_receipt")
    recall = recall if isinstance(recall, Mapping) else {}
    call_count = int(recall.get("call_count") or 0)
    max_calls = int(recall.get("max_calls") or 0)
    receipt_status = public_safe_compact_text(
        str(recall.get("status") or ""), limit=120
    )
    candidate_runnable = route == "proceed"
    return {
        "ok": True,
        "schema_version": ISSUE_FIX_CANDIDATE_PREFLIGHT_SCHEMA_VERSION,
        "configured": configured,
        "generated_at": generated_at,
        "repo": canonical_repo,
        "issue_ref": canonical_issue_ref,
        "input_contract": candidate_preflight_input_contract(),
        "decision": {
            "route": route,
            "candidate_runnable": candidate_runnable,
            "reason_codes": reason_codes,
            "existing_pr_refs": [row["pr_ref"] for row in existing_prs],
        },
        "evidence": {
            "domain_state_matched": domain is not None,
            "domain_route": domain.get("route") if domain else None,
            "numeric_pr_matches": numeric,
            "semantic_pr_matches": semantic,
            "semantic_pr_candidates_unverified": unverified_semantic,
            "all_state_numeric_checked": configured,
            "semantic_implementation_checked": configured,
            "source_receipt": _source_receipt_projection(
                payload.get("source_receipt")
            ),
        },
        "agentic_recall": {
            "receipt_status": receipt_status or None,
            "call_count": call_count,
            "max_calls": max_calls,
            "action": (
                "preserve_existing_receipt"
                if not candidate_runnable and receipt_status
                else "not_opened_by_preflight"
            ),
            "provider_calls_performed": 0,
            "raw_memory_captured": False,
        },
        "domain_state_projection": {
            "schema_version": "issue_fix_candidate_preflight_domain_state_projection_v0",
            "domain_pack": "issue_fix",
            "stream": "candidate-preflight",
            "key": {
                "repo": canonical_repo,
                "issue_ref": canonical_issue_ref,
            },
            "write_performed": False,
        },
        "provider_neutral": True,
        "external_reads_performed": False,
        "external_writes_performed": False,
        "raw_provider_payload_captured": False,
    }
