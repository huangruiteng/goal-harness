# Architecture RFCs

Architecture RFCs are public design proposals. Each RFC should name its
status, decision boundary, non-goals, smallest useful implementation slice,
and validation criteria. An RFC may describe future work; current behavior is
defined by the implementation and stable reference contracts.

## Active Drafts

- [Hierarchical Agent Stride Control v0](hierarchical-agent-stride-control-v0.md): treat effect feedback, bounded delivery, and authority intervention as three nested control intervals, then qualify their efficiency and failure modes before introducing adaptive stride selection.
- [长程 Agent 分层步幅控制 v0](hierarchical-agent-stride-control-v0.zh-CN.md)：把 effect 反馈、有界交付与 authority 干预视为三种嵌套控制区间，在引入 adaptive stride selection 前，先验证各层效率与失败模式。
- [Human Attention Wishlist v0](human-attention-wishlist-v0.md): let agents capture bounded, evidence-backed requests for optional human leverage as a non-blocking post-delivery sidecar, without changing user-gate authority, selected work, quota, or notification behavior.
- [Human Attention Wishlist v0（中文版）](human-attention-wishlist-v0.zh-CN.md)：让 agent 把有证据、可增加价值但不阻塞当前交付的人类协作机会，作为有界的交付后 sidecar 写入；不改变 user gate 权限、选中工作、quota 或通知行为。
- [Research Exploration Control Plane v0](research-exploration-control-plane-v0.md): evolve a typed research frontier across coverage, closure, and explicit composition experiments while keeping Explore, goal-frontier, and execution authority separate.
- [研究型探索控制面 v0](research-exploration-control-plane-v0.zh-CN.md)：围绕 coverage、closure 与显式组合实验演进类型化研究前沿，同时保持 Explore、goal-frontier 与执行权限彼此分离。
- [Agent Loop Effect Interpreter v0](agent-loop-effect-interpreter-v0.md): model LoopX as the effect interpreter around an agent loop, with canonical effect-request/interpretation/observation packet semantics.
- [Agent Loop Effect Interpreter v0（中文版）](agent-loop-effect-interpreter-v0.zh-CN.md): 把 LoopX 建模为 agent loop 外围的 effect interpreter，并给出 canonical effect-request/interpretation/observation packet 语义。
- [Agent IM, LoopX, and OpenViking collaboration v0](agent-im-openviking-collaboration-v0.md): separate runtime delivery, durable control state, and scoped context while preserving direct agent-to-LoopX interaction.
- [Goal Channel collaboration v0](goal-channel-collaboration-v0.md): bind one external collaboration channel to one LoopX goal while preserving LoopX as the source of truth.
- [Goal Channel 协作模型 v0](goal-channel-collaboration-v0.zh-CN.md): 将一个外部协作通道绑定到一个 LoopX goal，同时保持 LoopX 作为事实源。
- [Shared-goal online authority and pluggable coordination provider v0](shared-goal-authority-state-provider-v0.md): a claim-only contract proof for target-scoped conflicts over one canonical coordination aggregate, atomic original-receipt replay, and per-layer persistence ownership, with NoKV as an unpromoted provider candidate ([中文版](shared-goal-authority-state-provider-v0.zh-CN.md), [validation boundary](shared-goal-authority-state-provider-v0-evidence.zh-CN.md)).
- [Goal artifact lifecycle projection v0](goal-artifact-lifecycle-projection-v0.md): derived from artifact-centric business process management (ABPM / GSM milestone-guard semantics); treat a goal as a business artifact with derived milestones, blocking guards, and legal next transitions, projected read-only for operators and global views ([中文版](goal-artifact-lifecycle-projection-v0.zh-CN.md)).
- [Post-Outcome Memory Utility Attribution v0](post-outcome-memory-utility-attribution-v0.md): attribute bounded, evidence-tiered utility to recalled memory after verified outcomes, without turning retrieval, model judgment, or a global evaluator into authority.
- [结果后记忆效用归因 v0](post-outcome-memory-utility-attribution-v0.zh-CN.md)：在可验证结果之后，对召回记忆做有界、分证据等级的效用归因，同时避免让召回、模型判断或全局评估器变成新的权限来源。
- [TypeScript Control-Plane Migration v0](typescript-control-plane-migration-v0.md): contract-first, parity-gated, block-by-block migration from Python to TypeScript over the event store, parity-fixture layer, and CLI boundary; Python remains canonical during the transition.
- [TypeScript 控制面迁移 v0](typescript-control-plane-migration-v0.zh-CN.md)：契约优先、parity 门禁、逐块迁移；基于事件存储、parity fixture 层与 CLI 边界从 Python 渐进迁移到 TypeScript，过渡期内 Python 保持权威实现。

RFCs must not contain internal conversations, private links, local filesystem
paths, credentials, raw transcripts, or non-public organizational context.
