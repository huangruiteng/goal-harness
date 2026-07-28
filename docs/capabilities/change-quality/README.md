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
   untracked content relative to a base ref. It emits
   `change_quality_prepare_packet_v1`.
2. The packet projects path-only repository context: applicable instruction
   files, ownership files, build manifests, language hints, changed surface
   roots, and a provider-neutral validation plan. It does not copy instruction
   text, task bodies, or manifest contents into the control plane.
3. A host or model reviews that exact scope using ten required lenses: reuse,
   type/API boundaries, configuration, runtime ownership,
   quality/simplification, efficiency, error/supervision, test/validation,
   documentation/comments, and security/release. The result uses
   `change_quality_agent_result_v1`.
4. If policy allows it, the host may perform one bounded safe-fix pass. Any edit
   invalidates the old fingerprint, so prepare and final review run again.
5. `change-quality record --execute` requires complete per-lens conclusions,
   the principles from every projected repository instruction file, an
   explicit simplification decision, and typed validation evidence. Every
   applicable lens must cite a changed path, instruction, finding, validator,
   or simplification decision. Repeated generic all-clear summaries are
   rejected. The command validates the result against the current fingerprint
   and writes a compact local runtime receipt.
6. `change-quality verify` checks the current exact scope and v1 protocol.
7. `canary premerge --goal-id <goal-id>` enforces `strict_receipt`.

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
compact findings, per-lens conclusions, simplification decisions, and typed
validation evidence. Lens evidence references are typed and cross-checked
against the exact changed paths and receipt objects. Receipts do not retain raw
model transcripts, credentials, private context, or validator logs.

## Provider Boundary

The packet does not require a particular model, language, framework, or skill
host. Its review lenses name engineering outcomes rather than tools. A custom
runner may deliver the project-scoped `loopx-change-quality` skill or inject
equivalent instructions from the same LoopX revision. The global installer
intentionally skips project-scoped skills. The project still owns its tests,
lint, type checking, security checks, build commands, and repository-specific
rules; LoopX records which oracles ran and their outcomes instead of pretending
that one universal checker understands every language.

The validation plan discovers only repository-declared task identities from
structured manifests. Initial adapters understand Poe and Hatch task names in
`pyproject.toml`, Cargo aliases in `.cargo/config.toml`, and package scripts in
`package.json`. Each candidate carries a category, runner kind, task name, and
source reference; script bodies stay in the repository and execution remains a
host decision. Missing format, lint, typecheck, or test categories stay
explicitly unresolved instead of being filled with guessed commands. Applicable
`AGENTS.md` and `CLAUDE.md` files are projected as required reads, not parsed as
shell input. Manifests under fixture, testdata, vendor, third-party, or
dependency directories are reported as ignored references and never promoted
to project oracle candidates.

A blocking finding must be a concrete correctness, security, privacy, contract,
or required-validation failure. Subjective style advice remains nonblocking.
A failed validator is independently non-passing even when a reviewer forgot to
repeat it as a blocker finding.

Turn may carry the packet or receipt reference inside one bounded execution.
It does not own policy or enforcement. The authoritative merge decision stays
in `canary premerge`.

## Initial Scope

This version deliberately qualifies one final diff with at most one safe-fix
pass. It does not recursively review reviews, build a model hierarchy, or
require several agents to reach consensus. Language and build-system hints are
discovery inputs, not hardcoded validator policy. The initial matrix proves the
same output contract for Python, Rust, and TypeScript while preserving distinct
Poe, Cargo, and package-script runner identities. It does not invent a shared
compactor or silently execute any task.

The initial semantic calibration uses five public control-plane PRs covering a
registry boundary extraction, benchmark read-model move, recoverable Turn
stages, Vision replan repair, and capability-envelope propagation. The replay
keeps the benchmark-sensitive manual hold independent from receipt success and
proves that only one coherent safe-fix pass can be reported. These fixtures
calibrate review behavior; they are not project-specific production policy.
