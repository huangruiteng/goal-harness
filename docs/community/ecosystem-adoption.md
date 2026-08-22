# Ecosystem Adoption and Derivatives

> [简体中文](ecosystem-adoption.zh-CN.md)

LoopX is being sampled, integrated, and re-implemented by other open-source
projects. This page is a factual, public-safe inventory of what we observe.

> **Boundary**: inclusion is a factual record, not an endorsement. Only public
> GitHub evidence is listed. Status changes (merged, closed, renamed, stalled)
> are refreshed by a weekly scan; see
> [Maintenance](#maintenance) below.

For voluntary, self-attested project and user entries, see the repository's
[`ADOPTERS.md`](../../ADOPTERS.md) directory. This observed inventory and that
directory intentionally use different evidence boundaries.

## 1. Integrations

Projects that call LoopX CLI/contracts in real flows, or adopted LoopX as a
provider.

- **Adaptive-Agent-Orchestration-Protocol** (YuemingHub) — adopted LoopX as an
  optional long-running execution provider ([PR #41, merged](https://github.com/YuemingHub/Adaptive-Agent-Orchestration-Protocol/pull/41)),
  with a host pilot tracked in [issue #57](https://github.com/YuemingHub/Adaptive-Agent-Orchestration-Protocol/issues/57).
  Status: adopted (protocol layer).
- **LoopX Console / BitFun** (xielixing, GCWing) — a BitFun MiniApp packaging
  the LoopX control plane: host heartbeat calls `quota should-run`, follows
  `scheduler_hint`, and generates task bodies with `heartbeat-prompt --compact`
  ([loopx-console](https://github.com/xielixing/loopx-console),
  [BitFun PR #1808](https://github.com/GCWing/BitFun/pull/1808),
  [PR #2006](https://github.com/GCWing/BitFun/pull/2006)).
  Status: in progress (new repo, open PRs).
- **Meta-RLR** (hk20013106) — merged a maintenance boundary
  ([PR #17](https://github.com/hk20013106/RLR/pull/17)) where LoopX owns
  maintenance goal/todo/evidence/monitor/replan state while `research_loop`
  stays authoritative. Status: merged / active.
- **codexia** (milisp, connorodea) — a LoopX `should-run` pre-flight for the
  automation scheduler was proposed upstream ([PR #71, closed unmerged](https://github.com/milisp/codexia/pull/71))
  and re-opened on a fork ([PR #1](https://github.com/connorodea/codexia-task-management/pull/1)).
  Status: attempted; contract not yet verified against a live install.
- **spoon-core** (XSpoonAi) — planned optional read-only control context
  middleware ([issue #285](https://github.com/XSpoonAi/spoon-core/issues/285)).
  Status: planned.
- **OpenViking / NoKV** — confirmed partners; see
  [README Partner Projects](https://github.com/huangruiteng/loopx#partner-projects).

## 2. Sampling and Borrowing

Issues, PRs, books, or docs that explicitly reference LoopX as inspiration or
as a capability to absorb.

- **《深入理解 AI Agent》/ ai-agent-book** (bojieli, ~37k stars) — merged a
  chapter that anchors LoopX as a concrete Loop Engineering framework across 13
  maintained editions, with a verifier-centered case and a pinned stable commit
  ([PR #614](https://github.com/bojieli/ai-agent-book/pull/614),
  [chapter 10](https://github.com/bojieli/ai-agent-book/blob/01e54bf2acc28c7ebb9c325b6d93aef79e1b5069/book/chapter10.md)).
  Status: merged / textbook-level.
- **Mindthus** (rv198-star) — an explicit compare-and-absorb master plan
  (“兼容借鉴，不硬融理念”) with field-level borrowing candidates:
  [issue #132](https://github.com/rv198-star/Mindthus/issues/132) (总纲),
  [issue #133](https://github.com/rv198-star/Mindthus/issues/133) (scoped
  human gate + honest fallback fields),
  [issue #138](https://github.com/rv198-star/Mindthus/issues/138) (handoff
  recovery five questions). Status: open, maintainer review.
- **GovernLoop** (liangzhipengdamon-maker) — a Phase 0 evaluation report
  ([PR #23](https://github.com/liangzhipengdamon-maker/GovernLoop/pull/23))
  mapping real problems to LoopX capabilities; key finding: LoopX is a
  **passive state kernel** — strong for state persistence, machine-readable
  state, and resumability, not for active execution paths.
- **hartevo-desktop** (tangpingqingwa) — durable Mission Control kernel spec
  borrowing Prime Agent + LoopX patterns
  ([issue #55](https://github.com/tangpingqingwa/hartevo-desktop/issues/55)).
  Status: early spec.
- **stablyai/orca** — feature request referencing LoopX for goal-setting and
  auto-iteration ([issue #12628](https://github.com/stablyai/orca/issues/12628)).
  Status: one-line ask, open.
- **polyphemus** (Diekgbbtt) — research issue to integrate LoopX primitives
  ([issue #89](https://github.com/Diekgbbtt/polyphemus/issues/89)).
  Status: one-line ask, open.
- **mingos-foundation** (YuemingHub) — a deliberate experiment-only consumer
  PR to qualify LoopX as the AAOP execution-continuity provider
  ([PR #18](https://github.com/YuemingHub/mingos-foundation/pull/18)).
  Status: closed by design (experiment).

## 3. Derivatives and Periphery

Forks, kits, books, and same-name projects built around or inspired by LoopX.

- **loopx-book / loopx-book-labs** (cocolord) — a bilingual, protocol-first
  LoopX developer book
  ([loopx-book](https://github.com/cocolord/loopx-book),
  [labs](https://github.com/cocolord/loopx-book-labs)) with runnable labs for
  project onboarding, issue-to-PR, and standalone extensions.
- **foreman** (needware) — a proposed native-TypeScript migration of the LoopX
  kernel, pinned to an upstream authority commit
  ([PR #1](https://github.com/needware/foreman/pull/1)). Upstream coordination
  was invited; see the PR comment thread.
- **Fork contributions**: intranet offline bundle + OpenCode collaboration kit
  ([Allenskoo856](https://github.com/Allenskoo856/loopx/pull/1)),
  dashboard English localization ([manoelcalixto, merged](https://github.com/manoelcalixto/loopx/pull/1)),
  fork CI fail-safe ([Kankandesuyo](https://github.com/Kankandesuyo/loopx/pull/1)),
  native Windows qualification ([hk20013106, closed](https://github.com/hk20013106/loopx/pull/1)).
- **Same-name independent projects** (not upstream code): rye567/loopx
  (quality gate kit), lcmax/Loopx (agent loop design skill), hugh-zhan9/loopx
  (docs-first engineering discipline). Listed for brand clarity, not as
  affiliation.

## Not Tracked Here

- Trending/digest bots and one-line mentions (github-trending, BuilderPulse,
  agents-radar, etc.) are awareness signals but are not listed as adoption.
- Unrelated same-name matches (e.g., x86 `LOOPx` instructions, audio loop
  tools) are excluded.

## Maintenance

- Weekly scan (7d) by the LoopX value-explorer monitor
  (`github-loopx-mention-scan`): `gh search code "huangruiteng/loopx"`,
  `gh search issues loopx`, `gh search prs loopx`, `gh search repos loopx`.
- After each scan, this file is updated through a pull request; material
  transitions also create concrete follow-up todos.
- Last verified: 2026-08-15.
