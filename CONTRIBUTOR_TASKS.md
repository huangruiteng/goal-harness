# Contributor Task Board

This board is the public, contributor-facing projection of Goal Harness work.
It is intentionally different from `.local` active goal state:

- this file lists public work that can be discussed, claimed, reviewed, and
  validated in the repository;
- `.local`, `.goal-harness`, and live `ACTIVE_GOAL_STATE.md` files remain local
  runtime data for maintainers and automation;
- private benchmark traces, verifier output, raw agent sessions, credentials,
  internal document links, and local machine paths must not be copied here.

The goal is to make important work discoverable without turning the repository
into a mirror of maintainer scratch state.

## Status Legend

| Status | Meaning |
| --- | --- |
| Available | Ready for someone to comment on the linked issue or open a small PR. |
| Claimed | Someone has said they are working on it, or a maintainer assigned it. |
| Maintainer-owned | Active work is happening in maintainer/local automation; ask before touching. |
| Needs design | Discussion is welcome, but implementation needs agreement first. |
| Blocked | Waiting on a decision, dependency, or maintainer writeback. |
| Done | Completed and ready to archive from this board. |

## How To Claim Work

1. Prefer a linked GitHub issue. If there is no issue yet, open one with the
   contributor task template.
2. Comment that you would like to work on the task. Maintainers will mark it
   `claimed` or suggest a smaller slice.
3. For docs-only typo fixes or obviously tiny cleanups, opening a direct PR is
   fine.
4. If a claimed task has no update for 14 days, maintainers may release it back
   to `Available` after one ping.
5. If a task is `Maintainer-owned`, do not duplicate the work. Ask whether
   there is a public helper slice instead.

## Current Public Tasks

| ID | Status | Area | Good first? | Scope | Owner / issue | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| GH-C01 | Available | docs | Yes | Add a short "first goal" walkthrough that starts with `goal-harness demo`, inspects status/history, completes one todo, and shows the next todo. Keep it public and runnable on a clean checkout. | Unclaimed | `goal-harness check --scan-path README.md --scan-path docs/ --scan-path examples/` |
| GH-C02 | Available | tests | Yes | Add or extend a focused smoke test around todo archive/completion behavior. Prefer copying the style of `examples/todo-lifecycle-cli-smoke.py`. | Unclaimed | `python3 examples/todo-lifecycle-cli-smoke.py` and `python3 -m py_compile goal_harness/*.py` |
| GH-C03 | Available | diagnostics | No | Improve duplicate run-history index diagnostics so `goal-harness check` gives the next repair action, not only a warning. Include a small fixture or smoke path if practical. | Unclaimed | `goal-harness check --scan-root .` plus focused smoke if added |
| GH-C04 | Available | docs | Yes | Improve README troubleshooting for install, PATH setup, canary/default wrappers, and `goal-harness doctor`. | Unclaimed | `goal-harness check --scan-path README.md --scan-path CONTRIBUTING.md` |
| GH-C05 | Available | regression | No | Create the first `regression/` case for a previously observed control-plane stall, such as external-evidence waits, P0-blocked/P1 fallback, compact blocker writeback, or no-progress self-repair. Keep it deterministic and public-safe. | Unclaimed | Focused regression command plus `python3 -m py_compile goal_harness/*.py` |
| GH-C06 | Available | cli | No | Start CLI modularization by defining a `goal_harness/cli_commands/` command-module contract and migrating one low-risk command group while preserving old invocations. | Unclaimed | Old command smoke plus `python3 -m py_compile goal_harness/*.py` |
| GH-C07 | Available | state | No | Add structured-state write serialization for todo/refresh/history writers using a per-goal lock or optimistic revision guard. Include a concurrent todo add/update regression. | Unclaimed | New concurrency regression plus `python3 -m py_compile goal_harness/*.py` |
| GH-C08 | Available | status | No | Improve agent todo projection so `status` / `quota should-run` can expose a broader priority-sorted backlog without letting monitor items hide executable work. | Unclaimed | `goal-harness --format json status` fixture or focused smoke |
| GH-C09 | Available | diagnostics | Yes | Inspect duplicate run-history index rows with `history inspect-index-duplicates`, then document the current repair path in public-safe troubleshooting docs. This is docs-first; code fix can be a follow-up. | Unclaimed | `goal-harness check --scan-path docs/ --scan-path README.md` |
| GH-C10 | Available | docs | Yes | Add a public "what counts as a good smoke" guide using `CONTRIBUTING.md` and recent benchmark-smoke cleanup as source material. Explain when to keep, merge, or delete smokes. | Unclaimed | `goal-harness check --scan-path CONTRIBUTING.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C11 | Available | fresh clone | No | Harden the fresh-clone public user path: install wrapper, PATH, `doctor`, `demo`, `status`, dashboard status export, and project skill install/update. Record only public blockers. | Unclaimed | Fresh checkout notes plus runnable smoke or checklist |
| GH-C12 | Available | dashboard | No | Add a first-screen status/dashboard acceptance smoke that verifies goal name, waiting owner, recommended action, safety boundary, first user todo, and highest-priority agent todo appear before raw run-history drilldown. | Unclaimed | Dashboard/status smoke or fixture |
| GH-C13 | Available | docs | Yes | Expand public/private boundary examples with realistic safe and unsafe snippets for benchmark traces, active state, local paths, credentials, and compact artifacts. | Unclaimed | `goal-harness check --scan-path docs/public-private-boundary.md --scan-path examples/` |
| GH-C14 | Available | protocol | No | Add a focused regression for protocol action packet output so future Codex CLI wrappers cannot accidentally invoke model APIs or runner adapters from the decision-only path. | Unclaimed | `python3 examples/protocol-action-packet-smoke.py` or new focused smoke |
| GH-C15 | Available | benchmark | No | Implement benchmark ledger drift warning: when compact run history has a benchmark result but `benchmark-run-ledger.json/md` lacks the row, status should warn or closeout should auto-upsert. Keep raw task/log/trajectory material out. | Unclaimed | `python3 examples/benchmark-run-ledger-smoke.py` |
| GH-C16 | Available | benchmark | No | Add a public-safe trajectory-summary contract for non-SkillsBench adapters so Terminal-Bench/SWE/ALE can expose comparable counters without raw task text, logs, verifier output, or trajectory bodies. | Unclaimed | New unit/fake fixture smoke |
| GH-C17 | Needs design | benchmark | No | Design per-round artifact snapshot/restore for blind-loop benchmark runs so `best_score` can become an executable final-selection policy, not only an offline metric. | Unclaimed | Design note with stop conditions and public/private boundary |
| GH-C18 | Maintainer-owned | benchmark | No | Long-horizon benchmark evidence program, including live local no-upload cases, runner contracts, trace retention, score accounting, and good/bad case attribution. Do not duplicate live runs or inspect private artifacts unless maintainers split out a public helper issue. | Maintainers | Maintainer-run benchmark ledger and public/private scan |
| GH-C19 | Maintainer-owned | benchmark | No | Main-table SkillsBench product-mode comparison: raw Codex autonomous max5 versus Goal Harness state/todo/replan/CLI, no verifier feedback to either arm, stop on reward 1 or declared done. External contributors can help with schema/docs/smokes only. | Maintainers | Maintainer-run compact ledger and case-analysis update |
| GH-C20 | Needs design | benchmark | No | Define runner-agnostic benchmark lifecycle schema: `launch -> observe -> ingest -> classify -> ledger`, with stages such as process started, job materialized, trial started, worker started, result written, verifier scored. | Unclaimed | Design doc plus one adapter-neutral fixture |
| GH-C21 | Needs design | benchmark | No | Split benchmark accounting into launcher attempt, case attempt, solver attempt, verifier attempt, and official-score attempt. Launcher/materialization failures must not count as case failures. | Unclaimed | Design doc or focused ledger fixture |
| GH-C22 | Available | benchmark | No | Add launch artifact observable handles: pid/process state, job basename, compact artifact refs, allowed poll command, and read-boundary flags so heartbeat observation does not depend on chat memory. | Unclaimed | Focused fake launch artifact smoke |
| GH-C23 | Needs design | policy | No | Replace narrative benchmark authorization with `run_permission_policy_v0`: allowed local no-upload model/Docker/Harbor actions, forbidden upload/leaderboard/public claim/production/cloud actions, timeout budget, and compact-only observation. | Unclaimed | Schema note plus projection smoke |
| GH-C24 | Needs design | adapters | No | Plan adapter lifecycle rollout from Terminal-Bench to SkillsBench, SWE, and ALE using the same lifecycle/failure schema while keeping benchmark-specific runner details inside adapters. | Unclaimed | Design note accepted by maintainers |
| GH-C25 | Needs design | server | No | Design a local Goal Harness server/daemon roadmap that preserves CLI contracts while centralizing per-goal locks, leases, idempotency keys, quota decisions, heartbeat scheduling, and compact status projection. | Unclaimed | `docs/` roadmap update |
| GH-C26 | Needs design | planning | No | Define server-managed dreaming/planning semantics: background planning may propose ranked todos and evidence probes but must not execute protected work or spend delivery quota. | Unclaimed | Design note plus no-execution fixture |
| GH-C27 | Available | planning | No | Add a contract regression separating autonomous replan from dreaming: autonomous replan is must-attempt bounded delivery/control-plane repair; dreaming is advisory, operator-gated, and must not emit `agent_command`. | Unclaimed | Focused quota/status smoke |
| GH-C28 | Available | planning | No | Implement local-only dry-run proposal generation for dreaming: read public-safe run history/project state and emit proposal records without mutating project truth. | Unclaimed | Dry-run smoke with fake project state |
| GH-C29 | Needs design | dashboard | No | Add dashboard/status design for a separate Dreaming lane or badge beside delivery and operator gates, so exploration proposals do not interrupt active project agents. | Unclaimed | Dashboard design note or fixture |
| GH-C30 | Available | docs | Yes | Add a "project asset contract" explainer showing owner, gate, next action, stop condition, last evidence, next safe command, user todo, agent todo, support mode, and fresh status projection. | Unclaimed | `goal-harness check --scan-path docs/ --scan-path README.md` |
| GH-C31 | Needs design | project intake | No | Prepare a read-only observer / authority-map intake for a complex open-source project. It should produce only a compact project map and missing-gate list before any write-control or private material access. | Unclaimed | Design note plus dry-run map fixture |
| GH-C32 | Needs design | learning | No | Design public-safe reward-style learning for replanning: turn explicit reward/corrections into compact ranking hints without storing raw private chat or treating inferred preferences as hard gates. | Unclaimed | Design note with privacy constraints |
| GH-C33 | Needs design | resource sync | No | After server/daemon design lands, define periodic Resource-to-Todo sync that compares repo docs, roadmap/status contracts, and authority commitments against active todos, then proposes updates through structured lifecycle APIs. | Unclaimed | Design note; implementation blocked on server lane |

## Projection Sources

This board is maintained from public-safe projections of:

- the local `goal-harness-meta` Agent Todo list;
- public docs under `docs/`, especially the state interaction model, status
  data contract, quota allocation, integration guide, and benchmark research
  docs;
- recent maintainer review of which work is externally claimable versus
  maintainer-owned live automation.

Projection rules:

- copy the task intent, not private evidence details;
- convert private benchmark runs into public helper slices unless maintainers
  explicitly publish a runnable issue;
- mark live benchmark, release, and automation lanes as `Maintainer-owned`
  when duplicate work would waste compute or weaken evidence;
- prefer tasks that name likely files and validation, so contributors can start
  without reading local active state.

## Suggested Labels

Use these labels on GitHub issues when possible:

- `good first issue`: small, well-scoped, low setup, with files and validation
  called out.
- `help wanted`: useful public task where the approach is clear enough for an
  external contributor.
- `claimed`: someone is actively working on the issue.
- `maintainer-owned`: visible work that should not be duplicated.
- `needs design`: implementation is not ready until the design is agreed.
- `blocked`: waiting on a decision, dependency, or maintainer action.
- Area labels such as `area: docs`, `area: cli`, `area: status`,
  `area: benchmark`, `area: dashboard`, and `area: tests`.

## Maintainer Update Rules

- Keep this board curated. If it grows beyond roughly 35 open rows, move older
  or lower-priority work into GitHub issues and keep only the best entry points
  here.
- Every public task should include a scope, expected validation, and owner
  state.
- Do not publish private/local state. Summarize it into a public task only when
  the work is safe for the repository.
- After a meaningful internal milestone, update this board manually if there is
  a new contributor-sized slice.
- Remove or refresh stale tasks instead of leaving obsolete "good first issue"
  entries in place.
