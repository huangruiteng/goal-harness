# Architecture RFCs

Architecture RFCs are public design proposals. Each RFC should name its
status, decision boundary, non-goals, smallest useful implementation slice,
and validation criteria. An RFC may describe future work; current behavior is
defined by the implementation and stable reference contracts.

The [Current Technical Directions](../../project/technical-directions.md) page
maps these RFCs to strategic programs, contribution routes, and promotion
gates. The groups below reflect the status written in each RFC; they do not
promote a proposal beyond that status.

## Accepted Architecture

- [Agent Loop Effect Interpreter v0](agent-loop-effect-interpreter-v0.md)
  ([中文版](agent-loop-effect-interpreter-v0.zh-CN.md)): model LoopX as the
  effect interpreter around an agent loop, with canonical
  effect-request/interpretation/observation packets and a shared typed Effect
  Program for qualified settlement paths. Replan planning and ACK remain
  domain-local until a second real plan/receipt lifecycle justifies extraction.

## Active Research Programs

- [Long-Horizon Harness Benchmark and Research Program v0](long-horizon-harness-benchmark-research-program-v0.md)
  ([中文版](long-horizon-harness-benchmark-research-program-v0.zh-CN.md)):
  use ALE, LHTB, and DeepSWE as a complementary external-validity portfolio;
  separate capability evidence from mechanism research and preserve
  benchmark-native outcomes.
- [Hierarchical Agent Stride Control v0](hierarchical-agent-stride-control-v0.md)
  ([中文版](hierarchical-agent-stride-control-v0.zh-CN.md)): qualify effect
  feedback, bounded delivery, and authority intervention as nested control
  intervals before introducing adaptive stride selection.

## Product Direction And Delivery Contracts

- [Long-Running Agent Reliability Diagnostics and Governed Delivery v0](long-running-agent-reliability-diagnostics-governed-delivery-v0.md)
  ([中文版](long-running-agent-reliability-diagnostics-governed-delivery-v0.zh-CN.md)):
  define an observer-first entry between a native harness and full LoopX
  adoption, qualify it with matched benchmark evidence, and add execution
  authority only through accepted, reversible seams and reusable delivery
  assets.

## Drafts Under Review

- [Research Exploration Control Plane v0](research-exploration-control-plane-v0.md)
  ([中文版](research-exploration-control-plane-v0.zh-CN.md)): evolve a typed
  research frontier across coverage, closure, and explicit composition while
  keeping Explore, goal-frontier, and execution authority separate.
- [Human Attention Wishlist v0](human-attention-wishlist-v0.md)
  ([中文版](human-attention-wishlist-v0.zh-CN.md)): capture bounded,
  evidence-backed requests for optional human leverage as a non-blocking
  post-delivery sidecar without changing gates, selected work, quota, or
  notification authority.
- [Shared-goal online authority and pluggable coordination provider v0](shared-goal-authority-state-provider-v0.md)
  ([中文版](shared-goal-authority-state-provider-v0.zh-CN.md),
  [validation boundary](shared-goal-authority-state-provider-v0-evidence.zh-CN.md)):
  prove a claim-only provider-neutral contract for target-scoped conflict and
  original-receipt replay, with NoKV as an unpromoted provider candidate.
- [Goal artifact lifecycle projection v0](goal-artifact-lifecycle-projection-v0.md)
  ([中文版](goal-artifact-lifecycle-projection-v0.zh-CN.md)): derive
  milestones, blocking guards, and legal next transitions as a read-only
  operator projection.
- [Post-Outcome Memory Utility Attribution v0](post-outcome-memory-utility-attribution-v0.md)
  ([中文版](post-outcome-memory-utility-attribution-v0.zh-CN.md)): attribute
  bounded, evidence-tiered utility to recalled memory after verified outcomes
  without making retrieval, model judgment, or a global evaluator authoritative.
- [TypeScript Control-Plane Migration v0](typescript-control-plane-migration-v0.md)
  ([中文版](typescript-control-plane-migration-v0.zh-CN.md)): use a
  contract-first, parity-gated, block-by-block process; Python remains
  canonical during the transition.

## Draft Integration Proposals

- [Agent IM, LoopX, and OpenViking collaboration v0](agent-im-openviking-collaboration-v0.md):
  separate runtime delivery, durable control state, and scoped context while
  preserving direct agent-to-LoopX interaction.
- [Goal Channel collaboration v0](goal-channel-collaboration-v0.md)
  ([中文版](goal-channel-collaboration-v0.zh-CN.md)): bind one external
  collaboration channel to one LoopX goal while preserving LoopX as the source
  of truth.
- [Per-Goal Usage, Token, and Cost Surfacing v0](goal-usage-token-cost-v0.md):
  capture per-goal token, cost, and duration in core `usage_summary` and surface
  it in the existing dashboard behind a provider-neutral capture layer.

RFCs must not contain internal conversations, private links, local filesystem
paths, credentials, raw transcripts, or non-public organizational context.
