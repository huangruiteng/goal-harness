from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from collections.abc import Sequence

from ...repository_identity import normalize_repository_identity
from ...control_plane.runtime.time import now_utc_iso
from ...todos import add_goal_todo
from .metadata_preview import normalise_github_issue_reference
from .workflow_plan import build_issue_fix_workflow_plan_packet

ISSUE_FIX_PORTFOLIO_PACKET_SCHEMA_VERSION = "issue_fix_portfolio_packet_v0"
PORTFOLIO_ADVANCEMENT_ACTION_KIND = "issue_fix_portfolio_advancement"
PORTFOLIO_EXECUTION_MODEL = "sequential_pr_ready_advance"

_BOUNDARY_FLAG_FIELDS = (
    "issue_body_captured",
    "comment_bodies_captured",
    "response_payloads_captured",
    "raw_logs_captured",
    "local_paths_captured",
    "private_repo_state_read",
)


def _portfolio_advance_todo_text(
    repo_label: str,
    issue_label: str,
    permalink: str | None,
) -> str:
    link = f" ({permalink})" if permalink else ""
    return (
        f"[P0] Advance issue-fix for {repo_label} {issue_label}{link}: run "
        "`loopx issue-fix workflow-plan` and `loopx issue-fix feasibility` for this "
        "issue, pursue the selected route (fix_pr, comment_only, or triage_only), and "
        "mark this todo done once the PR is created or the route reaches a terminal "
        "disposition so the next portfolio issue can resume."
    )


def _resolve_candidate_reference(candidate: Mapping[str, Any]) -> dict[str, Any]:
    url = str(candidate.get("url") or "").strip() or None
    repo = str(candidate.get("repo") or "").strip() or None
    issue_number = candidate.get("issue_number")
    if url:
        return normalise_github_issue_reference(url=url)
    if repo and issue_number is not None:
        digits = str(issue_number).strip()
        if not digits.isdigit():
            raise ValueError(
                "portfolio candidate issue_number must be a positive integer"
            )
        constructed = f"https://github.com/{repo}/issues/{digits}"
        return normalise_github_issue_reference(url=constructed)
    raise ValueError(
        "portfolio candidate requires either a --url or a --repo plus an issue number"
    )


def _repo_url_from_reference(reference: Mapping[str, Any]) -> str | None:
    permalink = reference.get("permalink")
    if permalink:
        for sep in ("/issues/", "/pull/"):
            idx = permalink.find(sep)
            if idx > 0:
                return str(permalink[:idx])
    repo = reference.get("repo")
    if repo:
        return f"https://github.com/{repo}"
    return None


def _boundary_flags_from_single_plan(single_plan: Mapping[str, Any]) -> dict[str, bool]:
    return {field: bool(single_plan.get(field)) for field in _BOUNDARY_FLAG_FIELDS}


def _merge_boundary_flags(flag_sets: list[Mapping[str, Any]]) -> dict[str, bool]:
    merged = {field: False for field in _BOUNDARY_FLAG_FIELDS}
    for flags in flag_sets:
        for field in _BOUNDARY_FLAG_FIELDS:
            if flags.get(field):
                merged[field] = True
    return merged


def build_issue_fix_portfolio_packet(
    *,
    candidate_inputs: Sequence[Mapping[str, Any]],
    fetch_metadata: bool = False,
    fetch_timeout_seconds: int = 10,
    repo_path: str | None = None,
    base_branch: str = "main",
    validation_label: str = "caller-declared validation",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a public-safe sequential portfolio plan without writing state.

    Each candidate reuses the single-issue workflow plan builder for body-free
    metadata intake and branch grounding. The portfolio emits compact candidate
    rows plus a chained todo preview: issue 1 is open and runnable, issues 2..N
    are deferred behind ``todo_done:<previous issue todo id>`` so the heartbeat
    advances them one at a time after the previous issue reaches a PR-ready (or
    terminal) disposition.
    """

    timestamp = generated_at or now_utc_iso()
    if not candidate_inputs:
        raise ValueError("portfolio-plan requires at least one candidate issue")

    candidates: list[dict[str, Any]] = []
    chain: list[dict[str, Any]] = []
    boundary_flag_sets: list[Mapping[str, Any]] = []

    for index, raw_candidate in enumerate(candidate_inputs):
        reference = _resolve_candidate_reference(raw_candidate)
        repo_label = str(reference["repo"])
        issue_label = str(reference["issue_ref"])
        permalink = reference.get("permalink")
        order = index + 1

        single_plan = build_issue_fix_workflow_plan_packet(
            repo=repo_label,
            issue_ref=issue_label,
            url=permalink,
            provider_payload=None,
            fetch_metadata=fetch_metadata,
            fetch_timeout_seconds=fetch_timeout_seconds,
            repo_path=repo_path,
            base_branch=base_branch,
            validation_label=validation_label,
            generated_at=timestamp,
        )
        issue_signal = single_plan.get("issue_signal")
        if not isinstance(issue_signal, Mapping):
            issue_signal = {}
        branch_plan = single_plan.get("branch_plan")
        branch_status = (
            branch_plan.get("status") if isinstance(branch_plan, Mapping) else None
        )
        single_boundary = _boundary_flags_from_single_plan(single_plan)
        boundary_flag_sets.append(single_boundary)

        task_repository = None
        repo_url = _repo_url_from_reference(reference)
        if repo_url:
            task_repository = normalize_repository_identity(repo_url)

        candidates.append(
            {
                "order": order,
                "repo": repo_label,
                "issue_ref": issue_label,
                "number": reference.get("number"),
                "permalink": permalink,
                "kind": reference.get("kind"),
                "state": issue_signal.get("state"),
                "labels": list(issue_signal.get("labels") or []),
                "branch_plan_status": branch_status,
                "validation_label": validation_label,
                "task_repository": task_repository,
                "single_issue_workflow_plan_available": True,
                "boundary_flags": single_boundary,
            }
        )

        is_first = order == 1
        chain.append(
            {
                "order": order,
                "issue_ref": issue_label,
                "repo": repo_label,
                "status": "open" if is_first else "deferred",
                "action_kind": PORTFOLIO_ADVANCEMENT_ACTION_KIND,
                "task_repository": task_repository,
                "todo_text": _portfolio_advance_todo_text(
                    repo_label, issue_label, permalink
                ),
                "resume_depends_on_order": None if is_first else order - 1,
                "resume_when_pattern": (
                    None
                    if is_first
                    else "todo_done:{previous_issue_todo_id}"
                ),
                "claimed_by_first": is_first,
            }
        )

    merged_boundary = _merge_boundary_flags(boundary_flag_sets)
    return {
        "ok": True,
        "schema_version": ISSUE_FIX_PORTFOLIO_PACKET_SCHEMA_VERSION,
        "mode": "issue-fix-portfolio-plan",
        "generated_at": timestamp,
        "execution_model": PORTFOLIO_EXECUTION_MODEL,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "chain": chain,
        "boundary_flags": merged_boundary,
        "external_reads_performed": bool(fetch_metadata),
        "external_writes_performed": False,
        "todo_write_performed": False,
        "next_safe_action": (
            "Apply with --execute --goal-id --agent-id to write the chained "
            "advancement todos; the heartbeat then advances one issue at a time."
        ),
    }


def apply_issue_fix_portfolio(
    *,
    registry_path: Path,
    goal_id: str,
    agent_id: str,
    candidates: Sequence[Mapping[str, Any]],
    required_write_scopes: list[str] | None = None,
    project: Path | None = None,
) -> dict[str, Any]:
    """Write the chained portfolio advancement todos for a sequential run.

    Issue 1 is written open and claimed by ``agent_id`` so it is immediately
    runnable. Issues 2..N are written deferred behind
    ``resume_when=todo_done:<previous issue todo id>``. When the agent marks an
    issue's todo done (PR created or route terminal), the next issue's
    ``todo_done`` resume condition becomes satisfied and the heartbeat advances
    it through the existing deferred-resume frontier.
    """

    if not candidates:
        raise ValueError("portfolio apply requires at least one candidate issue")
    if not agent_id:
        raise ValueError("portfolio apply requires a registered --agent-id")

    applied: list[dict[str, Any]] = []
    previous_todo_id: str | None = None
    boundary_flags = {field: False for field in _BOUNDARY_FLAG_FIELDS}

    for index, candidate in enumerate(candidates):
        order = index + 1
        is_first = order == 1
        resume_when = None if is_first else f"todo_done:{previous_todo_id}"
        status = "open" if is_first else "deferred"
        task_repository = candidate.get("task_repository")
        todo_text = str(candidate.get("todo_text") or "")
        if not todo_text:
            todo_text = _portfolio_advance_todo_text(
                repo_label=str(candidate.get("repo") or ""),
                issue_label=str(candidate.get("issue_ref") or ""),
                permalink=candidate.get("permalink"),
            )

        write_result = add_goal_todo(
            registry_path=registry_path,
            goal_id=goal_id,
            role="agent",
            text=todo_text,
            status=status,
            task_class="advancement_task",
            action_kind=PORTFOLIO_ADVANCEMENT_ACTION_KIND,
            task_repository=task_repository,
            required_write_scopes=required_write_scopes,
            claimed_by=agent_id if is_first else None,
            resume_when=resume_when,
            project=project,
            dry_run=False,
        )
        todo_id = str(write_result.get("todo_id") or "")
        if not todo_id:
            raise ValueError(
                f"portfolio apply did not receive a todo_id for order {order}"
            )

        applied.append(
            {
                "order": order,
                "issue_ref": candidate.get("issue_ref"),
                "repo": candidate.get("repo"),
                "todo_id": todo_id,
                "status": write_result.get("status"),
                "resume_when": write_result.get("resume_when"),
                "resume_depends_on_order": None if is_first else order - 1,
                "claimed_by": write_result.get("claimed_by"),
                "action_kind": write_result.get("action_kind"),
                "task_repository": write_result.get("task_repository"),
            }
        )
        previous_todo_id = todo_id

    return {
        "ok": True,
        "schema_version": ISSUE_FIX_PORTFOLIO_PACKET_SCHEMA_VERSION,
        "mode": "issue-fix-portfolio-apply",
        "execution_model": PORTFOLIO_EXECUTION_MODEL,
        "applied_todo_count": len(applied),
        "applied_todos": applied,
        "boundary_flags": boundary_flags,
        "external_writes_performed": False,
        "todo_write_performed": True,
        "next_safe_action": (
            "Run `loopx status` and let the host heartbeat advance issue 1; mark "
            "each issue's todo done once its PR is created or its route is terminal."
        ),
    }


def render_issue_fix_portfolio_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# LoopX Issue Fix Portfolio Plan",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- schema_version: `{payload.get('schema_version')}`",
        f"- execution_model: `{payload.get('execution_model')}`",
        f"- candidate_count: `{payload.get('candidate_count', payload.get('applied_todo_count'))}`",
        f"- todo_write_performed: `{payload.get('todo_write_performed')}`",
        f"- external_writes_performed: `{payload.get('external_writes_performed')}`",
    ]
    boundary = payload.get("boundary_flags")
    if isinstance(boundary, Mapping):
        lines.append("")
        lines.append("## Boundary")
        for field in _BOUNDARY_FLAG_FIELDS:
            lines.append(f"- {field}: `{boundary.get(field)}`")

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        lines.append("")
        lines.append("## Candidates")
        lines.append("")
        lines.append("| order | repo | issue_ref | number | kind | branch_plan |")
        lines.append("|-------|------|-----------|--------|------|-------------|")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            lines.append(
                f"| {candidate.get('order')} | `{candidate.get('repo')}` | "
                f"`{candidate.get('issue_ref')}` | {candidate.get('number')} | "
                f"`{candidate.get('kind')}` | `{candidate.get('branch_plan_status')}` |"
            )

    chain = payload.get("chain")
    if isinstance(chain, list) and chain:
        lines.append("")
        lines.append("## Chain (sequential, PR-ready advance)")
        lines.append("")
        for entry in chain:
            if not isinstance(entry, Mapping):
                continue
            lines.append(
                f"- order {entry.get('order')} `{entry.get('issue_ref')}`: "
                f"status=`{entry.get('status')}`, "
                f"resume_depends_on_order=`{entry.get('resume_depends_on_order')}`"
            )

    applied = payload.get("applied_todos")
    if isinstance(applied, list) and applied:
        lines.append("")
        lines.append("## Applied Todos")
        lines.append("")
        lines.append(
            "| order | issue_ref | todo_id | status | resume_when | claimed_by |"
        )
        lines.append("|-------|-----------|---------|--------|-------------|-----------|")
        for entry in applied:
            if not isinstance(entry, Mapping):
                continue
            lines.append(
                f"| {entry.get('order')} | `{entry.get('issue_ref')}` | "
                f"`{entry.get('todo_id')}` | `{entry.get('status')}` | "
                f"`{entry.get('resume_when')}` | `{entry.get('claimed_by')}` |"
            )

    next_action = payload.get("next_safe_action")
    if next_action:
        lines.append("")
        lines.append("## Next Safe Action")
        lines.append("")
        lines.append(str(next_action))
    return "\n".join(lines) + "\n"
