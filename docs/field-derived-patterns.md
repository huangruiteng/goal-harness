# Field-Derived Project Control Patterns

Goal Harness should grow from repeated real collaboration patterns, not only
from abstract feature ideas. This document records public-safe mechanisms that
have proven useful in documentation-heavy agent infrastructure work,
long-window experiment control, and multi-project Codex collaboration.

The examples below are intentionally sanitized. Project-specific task ids,
private paths, internal document links, production logs, and metric values
belong in project-local payloads, not in the public Goal Harness repo.

## 1. Authority Registry

Complex projects need an authority layer before they need more automation.
When a repository has many design docs, TODO files, local mirrors, experiment
reports, and archived notes, the first failure mode is not that an agent cannot
read enough. It is that the agent reads the wrong source as current truth.

A useful authority registry names:

- default entry documents for a new controller tick;
- topic ownership: which file is canonical for current priorities, system
  design, validation, external sync, or historical evidence;
- document status: active, draft, diagnostic, external mirror, superseded,
  deprecated, archived;
- conflict rules: what wins when a TODO, design doc, mirror, and old run report
  disagree;
- update rules: when changing a canonical document also requires updating the
  registry.

Goal Harness should treat this as a first-class complex-project mechanism:

```json
{
  "authority_registry": {
    "path": "docs/meta/DOC_REGISTRY.yaml",
    "default_entry_docs": [
      "docs/TODO.md",
      "docs/meta/DOC_REGISTRY.yaml",
      "docs/external_materials/MANIFEST.md"
    ],
    "topic_authority": {
      "current_priority": "docs/TODO.md",
      "runtime_architecture": "docs/SYSTEM_DESIGN.md",
      "external_sync": "docs/external_materials/MANIFEST.md"
    }
  }
}
```

For `read-only-map`, the adapter should not just list files. It should report
whether an authority registry exists, which default entries were inspected,
which topics have canonical owners, and whether any active source conflicts
with a deprecated or archived source.

## 2. Current-Belief TODO

For long-running projects, a TODO file is most valuable when it answers three
questions:

- what do we currently believe?
- why do we believe it?
- what is the next bounded action?

This is different from a chronological task dump. Historical work should be
kept, but it should be compressed into archives, diagnostic reports, or
appendices once it no longer drives the next decision.

Goal Harness should absorb this pattern into active goal state and
read-only-map summaries:

- `current_judgment`: compact belief;
- `evidence_boundary`: what supports it and what does not;
- `next_action`: one bounded next step;
- `deferred_or_archived`: older lines that remain traceable but should not
  drive current work.

This makes state refreshes useful. A state-only update is not a log entry; it is
a new current-belief surface for the next agent tick and dashboard.

## 3. Managed External-Source Manifest

Many real projects depend on external documents, review surfaces, or product
discussion artifacts. They should not be treated as ordinary links.

A managed external-source manifest should track:

- local mirror path;
- stable source identifier;
- source revision or fetched timestamp;
- role: strategy doc, project wiki, validation doc, collaboration notes, etc.;
- sync direction and whether remote is newer;
- unresolved comments, highlights, or reviewer-visible marks that must be
  preserved;
- fetch-before-write rules.

Goal Harness should not blindly copy external material into public status. The
public compact record should say that a managed external source exists and
whether it is fresh enough. The private payload can keep richer evidence.

This pattern prevents two common failures:

- overwriting reviewer-visible remote signal because a local mirror looks
  cleaner;
- letting a stale local note become the current project authority.

## 4. Validation Surface Map

Complex projects rarely have one validation command. Progress may be proven by
different surfaces:

| Work type | Validation surface |
| --- | --- |
| Docs | markdown structure, links, authority registry, review notes |
| External sync | manifest freshness, scoped fetch, comment/highlight preservation |
| Benchmark/eval | run artifact, metric file, trace, paired baseline, claim boundary |
| Code | unit tests, type checks, integration smoke |
| PR/CI | branch status, CI checks, review comments |
| Public release | sensitive scan, README quickstart, examples |

Goal Harness should require each complex-project map to name validation
surfaces before proposing implementation work. This lets the dashboard show
"ready for Codex" only when the next action has a credible verification path.

## 5. Experiment Board

Long-window experiment projects need an experiment board, not only a run log.
The board should separate:

- objective and primary decision metric;
- decision window and comparable baseline window;
- guardrail metrics;
- non-goals and unsafe shortcuts;
- active tasks and what to watch;
- completed anchors and route history;
- launch or compute quota;
- next handoff condition.

The most important lesson is to anchor the goal identity in the decisive
evidence. If the real objective is a long-window metric, a runtime cache risk,
training-only movement, or one failed task should not become the goal identity.

Goal Harness should model this as:

```json
{
  "experiment_board": {
    "path": ".codex/experiments/example-goal.md",
    "primary_metric": "primary decision metric",
    "decision_window": "aligned eval window",
    "guardrails": ["runtime stability", "secondary metrics"],
    "active_tasks_section": "Active Tasks",
    "route_history_section": "Config Notes And History"
  }
}
```

Adapters should surface `waiting_on=external_evidence` until the decisive
evidence is comparable. Human reward or decision advice should not be inferred
from training-only guardrails.

## 6. Gate Order

Several field failures become simpler if Goal Harness applies gates in a stable
order:

1. health and public/private safety;
2. operator gate or project-controller opt-in;
3. evidence readiness;
4. compute quota;
5. Codex execution.

Compute quota decides how much automatic agent time a goal may consume. It does
not authorize writes, production actions, or route decisions. Operator gates
and human reward remain separate durable events.

## 7. Handoff Packet

A good handoff packet is short enough to forward, but precise enough to avoid
re-discovery. It should include:

- goal id and current classification;
- one recommended action;
- files or surfaces inspected;
- authority sources;
- validation surfaces;
- hard guards;
- residual risks;
- the exact condition that would allow the next stage.

It should not include raw private evidence. It should also not pretend to be
user approval. If a project agent needs permission to cross a gate, Goal
Harness should record an `operator_gate_*` run before the command becomes
Codex-ready.

## 8. Parallel Work Claims

Large projects often need several agents, but parallelism only works when
claims are explicit:

- controller owns the objective, final merge, public/private scan, and state
  writeback;
- child agents own scoped read-only exploration, one implementation slice, or
  one validation surface;
- write scopes should be disjoint;
- shared canonical sources such as TODO, authority registry, and global schema
  should normally be changed by the controller, not by independent children.

Goal Harness should record these as proposed sub-agent scopes in read-only
maps, then let the controller accept, edit, or reject them.

## 9. Anti-Patterns To Block

Goal Harness should actively prevent these patterns:

- treating a chat thread as the source of truth;
- using automation cadence as the only expression of project priority;
- letting an incidental runtime risk replace the real goal identity;
- using training-only or non-comparable evidence as a route winner;
- appending logs to a planning doc instead of updating the current belief;
- copying private links, task ids, workspace paths, or raw logs into public
  compact history;
- overwriting managed external sources without checking remote comments or
  reviewer marks;
- letting the last completed slice choose the next action without checking the
  goal's P0/P1/P2 priority stack;
- handing a project agent a command before recording the operator gate that
  makes the command valid.

## Near-Term Implementation Implications

These field patterns imply four concrete Goal Harness surfaces:

1. **Authority registry support**: `connect` and `read-only-map` should accept
   or discover a project authority registry and publish compact coverage.
2. **Experiment board support**: experiment adapters should name primary metric,
   decision window, guardrails, active-task section, and route-history section.
3. **Validation surface map**: status and dashboard should show why a goal is
   ready, waiting, or blocked in terms of validation surfaces, not only raw
   classifications.
4. **Handoff packet discipline**: every cross-thread packet should be short,
   public-safe, and gated; packets are collaboration affordances, not durable
   approval.
5. **Priority-stack next action**: every controller tick should explain whether
   the selected next action is P0, P1, or P2, and why it outranks adjacent
   candidates.
