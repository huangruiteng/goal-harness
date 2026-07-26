---
name: loopx-change-quality
description: Qualify the exact final diff for a LoopX-managed goal. Use when goal policy enables change_quality_qualification, before a non-trivial delivery or merge, and when producing or repairing an exact-scope quality receipt. The workflow is language-neutral, permits at most one policy-authorized safe-fix pass, and never grants merge or repository authority.
---

# LoopX Change Quality

Use this skill only when the selected goal's
`change_quality_qualification.enabled` policy is true. LoopX owns the canonical
source but does not install it globally. Install a managed copy in a connected
project for the relevant host:

```bash
loopx project-skill install \
  --project . \
  --skill loopx-change-quality \
  --surface codex \
  --execute
```

Use `--surface claude-code` or `--surface opencode` for those hosts. Skill
discovery does not activate the capability; product behavior remains
default-off until goal policy enables it.

The CLI is the contract authority. This skill supplies a host-neutral review
workflow. Repository instructions, tests, linters, type checkers, and security
checks remain the project's quality oracles.

## Prepare The Exact Scope

From the repository worktree, run:

```bash
loopx --format json change-quality prepare \
  --goal-id <goal-id> \
  --repo-path . \
  --base-ref origin/main
```

Stop when the packet says `disabled` or `no_changes`. When it says
`review_required`, review only the files and exact fingerprint in the packet.
Read repository-local instructions before judging the change.

Run `loopx project-skill status --project . --skill loopx-change-quality` when
the host depends on skill discovery. If the managed copy is absent or stale,
preview an explicit project install; do not fall back to a global copy.

## Review Rules

Review the final diff for:

- correctness and behavioral regressions;
- security, privacy, authority, and public/private boundary violations;
- broken caller contracts, schemas, migrations, and state transitions;
- missing validation required by the changed surface;
- unnecessary complexity, duplication of durable knowledge, and abstractions
  without a shipped call site;
- language- and framework-specific issues reported by the project's own tools.

Use `blocker` only for a concrete correctness, security, privacy, contract, or
required-validation failure. Style preferences and speculative redesigns are
`warning` or `advisory`, never blockers.

This first version is single-level. Review one final diff; do not recursively
review the review, spawn a hierarchy of quality agents, or require agreement
between several models.

## Safe Fix

`safe_fix` and `strict_receipt` are independent:

- `safe_fix=true` permits at most one bounded repair pass.
- `strict_receipt=true` requires exact-scope evidence before merge and grants
  no permission to edit.

When `safe_fix` is false, report findings without modifying files. When it is
true, one repair pass may address clear findings inside the selected todo and
goal boundary. Do not use destructive git, broaden permissions, change product
intent, add unrelated refactors, or conceal a failing validator.

After any edit, rerun `prepare`. The old fingerprint is invalid. Review the
entire new final scope, not only the lines changed by the repair.

## Record The Receipt

Write a compact result conforming to the packet's
`change_quality_agent_result_v0` template. Keep raw transcripts, private paths,
credentials, and unbounded logs out of the result.

Then record and read back the exact receipt:

```bash
loopx --format json change-quality record \
  --goal-id <goal-id> \
  --repo-path . \
  --base-ref origin/main \
  --result-json <ignored-or-temporary-result.json> \
  --execute

loopx --format json change-quality verify \
  --goal-id <goal-id> \
  --repo-path . \
  --base-ref origin/main
```

A receipt with an unresolved blocker is not passing. A receipt for an earlier
fingerprint does not qualify a later diff.

## Premerge Enforcement

Run the authoritative merge gate with the goal identity:

```bash
loopx canary premerge \
  --from-git-diff \
  --goal-id <goal-id>
```

Turn may transport the prepare packet or receipt reference as part of one
bounded transaction. Turn does not own quality policy and may not manufacture
or waive a receipt. `canary premerge` remains the enforcement authority.

## Completion Evidence

Report:

- final scope fingerprint and changed-file count;
- safe-fix allowed/applied and pass count;
- blocker, warning, and advisory counts;
- project validations run and their real results;
- receipt id and exact verification status;
- premerge status, failures or skips, and manual holds.

Stop before delivery when strict policy requires a receipt and the receipt is
missing, invalid, stale, or contains an unresolved blocker.
