# Contributor Task Board

This board is the public, contributor-facing projection of LoopX work.
It is intentionally different from `.local` active goal state:

- this file lists public work that can be discussed, claimed, reviewed, and
  validated in the repository;
- `.local`, `.loopx`, and live `ACTIVE_GOAL_STATE.md` files remain local
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

Start with **Starter** tasks if this is your first contribution. Choose
**Focused** tasks if you are comfortable running local smokes. Pick **Advanced**
tasks only when you are ready to touch shared state, adapters, or concurrency.
Use **Design/RFC** tasks to shape direction before implementation.

## Product Manager Cut

LoopX is currently converging from a control-plane library into a management
surface for long-running agent work. Product-capability contributions should
prefer slices that make existing kernel objects understandable to users instead
of adding another source of truth.

| Product slice | Current substrate | Contributor-sized next cut |
| --- | --- | --- |
| Management frontstage | Goals, todos, gates, claims, evidence, quota, run history, `goal_channel_projection_v0`, `task_graph_projection_v0`, `issue_fix_outcome_projection_v0`, `agent_management_projection_v0`, and same-source Explore views are already compact read models. The public homepage, hosted docs, and localized dashboard now expose these surfaces. | Translate the read models into stable operator concepts such as work item, owner, decision, evidence, budget, risk, and next action; preserve lineage, keep raw machine fields in drill-downs, and do not create a second task or case store. Changes to a public first viewport remain maintainer-preview work. |
| Conversational commands | `global_manager_command_v0` defines read-only commands such as `/loopx-global-summary`, `/loopx-global-gates`, `/loopx-global-todos`, and `/loopx-global-risks`; legacy `/loop-global-*` forms are only migration aliases. | Implement one canonical command at a time with a public-safe smoke and no alias sprawl. Unknown commands should fail closed with help. |
| Runtime connector modes | `host_mode_plan_v0` selects visible, isolated-headless, gateway, service, and hybrid modes over the connector catalog. Host-loop activation now covers Codex surfaces, Claude Code, OpenCode, TraeX, Pi, and custom agents; a scheduler-hint-aware external worker demonstrates one signed headless route. LoopX Turn remains one isolated request/effect/receipt transaction rather than a recurring loop. | Add one provider-neutral parity slice for route preservation, skill delivery/readback, continuation deadlines, signed primary actions, or stage/receipt visibility. Keep host wake/process ownership outside LoopX core and do not create a second scheduler or duplicate controller. |
| Planner-worker mode | The experimental planner-worker contract now supports one bounded plan, one selected worker step, an allowlisted validation set, a clean-worktree boundary, and a typed receipt; the TraeX probe is only one extension provider. | Add provider-neutral usage and failure guidance around the shipped fake runtime. Keep model routing explicit, validation caller-approved, and recurring scheduling or broad multi-agent orchestration outside this mode. |
| Visible governance | Quota, scheduler hints, authoritative interaction contracts, decision scopes, user gates, peer claims, optional task leases, repository policy, interface budgets, and provider-neutral PR program snapshots already exist in machine contracts. A shared-goal authority/state-provider RFC now defines the next coordination boundary without making the proposal runtime authority. | Show who can act, who must approve, which decision scope applies, what budget was spent, and how pause/override/terminate decisions map back to LoopX state. Keep proposal state, claims, leases, and PR program observations from becoming a new runtime hierarchy or write authority. |
| Decision and material quality | Decision Context and Material Lifecycle are experimental, built-in, default-off capabilities. They separate revision-bound evidence, advisory proposals, material planning, owner-gated apply, and private cursor/source state. | Build synthetic, no-provider walkthroughs that make these boundaries visible. Do not add private adapters, source bodies, provider payloads, or a second lifecycle store. |
| Memory and content workflows | Agent Turn Recall composes quota-selected work with scoped Reward Memory, while `content_ops_item_v0` preserves stable item identity, revision-bound approval, delivery/readback receipts, and supersession. Both remain advisory or preview-level and add no provider authority. | Add synthetic walkthroughs and negative fixtures that prove identity, revision, and failure boundaries. Keep provider payloads, draft bodies, credentials, raw sessions, and external writes outside LoopX state. |
| Extensions and change qualification | Standalone `extension init` scaffolding and managed zero-permission execution demonstrate optional provider delivery. Exact-diff Change Quality is separately goal-scoped, simplify-first, and enforced through fresh receipts when enabled. | Improve one existing provider or validation seam at a time. Do not invent a capability for installability, auto-run discovered repository tasks, or weaken exact-scope receipt checks. |

## Recent Maintainer Progress

These public milestones changed which tasks are still useful contributor entry
points:

| Area | Landed | Contributor implication |
| --- | --- | --- |
| Decision, content, issue-fix, and PR productization | The revision-bound content-item lifecycle is shipped. Current `main` also guards discovered issue promotion, pins approved issue-fix base snapshots before branch creation, and adds provider-neutral PR program snapshot/diff tracking. | Add one synthetic lifecycle walkthrough or missing negative fixture. Keep activation explicit and leave source bodies, draft bodies, review text, provider payloads, private locators, cursor state, and apply/publish authority outside public fixtures. |
| Public surfaces and showcases | The public homepage, hosted documentation site, Chinese operator dashboard, and stable README entry points are shipped. The Auto Research course, catalog, and long-horizon public evidence remain the reusable showcase path. | Improve deterministic evidence, accessible navigation, locale parity, or readability using existing surfaces and synthetic data. Do not alter the README or public homepage first screen without maintainer preview, or couple a renderer to one delivery provider. |
| Host loops and orchestration | A bounded external scheduler worker, TraeX Turn adapter, Pi Goal host, and adaptive child-admission contract have landed. They preserve signed actions, explicit identity/capabilities, repository conflict checks, and one bounded child/Turn receipt. | Add cross-host fake-fixture parity for skill delivery, action provenance, timeout/termination, or replan handoff. Do not infer child capability, treat a resumable session as authority, or embed a resident scheduler in LoopX. |
| Shared coordination and review | Peer claims remain routing signals. Provider-neutral PR program tracking and a shared-goal authority/state-provider RFC now make coordination state more reviewable, while PR review guidance requires causal and execution chains. | Add synthetic conformance and negative cases around observation, authority, and lineage. The RFC is not a grant to write remote state, and PR review snapshots must not retain private review bodies or provider payloads. |
| Status, quota, and monitors | Paused goals are authoritative terminal decisions, file-lock acquisition is bounded, registry CLI ownership budgets are restored, and monitor/selected-todo projections preserve capability provenance. Dedicated hot-path budget and todo-detail cold-path smokes remain the reference. | Extend one measured performance, detail-readback, lock-timeout, or malformed-state case. Keep default output bounded, cold-path detail available, and unavailable capabilities visible without adding another projection source. |
| Benchmark boundary | Shared lifecycle, readiness, ledger, and reducer contracts remain the public seam. Live scored comparisons are currently held until a fresh task-free runner lifecycle receipt proves readiness; the pure Turn Loop Controller is still coordination-required. | Extend another adapter through shared seams or add synthetic setup/termination attribution. Do not launch scoring, duplicate the controller, or expose raw task text, logs, trajectories, verifier tails, credentials, uploads, or local paths. |
| Validation and change quality | Python tests are green on the latest runtime-bearing `main` change. The newest Full Public run was partly blocked by GitHub Actions service availability; a runnable shard also exposed a stale required-skill expectation in `agent-onboard-host-loop-activation-smoke.py` after PR program became part of onboarding. The earlier KNN timing oracle still needs deterministic coverage. | Derive expected skill delivery from canonical manifests, replace timing as a semantic oracle, retain negative/mutation coverage, and distinguish infrastructure outages from product regressions. Keep live model/provider checks explicit and low-frequency. |
| Release and install | v0.4.1 is the latest public tag and package version. `main` now contains post-v0.4.1 product and public-surface changes, while `docs/product/release-readiness.md` still stops at v0.2.6. | Close the v0.2.7-v0.4.1 timeline gap from tagged release evidence, preserve tagged stable versus post-tag `main`, and improve contributor-safe update recovery without adding a parallel release checklist. |
| Public docs and onboarding | Hosted docs, a public homepage, localized dashboard copy, and public/private boundary examples have landed. Slash-command installation now exposes the canonical global manager command set, while only the summary command has a runtime implementation. | Keep contributor, release, protocol, course, and showcase surfaces concise and linked to public evidence; add navigation/locale checks and implement one missing read-only manager command at a time instead of appending status narratives or aliases. |

## Turn Loop Controller Plan

`loopx turn run-once` remains the atomic governed executor: decide, execute one
bounded host segment, validate independently, write back, spend once, and
project the latest scheduler contract. Host-loop activation, the external
scheduler worker, and visible Pi/TraeX integrations now provide concrete outer
loops, but they do not make LoopX a resident scheduler. The maintainer-owned
pure controller and replan transition are still in hardening, so contributors
should focus on independently derived decision tables, cross-host parity,
fail-closed fixtures, or docs that clarify the boundary below.

| Priority | Planned slice | Required boundary and proof |
| --- | --- | --- |
| P0 | Harden the maintainer-owned pure Turn Loop Controller transition contract over one Turn receipt plus a fresh quota/scheduler decision. | Return exactly one typed disposition such as `run_now`, `wait`, `user_action_required`, `repair`, `replan`, or `terminal`; reject malformed receipts, stale continuation, and invalid budgets without invoking a model, sleeping, mutating a host scheduler, writing state, or spending quota. |
| P0 | Make `replan_required` a real continuation boundary. | Before another Turn, write a bounded todo or vision delta, obtain a fresh TurnEnvelope, and preserve the causal agent/todo frontier. Never rerun the same stale todo merely because a host session is resumable. Reuse the existing autonomous-replan and two-stall contracts. |
| P1 | Qualify host-loop activation and skill-delivery parity. | Compare Codex, Claude Code, OpenCode, TraeX, Pi, and custom-agent packets against one provider-neutral fixture. Required skills and readback must come from the canonical release/goal contract rather than ambient host state. |
| P1 | Extend scheduler-owner and monitor parity from the shipped external worker. | Apply signed `primary_action`, `scheduler_hint` wake/backoff/terminal-stop, concrete user routing, and quiet no-spend monitor decisions through the declared runtime owner. `run-once` remains the only delivery transaction. |
| P2 | Qualify parity with Codex App heartbeat and adaptive child admission. | Use deterministic fixtures across active work, wait, user gate, repair, replan, child admission/conflict, monitor, and terminal states, followed by one explicit opt-in real-host qualification. Preserve independent validation and exclude raw prompts, transcripts, credentials, and host-local paths. |

Do not open a second implementation PR for the pure transition contract while
the maintainer-owned slice is active. Scheduler process management,
host-specific wake APIs, and operator presentation remain later adapters so
each slice stays reviewable and reversible.

### Starter / Good First

Low setup, docs-first, or narrow fixture work. These should be good entry
points for contributors who are still learning the repository.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C02 | tests | Add or extend a focused smoke test around todo archive/completion behavior. Prefer copying the style of `examples/control_plane/todo-lifecycle-cli-smoke.py`. | `python3 examples/control_plane/todo-lifecycle-cli-smoke.py` and `python3 -m py_compile loopx/*.py` |
| GH-C04 | docs | Refresh install, activation, and recovery guidance through v0.4.1: add concise v0.2.7-v0.4.1 timeline summaries from tagged release evidence, preserve tagged stable vs post-tag `main` and release-snapshot vs canary distinctions, cover installed-runtime activation recovery, and link rather than duplicate the release body's bilingual optional-capability usage guidance. | `python3 examples/fresh-clone-quickstart-smoke.py`, `python3 examples/loopx-update-smoke.py`, `python3 examples/release/release-readiness-doc-smoke.py`, `python3 examples/release/release-version-contract-smoke.py`, and `loopx check --scan-path docs/product/release-readiness.md --scan-path CONTRIBUTING.md` |
| GH-C10 | docs | Add a public "what counts as a good smoke" guide using `CONTRIBUTING.md` and recent benchmark-smoke cleanup as source material. | `loopx check --scan-path CONTRIBUTING.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C80 | docs | Add a hosted-docs navigation and locale-parity check across `mkdocs.yaml`, `docs/index.md`, the docs catalog, and stable README entry links. Catch broken or orphaned public pages without changing the README or homepage first viewport. | `python3 examples/docs-governance-smoke.py`, `python3 examples/frontstage-pages-workflow-smoke.py`, a strict MkDocs build, and `loopx check --scan-path docs --scan-path mkdocs.yaml --scan-path README.md --scan-path README.zh-CN.md` |
| GH-C64 | release docs | Add a contributor-safe atomic-promotion failure matrix around the shipped release lock/concurrency smoke: explain which failures happen before the symlink swap, how a waiter recovers, and when contributors must stop before maintainer-only promotion state. Extend the existing fixture only for a durable missing case. | `python3 examples/release/release-promotion-concurrency-smoke.py`, `python3 examples/release/local-install-promotion-boundary-smoke.py`, and `loopx check --scan-path docs/product/release-readiness.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C75 | runtime docs | Add a public operator guide for the experimental planner-worker mode using the shipped provider-neutral fake runtime. Explain the clean-worktree requirement, explicit model routes, caller-approved validation commands, one-step typed receipt, incomplete-cost semantics, provider opt-in, and how to stop without presenting it as a resident scheduler or default multi-agent runtime. | `python3 examples/experiments/planner_worker/contract-smoke.py`, `python3 examples/experiments/planner_worker/runtime-smoke.py`, and `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path CONTRIBUTOR_TASKS.md` |

### Focused Implementation

Small-to-medium code changes with a clear validation surface. These are good
for contributors who can run local CLI smokes and keep changes scoped.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C06 | cli | Characterize one remaining oversized CLI ownership seam after the recent quota, status, todo, history, and scheduler command-plumbing extractions, then move only a cohesive command or rule group into its bounded module. Preserve public invocations, avoid compatibility wrappers without a real caller, and keep the module-size/import budget honest. | Command-specific smoke, `python3 examples/cli-command-module-size-ownership-command-modularization-smoke.py`, `python3 regression/cli-command-module-contract.py`, and focused pytest if rules move |
| GH-C40 | benchmark | Adopt the bounded benchmark lifecycle/read-model seams in one remaining adapter, preferably ALE: keep adapter ingestion under `loopx/benchmark_adapters/`, reusable projections under `loopx/benchmarks/read_models/`, and release-only comparisons under `loopx/benchmarks/qualification/`. Add compact readiness, blocker, and result reducers without moving raw logs, task text, verifier output, or host paths into the public control plane. | `python3 examples/benchmark-developer-workflow-doc-smoke.py`, `python3 examples/benchmark-core-adapter-contract-smoke.py`, `python3 -m pytest -q tests/architecture/test_control_plane_import_boundaries.py`, and one adapter-focused fake fixture |
| GH-C43 | showcase | Extend the shipped Auto Research long-running showcase with a contributor-safe stop/takeover and state-aware wakeup walkthrough. Reuse the current command path and synthetic/redacted evidence; do not add a second launcher or alter the README first screen without maintainer preview. | `python3 examples/showcase-catalog-smoke.py`, `python3 examples/auto-research-demo-e2e-worker-loop-smoke.py`, `python3 examples/auto-research-visible-worker-hook-smoke.py`, and `loopx check --scan-path docs/showcases --scan-path docs/guides` |
| GH-C49 | dashboard | Polish the shipped `/frontstage` goal-channel board: improve visual acceptance, local demo fixture clarity, and operator onboarding while keeping browser data read-only and making outcome, lease, capability-wait, and workspace-repair states legible. | `npm run smoke:frontstage-route`, `npm run smoke:frontstage-browser`, and `loopx check --scan-path apps/presentation/dashboard --scan-path docs/product/roadmaps/dashboard-frontend-selection.md` |
| GH-C50 | control plane | Implement the first generic `observable_artifact_handle_v0` slice from `docs/product/domain-capability-packs.md`: compact handle, allowed poll command, artifact refs, terminal markers, and read-boundary flags for long-running work without assuming a benchmark, CI, deployment, or ML experiment adapter. | Focused fixture smoke plus `loopx check --scan-path docs/product/domain-capability-packs.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C74 | productization | Add one public synthetic walkthrough from a revision-bound Decision Context packet to a Material Lifecycle rerank preview. Prove stale/conflicting evidence stays visible, source bodies and private locators stay absent, and apply/cursor commits remain separate owner-gated actions. | `python3 examples/decision-context-contract-smoke.py`, `python3 examples/material-lifecycle-contract-smoke.py`, focused capability pytest, and `loopx check --scan-path docs/capabilities/decision-context --scan-path docs/capabilities/material-lifecycle --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C60 | workflow | Add one focused fake-fixture parity slice across Codex App heartbeat, Codex CLI TUI, LoopX Turn, Claude Code, OpenCode, TraeX, Pi, Ark Managed Agent, the external shell worker, HTTP webhook, and worker bridge. Cover one missing explicit capability route, signed primary action, scoped identity, skill delivery/readback, typed Goal continuation, runtime-owned cadence, no-spend transition, workspace repair, or private-boundary case. | `python3 examples/host-mode-plan-smoke.py`, `python3 examples/project/host-mode-plan-cli-smoke.py`, `python3 examples/control_plane/agent-onboard-host-loop-activation-smoke.py`, focused host bridge tests, `python3 -m pytest -q tests/test_loopx_turn_transaction.py tests/test_external_scheduler_worker.py tests/test_pi_goal_mode.py`, and `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path docs/reference/protocols/host-mode-plan-v0.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C59 | status | Extend the shipped hot-path performance and todo-detail cold-path contracts with one large ignored-state-tree, bounded drill-down, or malformed-state case so `status` / `quota` stay fast without dropping public-safe backlog detail. | `python3 examples/control_plane/status-quota-perf-budget-smoke.py`, `python3 examples/control_plane/todo-detail-cold-path-contract-smoke.py`, focused fixture coverage, and `loopx check --scan-path docs/status-data-contract.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C61 | cli | Implement the next canonical global manager command after `/loopx-global-summary`: choose one of `/loopx-global-gates`, `/loopx-global-todos`, `/loopx-global-risks`, or `/loop-goal-summary`, keep it read-only, source it from compact status/quota/todo/run-history projections, and make unknown aliases fail closed with help instead of broad dumps. | Focused command smoke plus `python3 examples/project/global-manager-command-protocol-smoke.py` and `loopx check --scan-path docs/reference/protocols/global-manager-command-v0.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C62 | governance | Add a synthetic visible-governance slice that relates per-goal/per-agent claims, optional task leases, quota, scheduler hints, decision scopes, and the shared-goal RFC's proposed authority/state-provider boundary. Make proposal versus shipped truth explicit; do not add a browser write API, infer scopes from prose, or present provider observations or leases as runtime authority. | Focused fixture smoke, `python3 -m pytest -q tests/control_plane/test_todo_decision_scope_lifecycle.py`, and `loopx check --scan-path docs/status-data-contract.md --scan-path docs/architecture/rfcs/shared-goal-authority-state-provider-v0.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C68 | validation | Move the stable pure rules from one oversized control-plane smoke, preferably `quota-scheduler-state-ack-smoke.py`, into independently derived pytest decision tables while retaining a thin CLI/public-behavior seam. Add at least one negative or mutation case so current implementation output cannot become the oracle. | Focused pytest, the retained smoke, `python3 examples/full-public-smokes-workflow-smoke.py`, and `git diff --check` |
| GH-C69 | explore | Add a public-safe local fixture and contributor walkthrough for canonical, executive, and semantic owner-board Explore views. Prove decision/evidence lineage and readability without enabling an external sink or depending on local/private graph sources. | `python3 examples/explore-result-layer-smoke.py`, `python3 -m pytest -q tests/test_explore_presentation_views.py`, and `loopx check --scan-path docs/capabilities/explore --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C70 | runtime | Add a provider-neutral host-loop parity walkthrough that runs the same synthetic task through the external scheduler worker plus one visible host such as Pi or TraeX. Compare signed action selection, compact Turn receipts, independent validation, recoverable timeout/termination, replan, and terminal no-followup behavior without retaining raw sessions or host-local paths. | Focused fake-host smoke, `python3 -m pytest -q tests/test_loopx_turn_driver.py tests/test_external_scheduler_worker.py tests/test_pi_goal_mode.py`, and `loopx check --scan-path docs/reference/protocols/loopx-turn-v0.md --scan-path docs/integrations/runtime-connector-catalog.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C71 | learning | Add a contributor-safe walkthrough from corpus health and candidate review through opt-in Agent Turn Recall, Reward Memory application, and scoped feedback. Use synthetic quota/todo packets, keep hints advisory, fail closed without activation, and prove agent/project/session scope without requiring an external sink or retaining provider payloads. | `python3 examples/reward-memory-corpus-registry-smoke.py`, `python3 examples/reward-memory-candidate-review-smoke.py`, `python3 examples/reward-memory-recall-application-smoke.py`, `python3 -m pytest -q tests/capabilities/test_agent_turn_recall.py`, and `loopx check --scan-path docs/capabilities/agent-turn-recall --scan-path docs/reference/protocols/reward-memory-architecture-v0.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C76 | workflow | Add a thin public CLI smoke for the shipped local integration-branch capability. Cover ignored plan state, read-only preview, ordered source updates, reviewed-candidate adoption, and fail-closed dirty/conflict cases without fetching, pushing, rewriting source branches, or changing protected bases. | New focused smoke, `python3 -m pytest -q tests/capabilities/test_integration_branch.py`, and `loopx check --scan-path docs/capabilities/integration-branch --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C77 | validation / showcase | Make the Auto Research KNN evidence-normalization smoke deterministic across supported CI hosts. Replace wall-clock speedup as the test oracle with a semantics-derived fixture or calibrated deterministic contract while preserving improved/contradicted evidence normalization and protected-scope checks. | Repeat `python3 examples/auto-research-knn-evidence-normalization-smoke.py` across supported Python versions, run `python3 examples/auto-research-demo-e2e-worker-loop-smoke.py`, and use `loopx check --scan-path examples/auto-research-knn-evidence-normalization-smoke.py --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C78 | productization | Add a public synthetic walkthrough for `content_ops_item_v0`: stable item identity, revision-bound approval invalidation, delivery/readback receipts, and supersession. Keep provider calls, draft bodies, credentials, private locators, and publish authority outside the fixture. | `python3 -m pytest -q tests/test_content_ops_item_lifecycle.py` and `loopx check --scan-path docs/capabilities/content-ops --scan-path docs/reference/protocols/content-ops-item-lifecycle-v0.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C79 | validation / onboarding | Make agent onboarding skill-delivery expectations follow the canonical release and active project-skill manifests. Cover the newly shipped PR program skill, missing/stale skill readback, and custom-host delivery without deriving the expected set from ambient global installations or hard-coding an old list. | `python3 examples/control_plane/agent-onboard-host-loop-activation-smoke.py`, `python3 examples/control_plane/peer-agent-runtime-v1-smoke.py`, focused project-skill delivery pytest, and `loopx check --scan-path loopx/agent_onboarding.py --scan-path examples/control_plane/agent-onboard-host-loop-activation-smoke.py --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C81 | workflow | Add a public synthetic walkthrough for provider-neutral PR program tracking: stable program identity, observed head snapshots, compact diff classification, review/CI transition lineage, and fail-closed unknown state. Keep provider payloads, review bodies, credentials, local paths, and merge authority outside the snapshot. | `python3 -m pytest -q tests/test_pr_program_snapshot_diff.py`, a focused skill script fixture, and `loopx check --scan-path skills/loopx-pr-program --scan-path CONTRIBUTOR_TASKS.md` |

### Advanced Implementation

Shared-state, adapter, or benchmark-control changes. Please open an issue first
and keep the first PR as a narrow slice.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C07 | state | Add structured-state write serialization for todo/refresh/history writers using a per-goal lock or optimistic revision guard. Include a concurrent todo add/update regression. | New concurrency regression plus `python3 -m py_compile loopx/*.py` |
| GH-C15 | benchmark | Implement benchmark ledger drift warning: when compact run history has a benchmark result but `benchmark-run-ledger.json/md` lacks the row, status should warn or closeout should auto-upsert. Keep raw task/log/trajectory material out. | `python3 examples/benchmark-run-ledger-smoke.py` |
| GH-C16 | benchmark | Add a public-safe trajectory-summary contract for non-SkillsBench adapters so Terminal-Bench/SWE/ALE can expose comparable counters without raw task text, logs, verifier output, or trajectory bodies. | New unit/fake fixture smoke |
| GH-C47 | state | Adopt the shipped optional `task_lease_v0` in one real host integration: advertise the capability explicitly, preserve soft-claim routing, expose acquire/renew/transfer/release outcomes, and prove overlapping write scopes fail without making `quota should-run` enforce undeclared lease authority. | `python3 examples/control_plane/task-lease-runtime-smoke.py`, `python3 -m pytest -q tests/control_plane/test_task_lease.py`, and a host-focused fake fixture |

### Design / RFC

Direction-setting work. These tasks should usually produce a doc or issue
before implementation.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C35 | integration | Design the next provider-neutral external-host adapter on top of LoopX Turn and TurnEnvelope, using the shipped external worker, Pi, and TraeX routes as conformance examples rather than special cases. Map compact session events into requests, planned effects, committed receipts, independent validation, recovery, and attention items while keeping raw transcripts, credentials, billing, permissions, and product frontstage outside LoopX. | Public design note with adapter-neutral fake-host smoke plan plus `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C37 | interaction model | Curate the interaction pattern catalog with one new public-safe good/bad case, including trigger signals, user channel, agent channel, state contract, bad smell, and validation reference. Do not copy raw chat, private benchmark artifacts, or internal links. | `loopx check --scan-path docs/concepts/interaction-pattern-catalog.md` |

### Maintainer-Owned / Coordination Required

Visible work that should not be duplicated. Ask for a public helper slice
instead of launching private runs or broad product changes.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C72 | workflow runtime | The pure Turn Loop Controller and its fail-closed repair remain maintainer-owned even though host-loop activation, the external worker, Pi, and TraeX integrations are shipped. Do not duplicate the controller. Public helpers may independently review decision-table semantics or propose synthetic malformed-receipt/cross-host fixtures; do not launch hosts, alter scheduler ownership, or weaken validation to make a candidate pass. | Maintainer-run focused controller pytest, LoopX Turn transaction tests, autonomous-replan smoke, and risk-based premerge canary |
| GH-C67 | issue-fix | The first operator rendering of `issue_fix_outcome_projection_v0` is an active coordination lane. Do not build a competing case ledger or operator surface. Ask for a synthetic fixture, accessibility, or projection-parity helper slice that keeps provider, sink, and private notification state out. | `python3 examples/issue-fix-outcome-projection-smoke.py`, the selected public surface smoke, and `loopx check --scan-path docs/capabilities/issue-fix --scan-path CONTRIBUTOR_TASKS.md` |
| GH-C18 | benchmark | Long-horizon benchmark evidence program, including live local no-upload cases, runner contracts, trace retention, score accounting, and good/bad case attribution. Do not duplicate live runs or inspect private artifacts unless maintainers split out a public helper issue. | Maintainer-run benchmark ledger and public/private scan |
| GH-C19 | benchmark | Main-table SkillsBench product-mode comparison: raw Codex autonomous max5 versus the qualified LoopX Turn route, no verifier feedback to either arm, stop on reward 1 or declared done. Scoring stays held until a fresh task-free runner lifecycle receipt proves readiness. Live matched pairs and official/countable receipt review remain maintainer-owned; external contributors can help with synthetic schema, docs, reducers, and smokes only. | Maintainer-run readiness receipt, compact ledger, case-analysis update, and public receipt/boundary scan |

## Projection Sources

This board is maintained from public-safe projections of:

- the local `loopx-meta` Agent Todo list;
- public docs under `docs/`, especially the state interaction model, status
  data contract, quota allocation, integration guide, product vision, and
  benchmark research docs;
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
