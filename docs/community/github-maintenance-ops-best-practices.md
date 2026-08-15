# GitHub Maintenance & Ops Automation: Best Practices from Running LoopX

> [简体中文](github-maintenance-ops-best-practices.zh-CN.md)

LoopX maintains its own open-source repository with LoopX. This page records
the operating patterns and best practices that emerged, generalized so other
open-source maintainers can reuse them.

## 1. The Claim

Repository maintenance and operations is long-horizon, interruptible,
high-context work: triage, review, release, security response, ecosystem
outreach, and content are never one prompt away from done. That is the same
problem shape LoopX solves for long-running agents, so running the repository
with LoopX is both dogfooding and a source of best practices.

Three operating patterns emerged:

1. a maintenance loop that owns PR review discipline, release and security
   handling, triage, and infrastructure repair;
2. an ecosystem and value loop that watches adoption, evaluates forks and
   derivatives, invites upstream contributions, and turns public evidence into
   documentation and social content;
3. an issue-to-PR bot that drives a public issue through feasibility, focused
   fix, evidence, reviewer routing, and merge observation.

## 2. Three Operating Patterns

### Pattern A: Maintenance Loop

The maintenance loop runs under heartbeat automation with its own goal,
todos, quota, and monitor contracts. It performs the repetitive but
judgment-heavy work of a maintainer:

- PR review with an explicit skill and exact-head evidence gate, instead of
  ad-hoc review from memory;
- issue/PR triage with typed classification so incoming work is tagged and
  routed;
- release and security response, including coordinated disclosure, with a
  recorded decision boundary;
- infrastructure repair such as fixing a stale star-history service or
  updating automation scheduling from a hint, backed by a small reusable tool
  that reads the hint, backs up state, applies the change, and acknowledges.

Public evidence: releases v0.4.5 through v0.4.7, the PR review skill
refinements, and the review/release discipline recorded in repository history.

### Pattern B: Ecosystem And Value Loop

The ecosystem loop treats the repository as a product that must be observed,
evaluated, and fed:

- a weekly scan classifies mentions into integrations, sampling/borrowing,
  derivatives, and coverage signals;
- each scan updates a public adoption inventory through a PR, so the inventory
  is a maintained artifact rather than a one-time report;
- forks and same-name projects are evaluated for absorbable capabilities
  (offline packaging, fork-safe CI, platform qualification, localization,
  quality-gate workflows);
- valuable sources receive an upstream PR invitation directly on their PR or
  issue thread;
- social content is produced from the same public evidence through a
  content-ops pipeline with explicit review states, and publication stays
  gated until the owner approves.

Public evidence: the ecosystem adoption inventory
([`ecosystem-adoption.md`](ecosystem-adoption.md)), the TypeScript migration
RFC ([#3225](https://github.com/huangruiteng/loopx/issues/3225),
[#3226](https://github.com/huangruiteng/loopx/pull/3226)), and the content-ops
capability.

### Pattern C: Issue-To-PR Bot

The issue-fix capability turns one public issue into a focused, verified,
reviewable PR and follows it to merged, closed, or an explicit no-follow-up.
It combines four layers with clear boundaries:

- the state kernel provides goal, todo, quota, authority, monitor, replan, and
  terminal closeout across turns;
- optional repository memory provides advisory context, always validated
  against the current checkout;
- domain state records feasibility, repository context, delivery evidence,
  reviewer route, PR lifecycle, and outcome;
- the agent runtime provides understanding, coding, and execution.

The core promise: `/loopx Fix <issue-url>` is not "generate a patch"; it is a
loop that survives model switches, CI waits, and review round-trips.

Public evidence: the
[issue-fix capability documentation](../capabilities/issue-fix/README.md) and
the OpenViking pilot recorded in the showcase appendix.

## 3. Best Practices

### 3.1 State Over Chat Memory

Every repetitive operation needs a durable state surface: todos, quota,
monitor, and replan. When a maintenance or outreach action is interrupted, the
next turn resumes from state, not from conversation history. Heartbeat
automation uses backoff and quiet waits instead of polling or forcing progress.

### 3.2 Turn Judgment Into Contracts, Skills, And CLI

The highest-leverage maintainer work is judgment. Once a judgment is
recognized, encode it: a PR review skill with exact-head evidence, a
scope-fit gate that rejects modules without a real call site, a typed decision
packet instead of prose, and a CLI entry point instead of instructions in chat.
This converts "review carefully" from a reminder into a checkable gate.

### 3.3 Classify Intake And Run An Adoption Funnel

Incoming issues, PRs, and mentions are classified before work. Issues and PRs
get typed tags; ecosystem mentions are split into integrations, sampling,
derivatives, and coverage. A weekly monitor updates the public inventory
through a PR, and material transitions create concrete follow-up todos instead
of being remembered.

### 3.4 Keep Security And Release Discipline Explicit

Security reports, disclosure, and release cutovers are recorded decision
paths, not improvisation. The pattern: reproduce and fix, self-review at exact
head, publish coordinated advisories when appropriate, then release with a
readable changelog and validation commands. Human maintainers keep the final
decision on what is disclosed and when.

### 3.5 Outreach Is A Cadence, Not A Campaign

Fork and derivative evaluation runs on a schedule. For each valuable source,
send one focused invitation on the author's own PR or issue thread, with a
concrete upstream target and an offer to review. Record outreach locally, and
let a monitor surface follow-ups instead of polling in chat.

### 3.6 Content Ops Feeds The Repository And Vice Versa

Public repository evidence is the source map for documentation and social
content. Content moves through a gated pipeline: source → angle → draft →
feedback → publish gate → readback. Approved content links back to the
repository, and reader signals return as new evidence. No raw private state
enters public packets.

### 3.7 Convergence Needs Parity First

When two execution paths drift semantically (for example turn settlement and
quota settlement), freeze both with parity fixtures first, then extract a
shared driver, then delete the duplicated branches. The same rule applies to a
language migration: contract freeze, parity gates, then block-by-block
replacement with rollback records.

### 3.8 Human Gates Stay Real

Automation reduces the cost of repetitive work but never removes the human
from judgment: publishing, disclosure, merge decisions, and scope changes
remain explicit gates. Approvals are bound to a specific revision, and
revising approved content invalidates the approval.

## 4. Failure Modes And Boundaries

- Long-running exploration can be wide and still miss a key detail; harnesses
  fix "runs long", but "reads fully" still needs better tool design.
- Low-quality contributor PRs can slip through when review is ad hoc; an
  explicit review skill and exact-head evidence make the signal visible.
- Monitor thresholds are heuristics; tune defaults from observed behavior
  (for example increasing the unchanged-streak before replan) and record why.
- Do not rewrite a large core in one pass; use contracts, parity, and
  reversible slices.
- Public materials must not leak internal context: no private links, raw
  logs, credentials, or unapproved internal metrics.

## 5. Reusable Playbook

1. Weekly: scan public mentions, update the adoption inventory through a PR.
2. Per incoming issue/PR: classify, tag, and route; drive fixable issues
   through the issue-fix loop.
3. Per fork/derivative: evaluate the diff against upstream, decide
   absorbability, send one upstream PR invitation, record it.
4. Per security report: reproduce, fix, self-review at exact head, decide
   disclosure, release.
5. Per social idea: build a public-safe source map, draft through the
   content-ops pipeline, gate on owner approval, publish, read back.

## 6. Evidence Index

- Ecosystem adoption inventory:
  [`ecosystem-adoption.md`](ecosystem-adoption.md)
- TypeScript migration RFC: issue
  [#3225](https://github.com/huangruiteng/loopx/issues/3225), RFC PR
  [#3226](https://github.com/huangruiteng/loopx/pull/3226)
- Issue-fix capability:
  [`docs/capabilities/issue-fix/README.md`](../capabilities/issue-fix/README.md)
- Content-ops capability:
  [`docs/capabilities/content-ops/README.md`](../capabilities/content-ops/README.md)
- Releases v0.4.5 through v0.4.7:
  [releases](https://github.com/huangruiteng/loopx/releases)
