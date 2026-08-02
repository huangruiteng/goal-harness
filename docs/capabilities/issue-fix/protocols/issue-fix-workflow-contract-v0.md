# issue_fix_workflow_contract_v0

`issue_fix_workflow_contract_v0` ties the existing issue-fix surfaces into one
GitHub issue fix workflow. It is a product contract, not a new state store:
LoopX still uses metadata preview, intake packets, LoopX todos, caller-approved
repo branches, validation evidence, review packets, and explicit gates as the
source of truth.

## User Story

A user gives LoopX a public GitHub issue or PR signal and an approved local
repository context. LoopX should classify the issue, decompose the work into
owner/user gates and agent todos, prepare or claim an issue branch, run the
declared validation, and emit a PR-review-ready packet. LoopX must not read raw
issue bodies, raw comments, private repro material, create external comments,
open PRs, merge, publish, or run destructive git without an explicit gate.

## Workflow Stages

1. **Candidate preflight:** reconcile prior issue-fix domain state, all-state
   closing PR references, cross-references, and maintainer-comment metadata
   before projecting patch-planning work. Without source evidence, admission is
   `evidence_required`, the final route is absent, and the candidate is not
   runnable.
   Each PR evidence field is an issue-specific query receipt carrying
   `repo`, `issue_ref`, `query_scope`, `complete`, `truncated`, and `rows`.
   Each field accepts one receipt object, not a list:
   `numeric_pr_evidence.query_scope` is `issue_specific_all_states`,
   `semantic_pr_evidence.query_scope` is `issue_specific_current_revision`,
   and `maintainer_comment_evidence.query_scope` is
   `issue_specific_comment_metadata`.
   Empty rows are valid only for complete, non-truncated receipts. Every
   returned row must be parseable and issue-scoped; malformed rows invalidate
   the receipt rather than disappearing into a false negative.
   `--fetch-candidate-evidence` invokes the bounded built-in public GitHub
   collector; `--candidate-preflight-json` remains the provider-neutral
   adapter/test seam. Admission is `evidence_required`,
   `verification_required`, `admitted`, or `terminal`; only final admission
   exposes `proceed`, `reuse_existing_pr`, `comment_only`, or `skip`.
   Cross-references, closed PRs, and maintainer comments project typed
   successors instead of masquerading as final `comment_only`.
   `issue_fix_candidate_resolution_v0` is the single compact resolution input:
   every row must match current source evidence. PR resolution binds the exact
   head revision, and maintainer-comment resolution binds the comment
   `updatedAt` revision. A changed source therefore invalidates stale resolution.
   Comment content remains behind the provider-content gate and only its
   compact disposition may enter the resolution receipt.
2. **Metadata preview:** build `github_issue_metadata_preview_v0` from a public
   URL, compact reference, mocked metadata, or caller-approved metadata fetch.
   Allowed fields are repo, issue or PR number, state, title summary, labels,
   updated timestamp, author association, comment count, and permalink. Body,
   comment, timeline, event, raw, and provider response fields are gated.
3. **Intake classification:** build `issue_fix_intake_v0` with issue class,
   code-context route candidates, owner/user gate projections, and ordered
   agent todo candidates. The first screen must name `waiting_on`, top agent
   todo, top gate when present, and next safe action.
4. **Repository context:** build `issue_fix_repository_context_v0` from a
   pinned repository revision plus compact source refs. Current authoritative
   or verified repository evidence may ground change scope, reproduction, and
   validation. Stale memory and external experts remain advisory. The context
   projects missing reads but does not introduce another lifecycle state,
   authorize external writes, or override feasibility routing.
5. **Workflow plan:** build `issue_fix_workflow_plan_packet_v0` to compose the
   metadata preview, intake, branch dry-run, validation label, ordered LoopX
   todo writeback preview, resolution route candidates, gate preview, post-PR
   lifecycle monitor plan, and PR-review readiness blockers. This stage does
   not write todos. It writes only the candidate preflight receipt when a goal
   id or explicit ledger path is present; `--no-write-domain-state` keeps that
   receipt preview-only.
6. **Feasibility checkpoint:** build `issue_fix_feasibility_v0` from compact
   public-safe agent observations only after candidate preflight returns
   `proceed`. The decision must select exactly one
   `fix_pr`, `comment_only`, or `triage_only` route. `fix_pr` requires bounded
   scope plus named reproduction and validation surfaces; planned reproduction
   projects confirmation work before patch work. With a goal id, the compact
   decision writes issue-fix domain state by default.
7. **LoopX todo writeback:** for a non-proceed candidate, write only the
   successor or no-follow-up projected by candidate preflight. For `proceed`,
   write the single route-specific successor projected by feasibility. Preserve
   priority and planner order. User todos represent concrete external-write,
   private-material, merge, publish, or repository-policy gates.
8. **Caller repo branch:** use `issue_fix_caller_repo_branch_packet_v0` only
   after the caller provides an approved local git repo, base branch, issue
   branch policy, and validation command. Dry-run mode must not inspect the
   repo. Execute mode may inspect the approved repo and create or claim a
   `codex/` issue branch, but must refuse branch switches from dirty state.
9. **Validation:** record focused validation as pass/fail, exit code, and
   public-safe label. Validation stdout, stderr, local paths, and raw git output
   stay out of the packet. A validated fix should prove failing-before and
   passing-after evidence when that repro path is available. When delivery
   names a commit and reports `passed` or `completed`, writeback must resolve
   the declared repository revision and commit in the caller-approved checkout,
   prove commit ancestry, and retain `issue_fix_repository_commit_evidence_v0`
   with a matching repository fingerprint plus a full recoverable branch, tag,
   or remote ref. Missing or stale commit proof fails before state mutation;
   legacy unproved rows project as `unverified`, not publication-ready.
10. **PR review packet:** emit `issue_fix_pr_review_packet_v0` only when branch,
   validation, and repo-relative changed-file evidence are sufficient for human
   review. Its `issue_fix_pr_description_contract_v0` keeps the PR-review
   motivation/approach/change/validation/risk structure, requires a compact key
   code or pseudocode section for code changes, and requires a post-fix
   repository CLI or focused code/test reproduction when applicable. Optional
   infographics are limited to complex changes and cannot replace textual
   evidence. Issue-backed changes add one functional reference block after any
   semantic-preference rewrite: use `Fixes #N` for a complete fix targeting the
   default branch, and `Related to #N` for partial work. Use full syntax for
   every issue and verify closing references through GitHub
   `closingIssuesReferences`. The packet is review evidence, not external
   publication authority.
11. **PR lifecycle monitor:** after a PR exists, use
   `issue_fix_pr_lifecycle_monitor_v0` to project compact public PR state into
   exactly one of `runnable_successor`, `monitor_continuation`, `user_gate`, or
   `no_followup`. Terminal PR states such as `MERGED` and `CLOSED` take
   precedence over stale review metadata. Failed checks, requested changes, and
   stale merge states create runnable successors instead of `monitor_quiet_skip`.
   The command writes compact domain state by default when a `--goal-id` or
   `--ledger-path` is provided, and `--no-write-domain-state` keeps it
   preview-only. Persisted lifecycle state should carry an explicit public-safe
   `issue_ref`; numeric aliases such as `#123`, `issue_123`, and `issues/123`
   canonicalize to `issues_123` before writeback. Outcome projection applies
   the same rule to legacy rows, but must not infer the issue from a branch
   name, PR title, or prose. Its
   `issue_fix_pr_grouped_monitor_projection_v1` assigns each open PR to a
   repository lifecycle-state bucket. Materialize at most one
   `continuous_monitor` for each nonempty bucket, upsert/remove PR membership
   as state changes, and complete empty buckets. Never create one monitor per
   PR. Material PR work remains a one-shot advancement todo, and reviewer
   notifications remain one PR per message. `pr-lifecycle
   --execute-transition --goal-id <goal> --claimed-by <agent>` performs this
   reconciliation through the generic todo API; `--monitor-cadence` controls
   the schedule and defaults to `30m`. A quiet replay with unchanged bucket
   membership is idempotent. The monitor poll lane, rather than repeated PR
   lifecycle execution, owns later cadence advancement. The creating issue-fix
   agent remains the monitor's `claimed_by` owner across turns; another peer
   cannot update, retire, reopen, or poll that monitor without explicit Todo
   lifecycle authority.
   With a public PR URL, `--execute-transition` fetches compact public metadata
   automatically unless `--metadata-json` supplies a deterministic fixture.
11. **Gate handling:** surface concrete gates instead of silently blocking. Safe
   metadata-only triage, public-code search, and focused smoke drafting may
   continue when those gates do not cover the selected action.
12. **Outcome projection:** use `issue_fix_outcome_projection_v0` to derive one
   stable operator-facing case from the existing feasibility row, repository
   context, optional `issue_fix_delivery_evidence_input_v0`, and optional PR
   lifecycle row. This projection writes no source state and creates no parallel
   workflow state machine. It must keep unknown delivery evidence explicit,
   retain terminal outputs, derive only bounded public-safe `context_tags`, and
   remain consumable by generic projection sinks.
   Default goal-level Kanban sync derives an
   `issue_fix_outcome_collection_projection_v0` from all feasibility rows and
   explicitly linked lifecycle rows before upserting issue outcome cards.

## Public-Safe Boundary

Packets in this workflow must preserve these boundary flags:

- `issue_body_captured: false`
- `comment_bodies_captured: false`
- `response_payload_captured` or `response_payloads_captured: false`
- `local_paths_captured: false`
- `external_writes_performed: false`
- `destructive_git_used: false`

`private_repo_state_read` is `false` for preview, intake, fixtures, and
caller-repo dry-runs. It may be `true` only for caller-approved
`caller-repo-branch --execute`, and even then local paths, raw validation
output, raw git output, and credentials must not be recorded.

## Todo And Gate Shape

Issue-fix todo plans should be small and ordered. For a clear bounded bug, use
the minimum sufficient plan rather than management filler:

- `[P0] Reproduce or classify the issue from public metadata and approved code
  context.`
- `[P0] Patch the selected issue branch and rerun the caller-declared
  validation.`
- `[P1] Prepare the PR review packet with repo-relative changed files,
  validation labels, and remaining gates.`
- `[P2] Monitor the PR lifecycle and project CI, review, merge, or stale-branch
  changes into a successor, gate, continuation, or no-follow-up.`

When several todos have the same priority, planner order plus LoopX write order
is the tie-breaker. Do not infer a gate from prose alone: write it as a user
todo or operator gate with the concrete action it blocks.

Resolution routes must stay explicit. `fix_pr` is appropriate only when a
focused repro or validation plan is available. `comment_only` should produce a
public-safe maintainer comment packet but still needs an explicit external-write
gate. `triage_only` is valid when the issue lacks enough public evidence for a
useful patch or comment.

## Domain State

Issue-fix domain state is a project-local read model for compact decisions and
long-running monitors:

```text
.loopx/domain-state/<goal-id>/issue_fix/candidate-preflight.jsonl
.loopx/domain-state/<goal-id>/issue_fix/feasibility.jsonl
.loopx/domain-state/<goal-id>/issue_fix/pr-lifecycle.jsonl
```

Candidate preflight and feasibility rows are keyed by `repo` and `issue_ref`;
PR lifecycle rows are keyed by `repo` and `pr_ref`. They may store compact
observations, decisions, and fingerprints. Candidate preflight retains the
source receipts and prior-work disposition that decide whether feasibility is
legal. A feasibility observation may include one compact
`issue_fix_repository_context_v0` projection so its repository revision,
source refs, coverage, expert policy, and memory policy survive across turns.
Domain state must not store issue bodies, comment bodies, raw
provider payloads, raw logs, local paths, credentials, or destructive-git
output. Public packet validation remains the behavior contract; domain state
only keeps the agent from forgetting its latest compact decision.

## Ready Criteria

An issue-fix workflow is PR-review-ready only when all of these are true:

- metadata/intake preserved body-free and comment-free boundaries;
- accepted todos or gates were written to LoopX state, not left in chat;
- the issue branch is created or claimed inside the caller-approved repo;
- the declared validation ran and passed, or the packet clearly says review is
  not ready yet;
- changed files are repo-relative and bounded;
- no external issue comment, PR creation, merge, publish, production action, or
  destructive git action occurred.

`issue_fix_workflow_plan_packet_v0` also projects a
`repository_context_input_contract` with the accepted top-level/source fields
and a minimal example. Hosts should construct feasibility input from that
contract instead of copying the normalized `issue_fix_repository_context_v0`
output shape.

## Related Schemas

- `github_issue_metadata_preview_v0`
- `content_ops_issue_fix_metadata_preview_packet_v0`
- `content_ops_issue_fix_intake_packet_v0`
- `issue_fix_intake_v0`
- `issue_fix_workflow_plan_packet_v0`
- `issue_fix_candidate_preflight_v0`
- `issue_fix_candidate_resolution_v0`
- `issue_fix_candidate_successor_v0`
- `issue_fix_candidate_preflight_domain_state_projection_v0`
- `issue_fix_repository_context_input_v0`
- `issue_fix_repository_context_v0`
- `issue_fix_repository_context_effect_v0`
- `issue_fix_feasibility_v0`
- `issue_fix_feasibility_observation_v0`
- `issue_fix_feasibility_decision_v0`
- `issue_fix_feasibility_domain_state_projection_v0`
- `issue_fix_pr_lifecycle_monitor_v0`
- `issue_fix_pr_grouped_monitor_projection_v1`
- `issue_fix_pr_lifecycle_transition_v0`
- `issue_fix_pr_lifecycle_domain_state_projection_v0`
- `issue_fix_delivery_evidence_input_v0`
- `issue_fix_repository_commit_evidence_v0`
- `issue_fix_outcome_case_v0`
- `issue_fix_outcome_projection_v0`
- `issue_fix_outcome_collection_projection_v0`
- `loopx_todo_writeback_preview_v0`
- `issue_fix_caller_repo_branch_packet_v0`
- `issue_fix_validated_fix_artifact_v0`
- `issue_fix_pr_review_packet_v0`
