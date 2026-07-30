from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...control_plane.runtime.public_safety import public_safe_compact_text
from .metadata_preview import normalise_github_issue_reference

ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION = (
    "issue_fix_candidate_preflight_input_v0"
)
ISSUE_FIX_CANDIDATE_PREFLIGHT_SCHEMA_VERSION = "issue_fix_candidate_preflight_v0"
ISSUE_FIX_CANDIDATE_RESOLUTION_SCHEMA_VERSION = "issue_fix_candidate_resolution_v0"

_TERMINAL_DOMAIN_STATES = {"closed", "done", "resolved", "superseded", "terminal"}
_IMPLEMENTATION_RELATIONS = {"implementation", "implements", "fix_candidate"}
_PR_STATES = {"OPEN", "CLOSED", "MERGED"}
_REQUIRED_EVIDENCE_FIELDS = ("numeric_pr_evidence", "semantic_pr_evidence")
_EVIDENCE_QUERY_SCOPES = {
    "numeric_pr_evidence": "issue_specific_all_states",
    "semantic_pr_evidence": "issue_specific_current_revision",
}
_RESOLUTION_OUTCOMES = {
    "pr_revision": {"implementation", "not_implementation"},
    "closed_pr": {"retry_new_implementation", "comment_only", "skip"},
    "maintainer_comment": {"non_blocking", "comment_only", "skip"},
}


def candidate_preflight_input_contract() -> dict[str, Any]:
    """Describe the compact evidence and resolution contract."""

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
            "issue-specific complete non-truncated receipts with valid rows only"
        ),
        "semantic_evidence_rule": (
            "cross-references require issue_fix_candidate_resolution_v0 bound "
            "to the current revision"
        ),
        "decision_rule": "only admitted proceed may start a new implementation",
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


def _issue_refs(
    raw: object,
    *,
    field: str,
    repo: str,
    issue_ref: str,
) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise TypeError(f"{field} must be a list")
    refs: list[str] = []
    for value in raw:
        normalised = _normalise_issue_ref(repo, value)
        if normalised is None:
            raise ValueError(f"{field} contains an invalid issue reference")
        refs.append(normalised)
    if issue_ref not in refs:
        raise ValueError(f"{field} must include the receipt issue_ref")
    return refs


def _evidence_rows(
    raw: object,
    *,
    field: str,
    repo: str,
    issue_ref: str,
    semantic: bool,
) -> list[dict[str, Any]]:
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

    validated: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for index, raw_row in enumerate(rows):
        row_field = f"{field}.rows[{index}]"
        if not isinstance(raw_row, Mapping):
            raise TypeError(f"{row_field} must be an object")
        row_repo = str(raw_row.get("repo") or "").strip()
        if row_repo.casefold() != repo.casefold():
            raise ValueError(f"{row_field}.repo must match the receipt repo")
        pr_ref = _safe_ref(raw_row.get("pr_ref"), field=f"{row_field}.pr_ref")
        if pr_ref in seen_refs:
            raise ValueError(f"{field}.rows contains duplicate pr_ref {pr_ref}")
        seen_refs.add(pr_ref)
        state = str(raw_row.get("state") or "").strip().upper()
        if state not in _PR_STATES:
            raise ValueError(f"{row_field}.state must be OPEN, CLOSED, or MERGED")
        refs_field = "related_issue_refs" if semantic else "closing_issue_refs"
        _issue_refs(
            raw_row.get(refs_field),
            field=f"{row_field}.{refs_field}",
            repo=repo,
            issue_ref=issue_ref,
        )
        if semantic:
            relation = str(raw_row.get("relation") or "").strip().casefold()
            if relation not in _IMPLEMENTATION_RELATIONS:
                raise ValueError(
                    f"{row_field}.relation is not an implementation relation"
                )
            if raw_row.get("current_revision_verified") not in {None, False}:
                raise ValueError(
                    f"{row_field} cannot self-assert current revision verification"
                )
        revision = public_safe_compact_text(
            str(raw_row.get("revision") or ""), limit=120
        )
        if not revision:
            raise ValueError(f"{row_field}.revision is required")
        validated.append(
            {
                "pr_ref": pr_ref,
                "state": state,
                "url": public_safe_compact_text(
                    str(raw_row.get("url") or ""), limit=220
                ),
                "revision": revision or None,
                "evidence_kind": (
                    "semantic_candidate" if semantic else "numeric_closing_reference"
                ),
            }
        )
    return validated


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
    if not isinstance(maintainer_refs, Sequence) or isinstance(
        maintainer_refs, (str, bytes)
    ):
        raise TypeError("source_receipt.maintainer_comment_refs must be a list")
    refs = [
        _safe_ref(value, field="source_receipt.maintainer_comment_refs")
        for value in maintainer_refs
    ]
    if len(refs) != len(set(refs)):
        raise ValueError("source_receipt.maintainer_comment_refs must be unique")
    if raw.get("external_reads_performed") is not True:
        raise ValueError("source_receipt must record external_reads_performed=true")
    for field in (
        "external_writes_performed",
        "raw_provider_payload_captured",
        "credentials_captured",
    ):
        if raw.get(field) is not False:
            raise ValueError(f"source_receipt must keep {field}=false")
    return {
        "schema_version": _safe_ref(
            raw.get("schema_version"), field="source_receipt.schema_version"
        ),
        "provider": _safe_ref(raw.get("provider"), field="source_receipt.provider"),
        "observed_at": _safe_ref(
            raw.get("observed_at"), field="source_receipt.observed_at"
        ),
        "maintainer_comment_refs": refs,
        "external_reads_performed": True,
        "external_writes_performed": False,
        "raw_provider_payload_captured": False,
        "credentials_captured": False,
    }


def _resolution_rows(
    raw: object,
    *,
    repo: str,
    issue_ref: str,
    numeric: Sequence[Mapping[str, Any]],
    semantic: Sequence[Mapping[str, Any]],
    comment_refs: Sequence[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise TypeError("candidate_resolution must be an object")
    if raw.get("schema_version") != ISSUE_FIX_CANDIDATE_RESOLUTION_SCHEMA_VERSION:
        raise ValueError(
            "candidate_resolution schema_version must be "
            "issue_fix_candidate_resolution_v0"
        )
    resolution_repo = str(raw.get("repo") or "").strip()
    resolution_issue = _normalise_issue_ref(repo, raw.get("issue_ref"))
    if resolution_repo.casefold() != repo.casefold() or resolution_issue != issue_ref:
        raise ValueError("candidate_resolution must match repo and issue_ref")
    if raw.get("raw_content_captured") is not False:
        raise ValueError("candidate_resolution must keep raw_content_captured=false")
    rows = raw.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError("candidate_resolution.rows must be a list")

    numeric_by_ref = {str(row["pr_ref"]): row for row in numeric}
    semantic_by_ref = {str(row["pr_ref"]): row for row in semantic}
    comments = set(comment_refs)
    resolutions: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw_row in enumerate(rows):
        field = f"candidate_resolution.rows[{index}]"
        if not isinstance(raw_row, Mapping):
            raise TypeError(f"{field} must be an object")
        kind = str(raw_row.get("kind") or "").strip()
        if kind not in _RESOLUTION_OUTCOMES:
            raise ValueError(f"{field}.kind is unsupported")
        ref = _safe_ref(raw_row.get("ref"), field=f"{field}.ref")
        outcome = str(raw_row.get("outcome") or "").strip()
        if outcome not in _RESOLUTION_OUTCOMES[kind]:
            raise ValueError(f"{field}.outcome is invalid for {kind}")
        key = (kind, ref)
        if key in resolutions:
            raise ValueError(f"candidate_resolution contains duplicate {kind} {ref}")
        revision = public_safe_compact_text(
            str(raw_row.get("revision") or ""), limit=120
        )
        if kind == "pr_revision":
            source = semantic_by_ref.get(ref)
            if source is None:
                raise ValueError(f"{field} does not match semantic source evidence")
            if not revision or revision != source.get("revision"):
                raise ValueError(
                    f"{field}.revision must match the current source revision"
                )
        elif kind == "closed_pr":
            source = numeric_by_ref.get(ref) or semantic_by_ref.get(ref)
            if source is None or source.get("state") != "CLOSED":
                raise ValueError(f"{field} does not match a closed source PR")
            if revision != source.get("revision"):
                raise ValueError(
                    f"{field}.revision must match the current source revision"
                )
        elif ref not in comments:
            raise ValueError(f"{field} does not match a source maintainer comment")
        resolutions[key] = {
            "kind": kind,
            "ref": ref,
            "revision": revision or None,
            "outcome": outcome,
        }
    return resolutions


def _successor(
    *,
    action_kind: str,
    repo: str,
    issue_ref: str,
    reason_code: str,
    ref: str | None = None,
    revision: str | None = None,
    comment_refs: Sequence[str] = (),
) -> dict[str, Any]:
    parts = [repo, issue_ref, action_kind]
    if ref:
        parts.append(ref)
    if revision:
        parts.append(revision)
    return {
        "schema_version": "issue_fix_candidate_successor_v0",
        "action_kind": action_kind,
        "target_key": ":".join(parts),
        "reason_code": reason_code,
        "ref": ref,
        "revision": revision,
        "comment_refs": list(comment_refs),
    }


def build_issue_fix_candidate_preflight_packet(
    *,
    repo: str,
    issue_ref: str,
    input_payload: Mapping[str, Any] | None,
    generated_at: str | None,
) -> dict[str, Any]:
    """Reconcile source evidence and source-bound resolutions before execution."""

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
            f"candidate preflight input requires evidence fields: {missing_evidence}"
        )

    domain = _domain_projection(
        payload.get("domain_state"),
        repo=canonical_repo,
        issue_ref=canonical_issue_ref,
    )
    numeric: list[dict[str, Any]] = []
    semantic_candidates: list[dict[str, Any]] = []
    source_receipt: dict[str, Any] | None = None
    if configured:
        numeric = _evidence_rows(
            payload.get("numeric_pr_evidence"),
            field="numeric_pr_evidence",
            repo=canonical_repo,
            issue_ref=canonical_issue_ref,
            semantic=False,
        )
        semantic_candidates = _evidence_rows(
            payload.get("semantic_pr_evidence"),
            field="semantic_pr_evidence",
            repo=canonical_repo,
            issue_ref=canonical_issue_ref,
            semantic=True,
        )
        source_receipt = _source_receipt_projection(payload.get("source_receipt"))
    comment_refs = (
        list(source_receipt.get("maintainer_comment_refs") or [])
        if source_receipt
        else []
    )
    resolutions = _resolution_rows(
        payload.get("candidate_resolution"),
        repo=canonical_repo,
        issue_ref=canonical_issue_ref,
        numeric=numeric,
        semantic=semantic_candidates,
        comment_refs=comment_refs,
    )

    semantic: list[dict[str, Any]] = []
    successors: list[dict[str, Any]] = []
    for row in semantic_candidates:
        resolution = resolutions.get(("pr_revision", str(row["pr_ref"])))
        if resolution is None:
            successors.append(
                _successor(
                    action_kind="issue_fix_verify_pr_current_revision",
                    repo=canonical_repo,
                    issue_ref=canonical_issue_ref,
                    reason_code=(
                        "semantic_candidate_requires_current_revision_verification"
                    ),
                    ref=str(row["pr_ref"]),
                    revision=row.get("revision"),
                )
            )
        elif resolution["outcome"] == "implementation":
            semantic.append(
                {
                    **row,
                    "evidence_kind": "semantic_implementation",
                    "current_revision_verified": True,
                    "verified_revision": resolution["revision"],
                }
            )

    closed_prs = [row for row in numeric + semantic if row["state"] == "CLOSED"]
    for row in closed_prs:
        resolution = resolutions.get(("closed_pr", str(row["pr_ref"])))
        if resolution is None:
            successors.append(
                _successor(
                    action_kind="issue_fix_resolve_closed_candidate",
                    repo=canonical_repo,
                    issue_ref=canonical_issue_ref,
                    reason_code="closed_implementation_pr_requires_disposition",
                    ref=str(row["pr_ref"]),
                    revision=row.get("revision"),
                )
            )

    unresolved_comments = [
        ref for ref in comment_refs if ("maintainer_comment", ref) not in resolutions
    ]
    if unresolved_comments:
        successors.append(
            _successor(
                action_kind="issue_fix_read_maintainer_disposition",
                repo=canonical_repo,
                issue_ref=canonical_issue_ref,
                reason_code="maintainer_comment_requires_disposition",
                comment_refs=unresolved_comments,
            )
        )

    existing_prs = numeric + [
        row
        for row in semantic
        if row["pr_ref"] not in {item["pr_ref"] for item in numeric}
    ]
    terminal_outcomes = [
        resolution["outcome"]
        for resolution in resolutions.values()
        if resolution["outcome"] in {"comment_only", "skip"}
    ]
    retry_refs = {
        resolution["ref"]
        for resolution in resolutions.values()
        if resolution["kind"] == "closed_pr"
        and resolution["outcome"] == "retry_new_implementation"
    }
    effective_prs = [
        row
        for row in existing_prs
        if not (row["state"] == "CLOSED" and row["pr_ref"] in retry_refs)
    ]

    route: str | None
    reason_codes: list[str]
    admission_state: str
    if not configured:
        admission_state = "evidence_required"
        route = None
        reason_codes = ["candidate_evidence_required"]
        successors = [
            _successor(
                action_kind="issue_fix_collect_candidate_evidence",
                repo=canonical_repo,
                issue_ref=canonical_issue_ref,
                reason_code="candidate_evidence_required",
            )
        ]
    elif domain and domain["terminal"]:
        admission_state = "terminal"
        route = "skip"
        reason_codes = ["terminal_domain_state"]
        successors = []
    elif "skip" in terminal_outcomes:
        admission_state = "terminal"
        route = "skip"
        reason_codes = ["resolved_candidate_disposition_skip"]
        successors = []
    elif "comment_only" in terminal_outcomes:
        admission_state = "terminal"
        route = "comment_only"
        reason_codes = ["resolved_candidate_disposition_comment_only"]
        successors = []
    elif any(row["state"] == "MERGED" for row in effective_prs):
        admission_state = "terminal"
        route = "skip"
        reason_codes = ["merged_implementation_pr"]
        successors = []
    elif any(row["state"] == "OPEN" for row in effective_prs):
        admission_state = "admitted"
        route = "reuse_existing_pr"
        reason_codes = ["open_implementation_pr"]
        successors = []
    elif successors:
        admission_state = "verification_required"
        route = None
        reason_codes = list(dict.fromkeys(row["reason_code"] for row in successors))
    elif domain and domain["route"] == "comment_only":
        admission_state = "terminal"
        route = "comment_only"
        reason_codes = ["existing_comment_only_domain_route"]
    elif domain and domain["route"] == "triage_only":
        admission_state = "terminal"
        route = "skip"
        reason_codes = ["existing_triage_only_domain_route"]
    else:
        admission_state = "admitted"
        route = "proceed"
        reason_codes = ["no_prior_work_conflict"]

    recall = payload.get("agentic_recall_receipt")
    recall = recall if isinstance(recall, Mapping) else {}
    call_count = int(recall.get("call_count") or 0)
    max_calls = int(recall.get("max_calls") or 0)
    receipt_status = public_safe_compact_text(
        str(recall.get("status") or ""), limit=120
    )
    candidate_runnable = admission_state == "admitted" and route == "proceed"
    return {
        "ok": True,
        "schema_version": ISSUE_FIX_CANDIDATE_PREFLIGHT_SCHEMA_VERSION,
        "configured": configured,
        "generated_at": generated_at,
        "repo": canonical_repo,
        "issue_ref": canonical_issue_ref,
        "input_contract": candidate_preflight_input_contract(),
        "admission": {
            "state": admission_state,
            "evidence_complete": configured,
            "final_decision_available": route is not None,
            "successors": successors,
        },
        "decision": {
            "route": route,
            "candidate_runnable": candidate_runnable,
            "reason_codes": reason_codes,
            "existing_pr_refs": [row["pr_ref"] for row in effective_prs],
        },
        "evidence": {
            "domain_state_matched": domain is not None,
            "domain_route": domain.get("route") if domain else None,
            "numeric_pr_matches": numeric,
            "semantic_pr_matches": semantic,
            "semantic_pr_candidates_unverified": [
                row
                for row in semantic_candidates
                if ("pr_revision", str(row["pr_ref"])) not in resolutions
            ],
            "candidate_resolutions": list(resolutions.values()),
            "all_state_numeric_checked": configured,
            "semantic_implementation_checked": configured,
            "source_receipt": source_receipt,
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
