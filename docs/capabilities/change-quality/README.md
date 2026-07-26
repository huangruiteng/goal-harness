# Change Quality Qualification

Change Quality Qualification gives a LoopX-managed goal a provider-neutral
final-diff review contract. It is default-off. A project opts in through goal
policy and chooses two independent controls:

| Policy | Meaning |
| --- | --- |
| `safe_fix` | Permit one bounded repair pass before the final review receipt |
| `strict_receipt` | Require a passing receipt for the exact current diff at premerge |

`safe_fix` grants limited mutation authority; `strict_receipt` grants none.
Projects may enable either, both, or neither after enabling the capability.

## Configure A Goal

Install the release-owned workflow into each connected project and host that
should discover it:

```bash
loopx project-skill install \
  --project . \
  --skill loopx-change-quality \
  --surface codex \
  --execute
```

Use `claude-code` or `opencode` for those surfaces. This controls discovery,
not activation. Preview goal policy before applying:

```bash
loopx configure-goal \
  --goal-id <goal-id> \
  --change-quality-enabled \
  --change-quality-safe-fix \
  --change-quality-strict-receipt

loopx configure-goal \
  --goal-id <goal-id> \
  --change-quality-enabled \
  --change-quality-safe-fix \
  --change-quality-strict-receipt \
  --execute
```

Absence of this policy is equivalent to all three values being false.

## Protocol

1. `change-quality prepare` hashes the committed, staged, unstaged, and
   untracked content relative to a base ref. It emits a self-contained
   `change_quality_prepare_packet_v0`.
2. A host or model reviews that exact scope using repository instructions and
   project validators. The result uses `change_quality_agent_result_v0`.
3. If policy allows it, the host may perform one bounded safe-fix pass. Any edit
   invalidates the old fingerprint, so prepare and final review run again.
4. `change-quality record --execute` validates the result against the current
   fingerprint and writes a compact local runtime receipt.
5. `change-quality verify` checks the current exact scope.
6. `canary premerge --goal-id <goal-id>` enforces `strict_receipt`.

```bash
loopx --format json change-quality prepare \
  --goal-id <goal-id> --repo-path .

loopx --format json change-quality record \
  --goal-id <goal-id> --repo-path . \
  --result-json <ignored-or-temporary-result.json> --execute

loopx --format json change-quality verify \
  --goal-id <goal-id> --repo-path .

loopx canary premerge --from-git-diff --goal-id <goal-id>
```

Receipts live under goal runtime state, not in the repository. They retain
compact findings and validation labels, not raw model transcripts, credentials,
private context, or validator logs.

## Provider Boundary

The packet does not require a particular model, language, framework, or skill
host. A custom runner may deliver the project-scoped `loopx-change-quality`
skill or inject equivalent instructions from the same LoopX revision. The
global installer intentionally skips project-scoped skills. The project still
owns its tests, lint, type checking, security checks, and repository-specific
rules.

A blocking finding must be a concrete correctness, security, privacy, contract,
or required-validation failure. Subjective style advice remains nonblocking.

Turn may carry the packet or receipt reference inside one bounded execution.
It does not own policy or enforcement. The authoritative merge decision stays
in `canary premerge`.

## Initial Scope

The first version deliberately qualifies one final diff with at most one
safe-fix pass. It does not recursively review reviews, build a model hierarchy,
or require several agents to reach consensus. Those mechanisms should be added
only after single-level receipts show a concrete failure they can solve.
