---
name: loopx-pr-review
description: Use when the visible request starts with `/loopx-pr-review` or asks LoopX to review a repository PR queue by time window, open/unmerged status, merged/closed status, or current-day PR activity. Run `loopx pr-review` first, preserve the full packet contract, then read PR evidence and produce detailed per-PR reviews with the five required blocks, exact-head key-code explanations, code-volume necessity, and concrete simplification analysis. For an open PR, publish validated actionable findings by default and submit REQUEST_CHANGES when blockers are found; keep review local only when the user explicitly asks for local-only or dry-run output. Use `loopx-pr-merge` for approval, merge, self-merge, or admin-bypass actions.
---

# LoopX PR Review

## Routing Boundary

Use this skill for `/loopx-pr-review` and for requests such as:

- review today's open and merged PRs;
- list the unmerged PR queue and take me through review;
- review PRs since a timestamp;
- show the merged PRs that need post-merge audit.

This skill owns evidence-backed review publication for open PRs. After the
review is complete:

- submit a formal `REQUEST_CHANGES` review when one or more validated blocking
  findings remain;
- otherwise post the review findings or no-blocker result as a normal PR
  review/comment, unless approval was explicitly requested;
- keep the workflow read-only only when the user explicitly says `local-only`,
  `dry-run`, `不要评论`, `不要提交 review`, or equivalent;
- route approval, merge, self-merge, and admin-bypass actions to
  `loopx-pr-merge`.

Do not leave actionable blockers only in chat. A plain PR comment is not an
adequate substitute for `REQUEST_CHANGES` when the evidence-based verdict is
that the open PR should not merge.

## First Command

Run the LoopX CLI before manual GitHub calls:

```bash
loopx --format json pr-review --state all
```

Translate user filters only into these CLI options:

- `--repo owner/repo` for an explicit repository;
- `--since ISO` for an explicit time window;
- `--state open`, `--state merged`, or `--state all` for state filters.
- `--limit N` when the user explicitly requests a bounded batch.

Default to the current `gh` repository, `--state all`, and the CLI's normal
100-PR group limit. Treat words like
`today`, `open`, `closed`, or `merged` as review-queue filters. They do not
mean "stats only" unless the user explicitly says `只统计`, `只列出`,
`stats only`, `list only`, `不要 review`, or `不用分析`.

## Preserve The Packet

Keep these fields in model context from the first CLI packet:

- `agent_response_contract`;
- `result_completeness`;
- `review_groups`;
- `pull_requests[].review_template`;
- `pull_requests[].evidence_commands`.

Do not pipe the first packet through `jq` or another projection that only keeps
`.summary`, `.review_sequence`, or a table. If a compact view is useful, save
the full JSON first and then print the contract-bearing fields:

```bash
packet="$(mktemp)"
loopx --format json pr-review --state all [--repo owner/repo] [--since ISO] > "$packet"
python3 - "$packet" <<'PY'
import json
import sys
p = json.load(open(sys.argv[1]))
print(json.dumps({
  "agent_response_contract": p.get("agent_response_contract"),
  "result_completeness": p.get("result_completeness"),
  "review_groups": p.get("review_groups"),
  "pull_requests": [
    {
      "number": pr.get("number"),
      "title": pr.get("title"),
      "review_template": pr.get("review_template"),
      "evidence_commands": pr.get("evidence_commands"),
    }
    for pr in p.get("pull_requests", [])
  ],
}, ensure_ascii=False, indent=2))
PY
rm -f "$packet"
```

## Require Complete Exhaustive Queues

When the user asks for `all`, `every`, `全部`, `每个`, or an exhaustive time
window, do not start reviewing until `result_completeness.complete=true`.
When it is false, rerun the same first command with
`--limit <result_completeness.recommended_limit>`. Repeat until complete,
preserving the latest full packet as the queue source of truth. Never infer
completeness from `summary.total_pr_count`, a count equal to the limit, or the
absence of a pagination error.

## Autonomous Monitor Route

For a recurring PR monitor, use the built-in `pull-request-review` capability
instead of inferring queue state from monitor timing or a remembered chat
summary:

```bash
loopx --format json pr-review --repo owner/repo --state open \
  --autonomous-observation \
  [--previous-observation-json previous.json] \
  [--handled-exact-head NUMBER@HEAD_OID]
```

Treat `autonomous_review.observation_state` literally:

- `not_observed` means the complete queue was not obtained. Preserve the prior
  fingerprint, retry later, and never report this as unchanged.
- `observed_unchanged` means a complete exact fingerprint matched. Do not
  recreate the same review Todo. When an explicit handled cursor is present,
  the packet may expose the next unhandled backlog candidate without changing
  this observation state. Deduplicate by exact target key while an unhandled
  candidate remains selected across polls.
- `material_transition` may expose one exact-head candidate. Materialize it
  only through normal Todo authority, then run this review skill for deep
  evidence and publication.

The candidate is a scheduling preview, not permission to review, comment,
approve, push, or merge. This skill still owns evidence-backed review
publication; `loopx-pr-merge` still owns approval and merge policy.

After publishing and reading back the formal review result for the candidate's
exact head, pass `--handled-exact-head NUMBER@HEAD_OID` on the next complete
poll. Never infer handled state from candidate selection alone. Preserve the
returned `handled_exact_heads` through later observation packets; a changed
head must be reviewed again.

## Review Flow

Review `review_groups.unmerged` first, then `review_groups.merged`. A queue
table can be a short preface, but stopping at the table is incomplete for
`/loopx-pr-review`.

For each selected PR, read the PR evidence before writing the review. Prefer the
packet's `evidence_commands`; equivalent targeted `gh pr view`, `gh pr diff
--name-only`, and `gh pr diff --patch` commands are acceptable when needed.
Each PR must receive its own evidence pass and standalone review card. Do not
reuse one PR's architecture, validation, or risk statements as queue-wide prose.
For code-changing PRs, also read the definitions and surrounding active call
sites of the behavior-bearing symbols; the changed hunk alone is insufficient.

Treat `agent_response_contract.explanation_depth_contract` and each
`review_template.sections[].agent_instruction` as the canonical detail policy.
The skill owns routing and evidence discipline; it must not maintain a second,
competing explanation checklist. For older packets without the depth contract,
still explain context, architecture, implementation, validation, necessity, and
risk for a reader who may not know the subsystem.

Record the remote `headRefOid` before deep review and query it again before the
verdict. If it changed, review the new head instead of carrying forward stale
findings. Use a clean read-only worktree at the exact head when local execution
or line-level evidence is useful, and name the reviewed short SHA in the answer.

Before publishing a review, query `headRefOid` one final time. Build the public
review body from the exact reviewed head, remove local paths, private context,
raw logs, credentials, and internal-only links, then submit it with literal-safe
GitHub text handling. Read the resulting review back and verify its state and
rendered body. Avoid duplicate reviews when the same reviewer has already
submitted an equivalent decision for the same head.

Do not fill the five-block review from title, labels, changed-file counts, or
metadata risk hints alone. `metadata_risk_hint` is only for queue ordering.

If the queue is too large for one response, review the highest-priority PRs
first and say which PRs remain. Do not compress individual cards to cover more
of the queue, and do not silently replace review with a summary.

## Per-PR Evidence And Depth Gate

Before drafting each card, build a compact internal evidence record for that PR.
This is preparation for the five required headings, not a sixth output section.
At minimum, record:

- the reviewed base and head SHA, PR body claim, changed paths, and exact check
  state;
- the old behavior and affected caller, plus the intended observable result;
- the entry point, important symbols, active call site, state or data flow, and
  ownership or authority boundary;
- a 2-5 symbol key-code map with exact-head lines, inputs/pre-state, critical
  branches or invariants, calls/side effects, outputs/consumers, and failure
  ownership;
- the changed-line breakdown by production, tests/fixtures, docs, generated
  files, and mechanical moves;
- focused validation tied to the changed invariant, including failures, skipped
  checks, and material cases that remain untested;
- the strongest concrete regression scenario and the code path that permits or
  prevents it;
- the code-volume verdict and one evidence-backed simplification opportunity,
  or an explicit statement that no safe reduction is supported.

Do not draft the verdict while any applicable item above is still inferred only
from the title, PR description, labels, or metadata hint. Read the relevant diff
and symbol, run or inspect focused validation where feasible, and mark evidence
that cannot be obtained as unverified. Each card must stand on its own for a
reader who has not read the PR body or another card in the queue.

Detailed means mechanism-rich, not repetitive. Explain how the implementation
works and why the evidence supports the conclusion instead of paraphrasing the
PR body. For runtime, selector, policy, state, authority, lifecycle, installer,
or bridge changes, include both:

- one concrete positive walkthrough from input or user action to observable
  outcome; and
- one concrete negative or failure walkthrough showing rejection, fallback,
  stale state, malformed input, or missing capability behavior.

The two chains below are the minimum interpretation of the packet's canonical
depth contract. They do not add output headings or compete with packet-specific
instructions; use the same evidence to satisfy both when they overlap.

### Key Code Explanation Gate

For every code-changing PR, put a `### 关键代码讲解` subsection inside
`具体改动`; this is a subsection, not a sixth top-level review block. Select
2-5 behavior-bearing symbols in proportion to the PR. Prefer the entry point,
decision helper, state transition or provider call, receipt/projection builder,
and failure or rollback owner. Do not choose symbols merely because their files
have the most changed lines.

For each selected symbol, explain all applicable items:

- exact-head `file:line` and symbol name;
- responsibility and before/after behavior;
- input or authoritative pre-state;
- critical condition, branch, transition, or invariant;
- important callee, side effect, or persisted write;
- return value, receipt, projection, or downstream consumer;
- rejection, fallback, retry, rollback, or error owner.

Include 1-3 short excerpts from the exact reviewed head, or equivalent
pseudocode when quoting would obscure the mechanism. Follow every excerpt with
an explanation of why the branch exists and how callers observe it. Do not paste
large diff regions, restate code token by token, list filenames without control
flow, or name symbols without explaining execution semantics. Read enough
unchanged surrounding code to identify the real caller and owner boundary.

For a docs-only PR, use `### 关键内容讲解` instead and explain the policy or
content anchors, their intended reader/tool consumer, and any precedence or
compatibility effect. Do not invent code symbols for a documentation-only diff.

### Motivation Causal Chain

Under `动机`, connect the feature objective to the real workflow:

1. name the old caller or operator path and the action that enters it;
2. explain the failure, ambiguity, repeated work, or unsafe default;
3. state who pays the cost and how it compounds in a long-running loop;
4. explain why the nearest existing mechanism or a smaller call-site fix is
   insufficient, or say explicitly when it would be sufficient;
5. name the intended observable outcome, non-goals, and active-call-site
   evidence that makes the need real rather than hypothetical.

Include one compact before/after scenario. Distinguish the PR author's claim
from behavior independently proven by the diff, call sites, tests, or a
reproduction.

### Implementation Execution Chain

Across `改动思路` and `具体改动`, describe an executable model rather than a
file inventory. Identify the caller and public entry point, authoritative
input or state, decision symbol, resulting transition or provider call,
observable receipt or projection, and the component that owns failure,
fallback, or retry.

Trace at least one concrete input through those symbols to the final output.
Use the key-code subsection to show the critical condition or transition with a
short exact-head excerpt or equivalent pseudocode, then connect it to the
surrounding caller and downstream consumer.
Map important changed files to their role in that chain and distinguish
production behavior from adapters, compatibility plumbing, fixtures, and
validation. For a related multi-PR set, add a compact relationship map after
the standalone five-block cards explaining whether the PRs compose, overlap,
depend on one another, or solve different layers. The map never replaces the
per-PR evidence pass or five required headings.

For a blocking finding, name the triggering input or state, trace it to the
incorrect outcome, cite the narrowest file/line or symbol, and state the minimum
repair plus regression test. When no blocker is found, say so explicitly and
still name residual risk and the strongest missing validation. Do not use
generic phrases such as "CI is green", "low risk", or "looks reasonable" as a
substitute for this evidence.

## Code Volume And Simplification Review

For every selected PR, analyze whether its code volume is necessary for the
shipped behavior and name concrete simplification opportunities. Do not treat a
large diff as a defect by itself or reward a small diff that hides complexity.

- Establish the changed-line shape from the exact reviewed base and head with
  `git diff --stat`, `git diff --numstat`, or equivalent evidence. Separate
  production code from tests/fixtures, docs, generated files, and mechanical
  moves before judging implementation size.
- Inspect the largest changed production files and the affected symbols, active
  call sites, and compatibility contracts. Use line count to locate review
  hotspots, not as the verdict.
- Classify the volume as `necessary`, `partly avoidable`, or `not yet proven`.
  Necessary volume may include a cohesive shipped behavior, a real migration or
  compatibility contract, and focused semantic or regression coverage.
- Look for avoidable volume in duplicated domain rules, speculative providers or
  extension points without a caller, compatibility wrappers without a real
  consumer, parameter-heavy helpers that join unrelated behavior, repeated
  fixture assertions, and old entry points that should have been removed.
- Propose a reduction only when it preserves the intended behavior and evidence.
  Cite the file or symbol, explain what can be deleted or collapsed, and name the
  validation that would keep the smaller version honest. If no safe reduction is
  supported by the diff, explicitly say the volume is justified.

Keep the five-heading output contract: put the measured shape and structural
hotspots under `具体改动`, and put the necessity verdict plus the highest-value
simplification direction under `我的整体评价`. A code-volume conclusion without
diff and call-site evidence is incomplete.

## Output Contract

Lead with a one-line evidence-based verdict and highest-severity reason. Then use
exactly these five headings for each reviewed PR:

1. `动机`
2. `改动思路`
3. `具体改动`
4. `对主干的风险`
5. `我的整体评价`

Use the packet's blank `review_template` as the required structure and minimum
detail signal, not as fake/example content. Fill each section only after reading
PR body, files, checks, and diff. Follow the packet's per-section ranges and
instructions as the normal per-PR depth target rather than optional aggregate
guidance. Going shorter is acceptable only when the PR genuinely has less
applicable surface, and the card must still satisfy the per-PR evidence gate.
For code-changing PRs, `具体改动` is incomplete without `### 关键代码讲解` and
the required symbol-level execution semantics. A final chat summary may be
short only after the detailed public review has been published and linked.
Avoid title-only summaries such as "improves docs" or "low risk", and
distinguish intended behavior from what the implementation and validation
actually prove.

For an open PR, the GitHub review state must match the written verdict:

- any remaining P0/P1 blocker, or another explicitly merge-blocking finding:
  `REQUEST_CHANGES`;
- non-blocking findings only: normal review/comment unless the user explicitly
  requests approval;
- no findings: report that clearly and route approval through `loopx-pr-merge`
  when approval is requested.

After publication, include the GitHub review/comment URL in the user-facing
summary. If GitHub rejects the requested review state, report the exact reason
and do not imply that the PR status was updated.

## Failure And Fallback

If `loopx pr-review` is unavailable, first repair the LoopX install or run the
checked-out LoopX CLI from the intended worktree. Do not reconstruct the whole
queue manually from GitHub and call it a successful `/loopx-pr-review` run.

If a selected PR needs approval, merge, self-merge, or admin-bypass, finish the
review first and route that action to `loopx-pr-merge`. Blocking findings do not
need a second authorization step: publish them and submit `REQUEST_CHANGES` by
default unless the user explicitly requested a local-only review.
