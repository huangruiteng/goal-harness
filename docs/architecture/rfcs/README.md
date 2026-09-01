# Architecture RFCs

Architecture RFCs are public design proposals. Each RFC should name its
decision boundary, non-goals, smallest useful implementation slice, and
validation criteria. An RFC may describe future work; current behavior is
defined by the implementation and stable reference contracts.

The [Current Technical Directions](../../project/technical-directions.md) page
maps RFCs to strategic programs, contribution routes, and promotion gates.

## How to read this index

RFC maturity and delivery maturity are different facts:

- **RFC status** records the decision state written in the RFC. `Draft` work
  remains open to architectural change even when a bounded slice has shipped.
- **Delivery on `main`** records the implementation state audited against the
  repository. A merged experiment does not make its whole RFC accepted, and an
  accepted RFC may still have later adoption work.
- **Current boundary** names what is real now and what is still excluded. It is
  a navigation aid, not a replacement for stable protocol documentation.

This matrix was last audited against `main` on **2026-09-01**. Update the RFC
row whenever its decision status, promoted behavior, or meaningful delivery
boundary changes.

## Status matrix

| RFC | RFC status | Delivery on `main` | Current boundary |
|---|---|---|---|
| [Agent Loop Effect Interpreter v0](agent-loop-effect-interpreter-v0.md) ([中文版](agent-loop-effect-interpreter-v0.zh-CN.md)) | Accepted | Core implemented; bounded adoption continues | Effect request, interpretation, observation, settlement, and typed Effect Program foundations are shipped. Replan planning/ACK stays domain-local until a second real lifecycle justifies extraction. |
| [TypeScript Control-Plane Migration v0](typescript-control-plane-migration-v0.md) ([中文版](typescript-control-plane-migration-v0.zh-CN.md)) | Accepted; transaction-payoff phase in progress | Substantially implemented; active migration | Stage 1 and 2A are complete. Stage 2B is cutting over whole semantic transactions and retiring Python facades under parity and differential gates. |
| [Provider-Neutral Turn-Start Inbox Hook v0](provider-neutral-turn-start-inbox-hook-v0.md) | Implemented behind explicit provider configuration | Implemented, opt-in | The provider-neutral turn-start read contract and Lark ACK/replay path shipped in [#3678](https://github.com/huangruiteng/loopx/pull/3678) and [#3733](https://github.com/huangruiteng/loopx/pull/3733); no provider is enabled implicitly. |
| [Per-Goal Usage, Token, and Cost Surfacing v0](goal-usage-token-cost-v0.md) | Draft | Core slice implemented | Codex usage capture, normalized aggregation, and dashboard surfacing shipped in [#3117](https://github.com/huangruiteng/loopx/pull/3117); broader runtime/provider coverage and cost semantics remain incomplete. |
| [Post-Outcome Memory Utility Attribution v0](post-outcome-memory-utility-attribution-v0.md) ([中文版](post-outcome-memory-utility-attribution-v0.zh-CN.md)) | Draft, under maintainer review | Stage 1 implemented | [#3280](https://github.com/huangruiteng/loopx/pull/3280) binds utility observations to verified outcomes without changing retrieval ranking. Reducer/read projection, provider readback, ranking influence, and pilot promotion remain open. |
| [Research Exploration Control Plane v0](research-exploration-control-plane-v0.md) ([中文版](research-exploration-control-plane-v0.zh-CN.md)) | Draft, under maintainer review | Partially implemented | The explicit composition projection and successor binding from M2 shipped in [#3173](https://github.com/huangruiteng/loopx/pull/3173). The canonical observation contract, shared write-time gate, model selection, and inferred triggers have not been promoted. |
| [Shared-goal Online Authority and Pluggable Coordination Provider v0](shared-goal-authority-state-provider-v0.md) ([中文版](shared-goal-authority-state-provider-v0.zh-CN.md), [validation boundary](shared-goal-authority-state-provider-v0-evidence.zh-CN.md)) | Draft, under maintainer review | Foundation and provider-contract slices implemented | Recoverable shared-authority foundations, the file-backed reference path, NoKV shadow/recovery evidence, and the TypeScript store contract are on `main` ([#3529](https://github.com/huangruiteng/loopx/pull/3529), [#3669](https://github.com/huangruiteng/loopx/pull/3669), [#3798](https://github.com/huangruiteng/loopx/pull/3798)). No remote provider is the promoted authority; PostgreSQL remains planned. |
| [Intelligent Review and Dynamic Presentation Surfaces v0](intelligent-review-presentation-surfaces-v0.md) ([中文版](intelligent-review-presentation-surfaces-v0.zh-CN.md)) | Draft, under maintainer review | Proposal only | Existing typed proposals, gates, planning projections, receipts, and direct reversible-action UX are inputs. The shared `action_review_plan_v0` compiler and dynamic card/report/wiki presentation contract have not shipped. |
| [Provider-Neutral Post-Writeback Capability Hooks v0](provider-neutral-post-writeback-capability-hooks-v0.md) ([中文版](provider-neutral-post-writeback-capability-hooks-v0.zh-CN.md)) | Draft, under maintainer review | First end-to-end vertical implemented | The periodic-report producer, durable intent lifecycle, terminal closeout dispatch, consumer, and approved Goal Channel delivery shipped through [#3691](https://github.com/huangruiteng/loopx/pull/3691), [#3748](https://github.com/huangruiteng/loopx/pull/3748), [#3749](https://github.com/huangruiteng/loopx/pull/3749), and [#3755](https://github.com/huangruiteng/loopx/pull/3755). General multi-capability promotion remains under review. |
| [Human Attention Wishlist v0](human-attention-wishlist-v0.md) ([中文版](human-attention-wishlist-v0.zh-CN.md)) | Draft, under maintainer review | Intentionally deferred | The RFC remains a discussion contract. Runtime work is held until repeated real usage demonstrates a second need without weakening non-blocking authority boundaries. |
| [Hierarchical Agent Stride Control v0](hierarchical-agent-stride-control-v0.md) ([中文版](hierarchical-agent-stride-control-v0.zh-CN.md)) | Draft, research proposal | M1 observation slice implemented | Read-only stride observation and its synthetic boundary fixture shipped in [#3207](https://github.com/huangruiteng/loopx/pull/3207) and [#3290](https://github.com/huangruiteng/loopx/pull/3290). Adaptive effect, delivery, and authority stride selection remains research-only. |
| [Long-Horizon Harness Benchmark and Research Program v0](long-horizon-harness-benchmark-research-program-v0.md) ([中文版](long-horizon-harness-benchmark-research-program-v0.zh-CN.md)) | Draft, research program | Active research and engineering program | ALE, LHTB, and DeepSWE form the external-validity portfolio; benchmark infrastructure and evidence workflows are being built without treating the research program as a runtime protocol. |
| [Long-Running Agent Reliability Diagnostics and Governed Delivery v0](long-running-agent-reliability-diagnostics-governed-delivery-v0.md) ([中文版](long-running-agent-reliability-diagnostics-governed-delivery-v0.zh-CN.md)) | Draft, product direction and delivery contract | Direction only | The observer-first adoption path, matched benchmark qualification, and governed delivery package are proposed; no unified product contract has been promoted. |
| [Goal Artifact Lifecycle Projection v0](goal-artifact-lifecycle-projection-v0.md) ([中文版](goal-artifact-lifecycle-projection-v0.zh-CN.md)) | Draft, under maintainer review | Proposal only | Milestones, blocking guards, and legal transitions are specified as a read-only projection; no canonical lifecycle projection has shipped. |
| [Obelisk Session Evidence Provider v0](obelisk-session-evidence-provider-v0.md) ([中文版](obelisk-session-evidence-provider-v0.zh-CN.md)) | Draft integration proposal | Evaluation only | The default-off, read-only evidence-provider boundary is documented. Obelisk is not installed, promoted, or authoritative for Replan settlement, memory, or action selection. |
| [LoopX Desktop Execution Frontends v0](desktop-execution-frontends-v0.md) ([中文版](desktop-execution-frontends-v0.zh-CN.md)) | Draft | Supporting foundations implemented | Attached and managed runtime, desktop, and connector pieces exist, but the unified execution-frontend/session-ownership contract and cross-transport convergence are not accepted as one shipped product boundary. |
| [Goal Channel Collaboration v0](goal-channel-collaboration-v0.md) ([中文版](goal-channel-collaboration-v0.zh-CN.md)) | Draft | Lark vertical implemented | Goal-bound Lark groups, Kanban, gate notifications, shared targets, and Bot runtime integration are shipped. The provider-neutral multi-surface model remains draft, and interactive transport is refined by the Desktop Frontends RFC. |
| [Agent IM, LoopX, and OpenViking Collaboration v0](agent-im-openviking-collaboration-v0.md) | Draft | Proposal only | LoopX, IM, and OpenViking have adjacent implementations, but this three-owner collaboration contract has not shipped as an integrated path. |

RFCs must not contain internal conversations, private links, local filesystem
paths, credentials, raw transcripts, or non-public organizational context.
