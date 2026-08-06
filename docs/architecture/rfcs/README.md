# Architecture RFCs

Architecture RFCs are public design proposals. Each RFC should name its
status, decision boundary, non-goals, smallest useful implementation slice,
and validation criteria. An RFC may describe future work; current behavior is
defined by the implementation and stable reference contracts.

## Active Drafts

- [Agent IM, LoopX, and OpenViking collaboration v0](agent-im-openviking-collaboration-v0.md): separate runtime delivery, durable control state, and scoped context while preserving direct agent-to-LoopX interaction.
- [Shared-goal online authority and pluggable coordination provider v0](shared-goal-authority-state-provider-v0.md): a claim-only contract proof for target-scoped conflicts over one canonical coordination aggregate, atomic original-receipt replay, and per-layer persistence ownership, with NoKV as an unpromoted provider candidate ([中文版](shared-goal-authority-state-provider-v0.zh-CN.md), [validation boundary](shared-goal-authority-state-provider-v0-evidence.zh-CN.md)).

RFCs must not contain internal conversations, private links, local filesystem
paths, credentials, raw transcripts, or non-public organizational context.
