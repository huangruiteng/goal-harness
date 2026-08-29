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

## Current Technical Directions

The canonical [Technical Directions map](../project/technical-directions.md)
explains outcomes, maturity, ownership boundaries, and promotion gates. This
board lists bounded work; it does not redefine those directions.

| Direction | Current stage | Contributor entry | Boundary |
| --- | --- | --- | --- |
| Long-Horizon Benchmarks and Evidence | Active research | [#3243](https://github.com/huangruiteng/loopx/issues/3243) | Work on public-safe fixtures, treatment integrity, reducers, and docs; live cases and scoring remain maintainer-owned. |
| Operator Surface and IM Integration | Incubating on `frontend-control-plane-im-prototype-rfc` | [#3244](https://github.com/huangruiteng/loopx/issues/3244) | State the target base branch; UI remains a projection and promotion to `main` is staged. |
| Shared Goal Authority and Cross-host Coordination | Stage 2 slice shipped (aggregate head, file provider, `claim_work` executor); NoKV stays an unpromoted candidate | [#3245](https://github.com/huangruiteng/loopx/issues/3245) | Keep slices provider-neutral and file-backed; no second scheduler or write authority. |
| Architecture and Research Incubator | Mixed by RFC | [#3246](https://github.com/huangruiteng/loopx/issues/3246) | Read the per-exploration stage; an RFC alone does not make implementation claimable. |

Core control-plane reliability remains the shared shipped foundation. Effect
Program hardening, verified transitions, recovery, observability,
maintainability, and contributor experience continue through the focused rows
below and the existing `control-plane` label.

## Priority Queue

| Priority | Direction | Slice | Issue / PR | Status |
| --- | --- | --- | --- | --- |
| P0 | Core hardening | Complete exact-head review of remote execution and terminal writeback fencing | #3074 | Claimed |
| P0 | Core hardening | Wire caller-approved `validation_command` into the remaining self-report entry points | #3082 / #3142 #3291 #3343 | Done |
| P1 | Benchmark evidence | Add one deterministic fixture for the four-arm study contract or orchestrator runtime provenance | GH-C99 | Available |
| P1 | Benchmark evidence | Split one deterministic adapter-fidelity or treatment-integrity fixture | #3243 | Needs design |
| P1 | Operator surface / IM | Split one projection or session-contract characterization unit from the incubation branch | #3244 | Needs design |
| P1 | Shared coordination | Characterize the shipped file-backed `claim_work` executor with a provider-neutral parity fixture | #3245 | Needs design |
| P1 | Core hardening | One budget-aware CLI output ergonomics slice | #2881 | Needs design |
| P2 | Project docs | Release docs install, activation, and recovery guidance through v0.5.4 | GH-C04 | Available |
| P2 | Maintainability | CLI ownership and hot-module extraction | GH-C06 | Available |

## Product Manager Cut

LoopX is converging from a control-plane library into a management surface for
long-running agent work. Product-capability contributions should prefer slices
that make existing kernel objects understandable to users instead of adding
another source of truth.

| Product slice | Current substrate | Contributor-sized next cut |
| --- | --- | --- |
| Management frontstage | Goals, todos, gates, claims, evidence, quota, run history, `goal_channel_projection_v0`, `task_graph_projection_v0`, `issue_fix_outcome_projection_v0`, `agent_management_projection_v0`, and same-source Explore views are already compact read models. The public homepage, hosted docs, and localized dashboard now expose these surfaces. | Translate the read models into stable operator concepts such as work item, owner, decision, evidence, budget, risk, and next action; preserve lineage, keep raw machine fields in drill-downs, and do not create a second task or case store. Changes to a public first viewport remain maintainer-preview work. |
| Conversational commands | The four canonical global manager CLI commands are shipped: `/loopx-global-summary`, `/loopx-global-gates`, `/loopx-global-todos`, and `/loopx-global-risks`; legacy `/loop-global-*` forms are only migration aliases. | Keep their focused read-only contracts and public-safe smokes aligned. `/loop-goal-summary` remains host-only and outside this contributor slice; do not invent another manager command or alias family. |
| Runtime connector modes | `host_mode_plan_v0` selects visible, isolated-headless, gateway, service, and hybrid modes over the connector catalog. Host-loop activation now covers Codex surfaces, Claude Code, OpenCode 1/2 goal loops, TraeX, Pi, Gemini, Cursor, DeepSeek Harness, and custom agents; a scheduler-hint-aware external worker demonstrates one signed headless route. LoopX Turn remains one isolated request/effect/receipt transaction rather than a recurring loop. | Add one provider-neutral parity slice for route preservation, skill delivery/readback, continuation deadlines, signed primary actions, or stage/receipt visibility. Keep host wake/process ownership outside LoopX core and do not create a second scheduler or duplicate controller. |
| Planner-worker mode | The experimental planner-worker contract now supports one bounded plan, one selected worker step, an allowlisted validation set, a clean-worktree boundary, and a typed receipt; the TraeX probe is only one extension provider. | Add provider-neutral usage and failure guidance around the shipped fake runtime. Keep model routing explicit, validation caller-approved, and recurring scheduling or broad multi-agent orchestration outside this mode. |
| Visible governance | Quota, scheduler hints, authoritative interaction contracts, decision scopes, user gates, peer claims, optional task leases, a repository change-window gate with a pending ledger (#3319), interface budgets, and provider-neutral PR program snapshots already exist in machine contracts. A shared-goal authority/state-provider RFC now defines the next coordination boundary without making the proposal runtime authority. | Show who can act, who must approve, which decision scope applies, what budget was spent, and how pause/override/terminate decisions map back to LoopX state; add one provider-neutral negative fixture proving a locked repository window rejects writes and pending ledger rows resolve with a typed lifecycle after merge or close. Keep proposal state, claims, leases, and PR program observations from becoming a new runtime hierarchy or write authority. |
| Decision and material quality | Decision Context and Material Lifecycle are experimental, built-in, default-off capabilities. They separate revision-bound evidence, advisory proposals, material planning, owner-gated apply, and private cursor/source state. | Build synthetic, no-provider walkthroughs that make these boundaries visible. Do not add private adapters, source bodies, provider payloads, or a second lifecycle store. |
| Memory and content workflows | Agent Turn Recall composes quota-selected work with scoped Reward Memory whose post-outcome utility attribution is advisory and read-only (#3280), while `content_ops_item_v0` preserves stable item identity, revision-bound approval, delivery/readback receipts, and supersession. Both remain advisory or preview-level and add no provider authority. | Add synthetic walkthroughs and negative fixtures that prove identity, revision, and failure boundaries. Keep provider payloads, draft bodies, credentials, raw sessions, and external writes outside LoopX state. |
| Extensions and change qualification | Standalone `extension init` scaffolding and managed zero-permission execution demonstrate optional provider delivery; a `loopx-repo-health` provider publishes public repository-health snapshots (#3272). Exact-diff Change Quality is separately goal-scoped, simplify-first, and enforced through fresh receipts when enabled. | Improve one existing provider or validation seam at a time. Do not invent a capability for installability, auto-run discovered repository tasks, or weaken exact-scope receipt checks. |

## Recent Maintainer Progress

These public milestones changed which tasks are still useful contributor entry
points:

| Area | Landed | Contributor implication |
| --- | --- | --- |
| Turn and settlement | Typed settlement now covers CLI, Codex App, task leases, and todo completion: caller-approved `validation_command` commits verified completion receipts (#3142), user-role done updates run the same declared gate (#3291, #3293), and MCP `complete_task` inherits that gate with a pinned negative fixture (#3343), closing GH-C85 / #3082. A shared typed settlement receipt-chain driver unifies replay (#3199), M7 parity fixtures plus a read-only journal inspection/`interpret_turn_journal` lens shipped (#3189, #3193, #3205), per-todo validation timeouts override the 20s default (#3210), and replan typed semantic exits settle exhausted-goal and future-monitor reentry (#3213). Failed-session recovery now resumes preserved sessions without weakening drift checks (#3262, #3266) and same-turn terminal closeout recovers (#3261), closing #3228; ambiguous quota-spend retries and terminal no-followup ordering are also settled (#3258, #3250). Receipt-bound monitor settlement now closes deterministically and governed continuous-monitor proposals settle in the Kernel (#3513, #3511); replaying a completed heartbeat turn returns `heartbeat_settled_skip` with no re-spend and no successor conflict when its completion, writeback, and spend receipts exist (#3578, closing #3567). Post-v0.5.3, settlement readback is consolidated into the typed TypeScript boundary with per-effect reduction cases pinned, successor Turn outcomes validate, non-completion terminal closeout is rejected, and a turn survives capability re-entry. Fencing remote execution and terminal writeback (#3074) is still under review. | Add receipt-chain drift or replay-identity negatives on the shared driver. No second settlement ledger, model call, or double quota spend. |
| Effect program runtime | A shared typed Effect Program drives quota, Turn, task-lease, and todo-completion settlement. The Dev Book course teaches the current runtime (#3097), M7.1 parity fixtures and the read-only replay lens shipped (#3189, #3193), and the turn driver is the second consumer of the settlement algebra. The TypeScript control-plane migration has entered its transaction payoff phase (#3447): settlement (#3464), delivery routing (#3481), the scheduler transition kernel (#3434), and todo completion (#3530) now cut over to typed TypeScript transactions, and receipt-bound phase classification moves into the typed quota boundary (#3578). The scheduler remains outside settlement. | Add receipt-chain drift or replay-identity negative cases on the shared driver; do not extract a shared executor until two adapters share execution ownership or build an interpreter protocol before both consume the same plan/receipt algebra. |
| Review quality | PR review now requires scope-fit evidence for production surface changes (#3090), the execution contract carries four self-dev review lenses (#3123), example-only PRs need durable smoke-value evidence (#3134), and age-fair exact-head scheduling persists across restarts (#3317). | Add synthetic conformance and negative cases around scope-fit evidence, causal chains, exact-head review packets, and durable-smoke-value claims. |
| Task leases | Typed task-lease CLI with preserved legacy error codes landed (#3095); on-disk hard leases surface in goal-channel projection (#3039); Turn fencing uses lease fences plus an append-only journal, and the OpenCode 2 goal worker fences its own live worker lease. A task-lease generation ABA fix shipped (#3393), a Pi `loopx_task_lease` facade over the shipped `task_lease_v0` CLI merged (#3559, closing #3549), and task-lease settlement cut over to TypeScript (#3674). | Adopt the same facade in one more real host integration (for example TraeX) or add a transfer/overlap-write-scope fixture. Keep soft-claim routing and undeclared-lease authority unchanged. |
| Status, quota, monitors | Replan context is host-projected from the evidence ledger; two equivalent typed progress observations create an obligation, maintenance writes fail closed against the same full goal-frontier reducer used by quota, and an exact runnable-successor Todo carries the obligation-bound semantic receipt and turn boundary. Heartbeat todos survive capability reentry (#3321), Todo identity filtering and UTC ordering are corrected (#3311), unbound `/loopx` sessions inherit existing agent identity (#3315), declared validation gates run on user-role done updates (#3291, #3293), quota guards follow the selected Todo (#3506), and a bounded fallback action portfolio keeps quota decisions actionable (#3514). Guided start is bound to one turn (#3572), stale generated Next Actions rebind to the current todo (#3524), unknown workspace causality is repairable (#3519), malformed runtime recovery and settlement payloads fail closed (#3525), and managed and queued turn creation are serialized (#3542, #3562). Post-v0.5.3, `todo list` gained a bounded thin projection with an output-budget cap (#3679), and the dashboard projects completed Todos with done-count run progress (#3689). Manual evidence reads, prose ACKs, and historical repair-delta claims are diagnostic only. Compact scheduler-hint and heartbeat-prompt budgets plus todo-detail cold paths remain the reference. | Extend one measured performance, detail-readback, lock-timeout, malformed-state, typed progress, or obligation-bound semantic-transition case. Keep default output bounded and cold-path detail available. |
| Governance and productization | A synthetic visible-governance slice landed (#3086); decision-context evidence cursors settle (#3079); the React homepage rebuild (#3098) landed; a deterministic project registry (#3170) serializes global sync; per-goal handoff mode gates claim/lease authority (#3164) and hard-lease gates auto-acquire completion keys (#3198); a repository change-window gate and pending ledger ship (#3319); goal channels default to human-gate auto-notify on new channels (#3523); coordination state rules are centralized (#3410) and the Stage 2 slice ships an aggregate head, file provider, and `claim_work` executor (#3529); project repository delivery lands through capability hooks (#3570) with gitless delivery workspaces settled (#3574) and CPA/provider-routing qualification recorded (#3576, #3573, #3563); a read-only stride shadow observation M1 (#3207), a synthetic stride-boundary shadow fixture (#3290), and the hierarchical stride RFC (#3204) open the next boundary; goal-artifact lifecycle projection (#3136) proposes a read-model boundary and post-outcome memory utility attribution from RFC #3215 is implemented (#3280). | Add one synthetic lifecycle or stride-boundary fixture, extend the visible-governance walkthrough with a missing negative case, or characterize the shipped `claim_work` executor with a file-backed parity fixture. Keep activation explicit and leave source bodies, draft bodies, review text, provider payloads, private locators, cursor state, and apply/publish authority outside public fixtures. |
| Security boundaries | Four merged hardening fixes contain state-file override writes (#3140), reject shell metacharacters in launcher worker commands (#3139), validate `goal_id` in reward routes (#3138), and stop ACAO:* on unauthenticated status reads (#3137). Loopback CORS, worker-command charset, and state-file symlink containment are pinned as regression tests (#3340). GH-C90 audited the four shipped negative fixtures and added one durable mutation per boundary: path-prefix sibling containment, worker-command input redirect, absolute `goal_id` path segments, and `file://localhost` ACAO rejection (`tests/test_state_file_containment.py`, `tests/test_worker_command_validation.py`, `tests/test_feedback_goal_id_validation.py`, `tests/test_status_server_cors.py`), completing the GH-C90 slice (#3636). | Keep credentials, private reproduction details, and advisory coordination out of public fixtures; extend only when a new shipped boundary lacks a distinct fail-closed mutation. |
| Runtime connectors and content workflows | DeepSeek Harness Turn adapter with real e2e smoke landed (#3188); OpenCode 1 and OpenCode 2 continuous goal loops ship (#3151); content-ops gained a layout template library and dense-cover defaults (#3222, #3223); provider-neutral PR program snapshots ship (#2814); `computer_use_runtime_v0` is now a machine-checkable protocol contract (#3279); a `loopx-community-discussion` public source provider (#3299) and a `loopx-repo-health` provider (#3272) extend public source coverage; goal-channel botmux runtime integration lands with terminal dispatches preserved and uncertain dispatches persisted, desktop chat routes through a loopback service, chat-wide routing and contextual inbox replies land (#3555), and managed and queued turn creation are serialized (#3542, #3562); the desktop added workspace language settings, localized write previews, and preserved heartbeat schedule and off-hours semantics (#3594); host parity, skill-delivery, and observable-handle thin pytest now cover the expanded host list. | Add one provider-neutral parity slice for DeepSeek Harness, OpenCode 1/2, goal-channel botmux, content-ops delivery/readback, or desktop locale parity; keep raw transcripts, provider payloads, credentials, and host-local paths out of fixtures. |
| Benchmark boundary | Benchmark research was reset around native runners (#3267): native Codex Goal connects to the real runtime (#3271), workers are isolated from the host (#3277), provider env binds to installed Goal profiles (#3276) with formally verified treatments (#3275) and live continuations (#3273), runtime evidence binds to the exact container (#3303), a post-run case analyst brief ships (#3289), an integrity qualification toolkit landed (#3241), source-env usage is distinguished from credential probes (#3298, #3278), and accountable closeout requires Todo validation (#3229). A provider-neutral four-arm study contract ships (#3516) with treatment plans qualified by typed action roles (#3507), restricted task-source access (#3504), non-http git clones classified as network with loopback integrity probes allowed (#3510), namespaced public case ids (#3532), locked git-clone integrity boundaries (#3515), orchestrator runtime provenance, and fail-closed runtime closeout drift (#3503). Public native Goal trajectory summaries now derive from compact lifecycle facts without retaining raw artifacts (#3327), completing the GH-C16 slice. Shared lifecycle, readiness, ledger, and reducer contracts remain the public seam; generic Effect Program conformance and replay tests harden settlement infrastructure but do not change benchmark scoring or authorize live runs. Live scored comparisons stay held until a fresh task-free runner lifecycle receipt proves readiness. | Extend synthetic setup/termination attribution, add one deterministic fixture for the four-arm contract or runtime provenance (GH-C99), derive the public trajectory summary for a second non-SkillsBench adapter, or add a SWE adapter only when a second SWE route needs shared launch/observe/ingest behavior. Do not launch scoring, duplicate the controller, or expose raw task text, logs, trajectories, verifier tails, credentials, uploads, or local paths. |
| Validation and change quality | Python tests are green on the latest runtime-bearing `main` change; public smoke parity and the frontstage Pages build are restored, with Codex App fallback receipt identity isolated (#3233); public smoke reliability was restored again (#3302), stargazer history now fetches through REST (#3320), and a repository-hygiene smoke plus release-timeline ratchet landed (#3249). The KNN timing oracle still needs deterministic coverage. | Replace timing as a semantic oracle, retain negative/mutation coverage, and distinguish infrastructure outages from product regressions. Keep live model/provider checks explicit and low-frequency. |
| Release and install | v0.5.3 is the latest public tag and package version (v0.5.0-v0.5.3 landed after the last board refresh). PyPI remains the default complete install path (#3301) with explicit installation ownership (#3566); canonical project links are published (#3253), derived capability/manpage surfaces are synced (#3254), exact Miaoda releases are verified in periodic-report receipts (#3508) with governed delivery (#3401), extension doctor readiness recovers across releases (#3556), and the public release timeline covers v0.1.3 through v0.5.3. | Keep install, activation, and recovery guidance aligned with the PyPI default and tagged stable versus post-tag `main`, and continue contributor-safe update recovery without adding a parallel release checklist. |
| Public docs and onboarding | Hosted docs, a public homepage, the Dev Book, localized dashboard copy, public/private boundary examples, GitHub issue forms, and a PR/issue label taxonomy have landed. Slash-command installation now exposes all four canonical global manager commands through their shipped CLI wrappers; fresh-project onboarding and its regression fixture landed (#3093, #3103), and harness-above positioning (#3202), ecosystem adoption and derivatives inventory (#3224), GitHub maintenance and ops automation best practices (#3227), long-horizon/commercialization strategy docs (#3217-#3220), the TypeScript control-plane migration RFC (#3226), the open strategy review process (#3295), stale-issue reminders without auto-close (#3297), welcome-all-contribution-shapes guidance (#3294), consolidated community policy (#3238), Apache-2.0 open-core adoption (#3235), a capability implementation code map (#3252) with co-located docs (#3265), outcome/extension path clarifications (#3242), the NoKV semantic-authority RFC (#3263), the long-horizon benchmark research program RFC (#3240), the published technical directions (#3248), and a DCO sign-off reminder (#3316) are public. | Keep contributor, release, protocol, course, showcase, and RFC surfaces concise and linked to public evidence; add navigation, locale, and RFC-compatibility checks without appending status narratives or aliases. |

## Turn Loop Controller Plan

`loopx turn run-once` remains the atomic governed executor: decide, execute one
bounded host segment, validate independently, write back, spend once, and
project the latest scheduler contract. Host-loop activation, the external
scheduler worker, and visible Pi/TraeX integrations provide concrete outer
loops, but they do not make LoopX a resident scheduler. The maintainer-owned
pure controller and replan transition are still in hardening, so contributors
should focus on independently derived decision tables, cross-host parity,
fail-closed fixtures, or docs that clarify the boundary below.

| Priority | Planned slice | Required boundary and proof |
| --- | --- | --- |
| P0 | Harden the maintainer-owned pure Turn Loop Controller transition contract over one typed settlement receipt plus a fresh quota/scheduler decision. | Return exactly one typed disposition such as `run_now`, `wait`, `user_action_required`, `repair`, `replan`, or `terminal`; reject malformed receipts, legacy plans without a typed settlement, stale continuation, and invalid budgets without invoking a model, sleeping, mutating a host scheduler, writing state, or spending quota. |
| P0 | Make `replan_required` a real continuation boundary. | Before another Turn, write a bounded todo or vision delta, obtain a fresh TurnEnvelope, and preserve the causal agent/todo frontier. Never rerun the same stale todo merely because a host session is resumable. Reuse the existing autonomous-replan and two-stall contracts. |
| P1 | Qualify host-loop activation and skill-delivery parity. | Compare Codex, Claude Code, OpenCode 1/2, TraeX, Pi, Gemini, Cursor, DeepSeek Harness, and custom-agent packets against one provider-neutral fixture. Required skills and readback must come from the canonical release/goal contract rather than ambient host state; install dedupe and cwd isolation keep canonical manifests the source of truth. |
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
| GH-C04 | docs | Keep release docs current through v0.5.4: align install, activation, and recovery guidance with the PyPI default complete install path (#3301) and explicit installation ownership (#3566), preserve tagged stable vs post-tag `main` and release-snapshot vs canary distinctions, cover installed-runtime activation recovery and extension-doctor readiness (#3556), and keep the public release timeline (v0.1.3-v0.5.3) in sync with tagged evidence instead of duplicating the release body's bilingual optional-capability usage guidance. | `python3 examples/fresh-clone-quickstart-smoke.py`, `python3 examples/loopx-update-smoke.py`, `python3 examples/release/release-readiness-doc-smoke.py`, `python3 examples/release/release-version-contract-smoke.py`, and `loopx check --scan-path docs/product/release-readiness.md --scan-path CONTRIBUTING.md` |
| GH-C80 | docs | Add a hosted-docs navigation and locale-parity check across `mkdocs.yaml`, `docs/index.md`, `docs/book/index.md`, the docs catalog, and stable README entry links. Catch broken or orphaned public pages without changing the README or homepage first viewport. | `python3 examples/docs-governance-smoke.py`, `python3 examples/frontstage-pages-workflow-smoke.py`, a strict MkDocs build, and `loopx check --scan-path docs --scan-path mkdocs.yaml --scan-path README.md --scan-path README.zh-CN.md` |
| GH-C64 | release docs | Add a contributor-safe atomic-promotion failure matrix around the shipped release lock/concurrency smoke: explain which failures happen before the symlink swap, how a waiter recovers, and when contributors must stop before maintainer-only promotion state. Extend the existing fixture only for a durable missing case. | `python3 examples/release/release-promotion-concurrency-smoke.py`, `python3 examples/release/local-install-promotion-boundary-smoke.py`, and `loopx check --scan-path docs/product/release-readiness.md --scan-path docs/development/contributor-tasks.md` |
| GH-C75 | runtime docs | Add a public operator guide for the experimental planner-worker mode using the shipped provider-neutral fake runtime. Explain the clean-worktree requirement, explicit model routes, caller-approved validation commands, one-step typed receipt, incomplete-cost semantics, provider opt-in, and how to stop without presenting it as a resident scheduler or default multi-agent runtime. | `python3 examples/experiments/planner_worker/contract-smoke.py`, `python3 examples/experiments/planner_worker/runtime-smoke.py`, and `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path docs/development/contributor-tasks.md` |

### Focused Implementation

Small-to-medium code changes with a clear validation surface. These are good
for contributors who can run local CLI smokes and keep changes scoped.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C06 | cli | Characterize one remaining oversized CLI ownership seam after the recent quota, status, todo, history, and scheduler command-plumbing extractions, then move only a cohesive command or rule group into its bounded module. Preserve public invocations, avoid compatibility wrappers without a real caller, and keep the module-size/import budget honest. | Command-specific smoke, `python3 examples/cli-command-module-size-ownership-command-modularization-smoke.py`, `python3 regression/cli-command-module-contract.py`, and focused pytest if rules move |
| GH-C85 | validation | **Done / shipped.** Caller-approved `validation_command` now gates every self-report completion entry point for #3082: todo completion (#3142), user-role done updates (#3291, #3293), and MCP `complete_task` via the shared `todo complete` path with a pinned negative fixture (#3343). No-command fast path stays unchanged; malformed or failing commands fail closed with a typed receipt. Evidence: `tests/control_plane/test_todo_completion_validation.py`, `tests/test_goal_mode_mcp_completion_validation.py`. | Shipped: `python3 -m pytest -q tests/control_plane/test_todo_completion_validation.py tests/test_goal_mode_mcp_completion_validation.py`, `python3 examples/loopx-turn-fake-host-walkthrough-smoke.py`, and `loopx check --scan-path loopx/capabilities/issue_fix --scan-path docs/development/contributor-tasks.md` |
| GH-C95 | cost ledger | Implement real per-run usage ingest for the cost ledger (#3163): read compact accounting rows from existing run history, keep the ledger the single source of truth, and fail closed on malformed or negative usage without provider payloads or a second ledger. A contributor PR is open (#3662); help by reviewing it at exact head against the ledger contract or by closing any remaining negative-coverage gap the review finds. | New focused pytest and `loopx check --scan-path docs/status-data-contract.md --scan-path docs/development/contributor-tasks.md` |
| GH-C88 | cli | Implement one budget-aware CLI output ergonomics slice for #2881: shorter default summaries with a typed `--json` escape hatch on one command family, keeping hot-path payload budgets and differential allowances intact. | `python3 examples/control_plane/cli-output-budget-regression-smoke.py`, focused command smoke, and `loopx check --scan-path docs/status-data-contract.md --scan-path docs/development/contributor-tasks.md` |
| GH-C97 | cli | Fix `todo add --note` being silently accepted but dropped: pass the note through the add command and state writer, project it on readback, and add focused CLI regression coverage. Open an issue with the contributor task template first. | `python3 examples/control_plane/todo-lifecycle-cli-smoke.py`, focused CLI regression pytest with a negative case, and `loopx check --scan-path docs/status-data-contract.md --scan-path docs/development/contributor-tasks.md` |
| GH-C43 | showcase | Add a contributor-facing walkthrough for the shipped Auto Research stop/takeover and state-aware wake transitions. Reuse the current command path and synthetic/redacted evidence; do not add a second launcher or alter the README first screen without maintainer preview. | `python3 examples/showcase-catalog-smoke.py`, `python3 examples/auto-research-demo-e2e-worker-loop-smoke.py`, `python3 examples/auto-research-visible-worker-hook-smoke.py`, `python3 examples/auto-research-stop-marker-smoke.py`, `python3 examples/auto-research-state-aware-wake-smoke.py`, `python3 examples/auto-research-quota-pause-smoke.py`, and `loopx check --scan-path docs/showcases --scan-path docs/guides` |
| GH-C49 | dashboard | Polish the shipped `/frontstage` goal-channel board: improve visual acceptance, local demo fixture clarity, and operator onboarding while keeping browser data read-only and making outcome, lease, capability-wait, and workspace-repair states legible. | `npm run smoke:frontstage-route`, `npm run smoke:frontstage-browser`, and `loopx check --scan-path apps/presentation/dashboard --scan-path docs/product/roadmaps/dashboard-frontend-selection.md` |
| GH-C74 | productization | Add one public synthetic walkthrough from a revision-bound Decision Context packet to a Material Lifecycle rerank preview. Prove stale/conflicting evidence stays visible, source bodies and private locators stay absent, and apply/cursor commits remain separate owner-gated actions. | `python3 examples/decision-context-contract-smoke.py`, `python3 examples/material-lifecycle-contract-smoke.py`, focused capability pytest, and `loopx check --scan-path loopx/capabilities/decision_context --scan-path loopx/capabilities/material_lifecycle --scan-path docs/development/contributor-tasks.md` |
| GH-C60 | workflow | Add one focused fake-fixture parity slice across Codex App heartbeat, Codex CLI TUI, LoopX Turn, Claude Code, OpenCode 1/2 goal loops, TraeX, Pi, Gemini, Cursor, Ark Managed Agent, DeepSeek Harness, the external shell worker, HTTP webhook, and worker bridge. Cover one missing explicit capability route, signed primary action, scoped identity, skill delivery/readback, typed Goal continuation, runtime-owned cadence, no-spend transition, workspace repair, or private-boundary case. | `python3 examples/host-mode-plan-smoke.py`, `python3 examples/project/host-mode-plan-cli-smoke.py`, `python3 examples/control_plane/agent-onboard-host-loop-activation-smoke.py`, focused host bridge tests, `python3 -m pytest -q tests/test_host_parity_smoke.py tests/test_skill_delivery_parity.py tests/test_loopx_turn_transaction.py tests/test_external_scheduler_worker.py tests/test_pi_goal_mode.py tests/test_gemini_cursor_host_surfaces.py`, and `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path docs/reference/protocols/host-mode-plan-v0.md --scan-path docs/development/contributor-tasks.md` |
| GH-C62 | governance | Add a synthetic visible-governance slice that relates per-goal/per-agent claims, optional task leases, quota, scheduler hints, decision scopes, and the shared-goal RFC's proposed authority/state-provider boundary. Make proposal versus shipped truth explicit; do not add a browser write API, infer scopes from prose, or present provider observations or leases as runtime authority. | Focused fixture smoke, `python3 -m pytest -q tests/control_plane/test_todo_decision_scope_lifecycle.py`, and `loopx check --scan-path docs/status-data-contract.md --scan-path docs/architecture/rfcs/shared-goal-authority-state-provider-v0.md --scan-path docs/development/contributor-tasks.md` |
| GH-C70 | runtime | Add a provider-neutral host-loop parity walkthrough that runs the same synthetic task through the external scheduler worker plus one visible host such as Pi or TraeX. Compare signed action selection, compact Turn receipts, independent validation, recoverable timeout/termination, replan, and terminal no-followup behavior without retaining raw sessions or host-local paths. | Focused fake-host smoke, `python3 -m pytest -q tests/test_loopx_turn_driver.py tests/test_external_scheduler_worker.py tests/test_pi_goal_mode.py`, and `loopx check --scan-path docs/reference/protocols/loopx-turn-v0.md --scan-path docs/integrations/runtime-connector-catalog.md --scan-path docs/development/contributor-tasks.md` |
| GH-C71 | learning | Add a contributor-safe walkthrough from corpus health and candidate review through opt-in Agent Turn Recall, Reward Memory application, and scoped feedback. Use synthetic quota/todo packets, keep hints advisory, fail closed without activation, and prove agent/project/session scope without requiring an external sink or retaining provider payloads. | `python3 examples/reward-memory-corpus-registry-smoke.py`, `python3 examples/reward-memory-candidate-review-smoke.py`, `python3 examples/reward-memory-recall-application-smoke.py`, `python3 -m pytest -q tests/capabilities/test_agent_turn_recall.py`, and `loopx check --scan-path loopx/capabilities/agent_turn_recall --scan-path loopx/capabilities/reward_memory/README.md --scan-path docs/development/contributor-tasks.md` |
| GH-C76 | workflow | Done: the thin public CLI smoke is shipped as `examples/integration-branch-cli-smoke.py` (with lifecycle tests in `tests/capabilities/test_integration_branch.py`). It covers ignored plan state, read-only preview, ordered source updates, reviewed-candidate adoption, and fail-closed dirty/conflict cases without fetching, pushing, rewriting source branches, or changing protected bases. Keep board/docs validation aligned with that smoke. | `python3 examples/integration-branch-cli-smoke.py`, `python3 -m pytest -q tests/capabilities/test_integration_branch.py`, and `loopx check --scan-path loopx/capabilities/integration_branch --scan-path docs/development/contributor-tasks.md` |
| GH-C77 | validation / showcase | Make the Auto Research KNN evidence-normalization smoke deterministic across supported CI hosts. Replace wall-clock speedup as the test oracle with a semantics-derived fixture or calibrated deterministic contract while preserving improved/contradicted evidence normalization and protected-scope checks. | Repeat `python3 examples/auto-research-knn-evidence-normalization-smoke.py` across supported Python versions, run `python3 examples/auto-research-demo-e2e-worker-loop-smoke.py`, and use `loopx check --scan-path examples/auto-research-knn-evidence-normalization-smoke.py --scan-path docs/development/contributor-tasks.md` |
| GH-C99 | benchmark | Add one deterministic, provider-neutral fixture for the shipped four-arm study contract (#3516) or orchestrator runtime provenance: qualify typed action roles, restricted task-source access, network classification, and fail-closed runtime closeout drift on synthetic lifecycle facts, without live runs, scoring, uploads, or submissions. | Focused pytest against `loopx/capabilities/benchmark_toolkit/`, and `loopx check --scan-path loopx/capabilities/benchmark_toolkit --scan-path docs/development/contributor-tasks.md` |

### Advanced Implementation

Shared-state, adapter, or benchmark-control changes. Please open an issue first
and keep the first PR as a narrow slice.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C07 | state | Global registry sync now writes inside a lock (`tests/test_global_registry_write_serialization.py`); extend the same lock or optimistic-revision guard to per-goal todo/refresh/history writers and include a concurrent todo add/update regression. | New concurrency regression plus `python3 -m py_compile loopx/*.py` |
| GH-C47 | state | Task leases now back Turn fencing and typed CLI acquire/release, the OpenCode 2 goal worker fences its own live worker lease, a lease generation ABA fix is shipped (#3393), and a Pi `loopx_task_lease` facade over the shipped `task_lease_v0` CLI merged (#3559, closing #3549); claim coordination lives there. Adopt the same facade in one more real host integration (for example TraeX): advertise the capability explicitly, preserve soft-claim routing, expose acquire/renew/transfer/release outcomes, and prove overlapping write scopes fail without making `quota should-run` enforce undeclared lease authority. | `python3 examples/control_plane/task-lease-runtime-smoke.py`, `python3 -m pytest -q tests/control_plane/test_task_lease.py tests/test_loopx_turn_driver.py`, and a host-focused fake fixture |

### Design / RFC

Direction-setting work. These tasks should usually produce a doc or issue
before implementation.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C89 | governance | Respond to the AGE-style attractor proposal (#2831): anchor goal direction to repository owner docs so the control plane can validate semantic drift, not just execution state. Define the read boundary, the drift signal, and what must remain advisory; do not make repository docs a write authority. | Public design note with a synthetic drift fixture plan plus `loopx check --scan-path docs/architecture/rfcs --scan-path docs/development/contributor-tasks.md` |
| GH-C96 | design / migration | Review the TypeScript control-plane migration RFC (#3225, #3226) for compatibility completeness: verify typed state rules, domain neutrality, behavior-change disclosure, and the public/private boundary, then publish concise migration-compatibility notes without starting the migration. | `python3 examples/docs-governance-smoke.py` and `loopx check --scan-path docs/architecture/rfcs/typescript-control-plane-migration-v0.md --scan-path docs/development/contributor-tasks.md` |
| GH-C35 | integration | Design the next provider-neutral external-host adapter on top of LoopX Turn and TurnEnvelope, using the shipped external worker, Pi, and TraeX routes as conformance examples rather than special cases. Map compact session events into requests, planned effects, committed receipts, independent validation, recovery, and attention items while keeping raw transcripts, credentials, billing, permissions, and product frontstage outside LoopX. | Public design note with adapter-neutral fake-host smoke plan plus `loopx check --scan-path docs/integrations/runtime-connector-catalog.md --scan-path docs/development/contributor-tasks.md` |
| GH-C37 | interaction model | Curate the interaction pattern catalog with one new public-safe good/bad case, including trigger signals, user channel, agent channel, state contract, bad smell, and validation reference. Do not copy raw chat, private benchmark artifacts, or internal links. | `loopx check --scan-path docs/concepts/interaction-pattern-catalog.md` |

### Maintainer-Owned / Coordination Required

Visible work that should not be duplicated. Ask for a public helper slice
instead of launching private runs or broad product changes.

| ID | Area | Task | Validation |
| --- | --- | --- | --- |
| GH-C72 | workflow runtime | The pure Turn Loop Controller and its fail-closed repair remain maintainer-owned even though host-loop activation, the external worker, Pi, TraeX, and typed settlement are shipped. Do not duplicate the controller. Public helpers may independently review decision-table semantics or propose synthetic malformed-receipt/cross-host fixtures; do not launch hosts, alter scheduler ownership, or weaken validation to make a candidate pass. | Maintainer-run focused controller pytest, LoopX Turn transaction tests, autonomous-replan and bounded monitor no-change smokes, and risk-based premerge canary |
| GH-C67 | issue-fix | The first operator rendering of `issue_fix_outcome_projection_v0` is an active coordination lane. Do not build a competing case ledger or operator surface. Ask for a synthetic fixture, accessibility, or projection-parity helper slice that keeps provider, sink, and private notification state out. | `python3 examples/issue-fix-outcome-projection-smoke.py`, the selected public surface smoke, and `loopx check --scan-path loopx/capabilities/issue_fix --scan-path docs/development/contributor-tasks.md` |
| GH-C18 | benchmark | Long-horizon benchmark evidence program, including live local no-upload cases, runner contracts, trace retention, score accounting, and good/bad case attribution. Do not duplicate live runs or inspect private artifacts unless maintainers split out a public helper issue. | Maintainer-run benchmark ledger and public/private scan |
| GH-C19 | benchmark | Main-table SkillsBench product-mode comparison: raw Codex autonomous max5 versus the qualified LoopX Turn route, no verifier feedback to either arm, stop on reward 1 or declared done. Scoring stays held until a fresh task-free runner lifecycle receipt proves readiness; the native-runner research reset (#3267) and the shipped public trajectory summary seam (#3327) define the current public helper boundaries. Live matched pairs and official/countable receipt review remain maintainer-owned; external contributors can help with synthetic schema, docs, reducers, and smokes only. | Maintainer-run readiness receipt, compact ledger, case-analysis update, and public receipt/boundary scan |

## Projection Sources

This board is maintained from public-safe projections of:

- the local `loopx-meta` Agent Todo list;
- public docs under `docs/`, especially the state interaction model, status
  data contract, quota allocation, integration guide, product vision, the
  repository change-window gate contract (#3319), the TypeScript transaction
  payoff phase (#3447), benchmark research docs (including the four-arm study
  contract #3516 and the public trajectory summary #3327), the goal artifact
  lifecycle projection RFC (#3136), the hierarchical stride, post-outcome
  memory utility, human-attention, and TypeScript migration RFCs, the Dev Book
  and control-plane course, and the PR/issue label taxonomy;
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

Use the public label taxonomy in `docs/operations/pr-issue-labels.md` when
opening or triaging issues:

- Lifecycle labels: `good first issue`, `help wanted`, `triage`,
  `workflow-audit`, `bug`, `enhancement`, `duplicate`, `question`,
  `invalid`, and `wontfix`.
- Area labels: `control-plane`, `benchmark-boundary`, `capability-extension`,
  `public-docs`, and `build-or-ci`.

Board states such as `claimed`, `maintainer-owned`, `needs design`, and
`blocked` are board statuses, not GitHub labels. Track them in issue comments
and through the `triage` or `workflow-audit` lifecycle labels.

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
