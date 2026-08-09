# PR And Issue Labels

LoopX uses GitHub labels so maintainers, contributors, and agent monitors can
filter, route, and aggregate issues and pull requests by lifecycle and product
area.

## Lifecycle Labels

These labels describe the item lifecycle and are applied by issue templates or
maintainer triage:

| Label | Applied by | Meaning |
| --- | --- | --- |
| `bug` | Bug report template | Reproducible incorrect or unexpected behavior. |
| `enhancement` | Feature request template | Concrete product or documentation improvement. |
| `triage` | Issue templates | Needs maintainer triage or routing before work starts. |
| `duplicate` / `question` / `invalid` / `wontfix` | Maintainer triage | Standard GitHub lifecycle states. |
| `good first issue` / `help wanted` | Maintainer triage | Contributor onboarding signals. |
| `workflow-audit` | Contributor task board | Public or synthetic agent workflows for LoopX audit. |

## Area Labels

Area labels describe the public product surface a change touches. Issue
templates ask contributors to select an area, and pull request templates ask
for a self-tagged primary area; maintainers apply the matching label:

| Label | Public surface |
| --- | --- |
| `control-plane` | Goals, todos, quota, scheduler, registry, runtime, state, and gate lifecycle. |
| `benchmark-boundary` | Benchmark adapters, runners, verifiers, scoring, leaderboards, and public benchmark evidence. |
| `capability-extension` | Capability, extension, provider, adapter, or skill contracts. |
| `public-docs` | README, protocol docs, frontstage, dashboard, and first-screen presentation surfaces. |
| `build-or-ci` | Build, packaging, installer, CI workflows, and release pipelines. |

Anything not clearly covered by an area label keeps only its lifecycle label.

## Triage Policy

1. Issue templates auto-apply `triage` plus `bug` or `enhancement`.
2. Maintainers (or an approved bot) move triaged items forward: route to an
   area label, mark `duplicate`/`question`/`invalid`/`wontfix`, or link a
   contributor task.
3. Pull requests self-tag a primary area in the template. Reviewers verify the
   area matches the diff and correct the label when it does not.
4. Agent monitors (PR review queue, issue intake) may read area labels as
   routing hints, but labels never grant review, merge, or write authority.

## Staged Auto-Classification

Today labels are human-selected through templates and triage. The next stage
may add a rule-based classifier that suggests area labels from title, changed
files, and review areas, followed by an offline model for long-tail cases.
This staged path follows the classification practice used by the OpenViking
feedback observability design: start with deterministic rules as an
enhancement, then move to a model, then stabilize the taxonomy. Until then,
labels are guidance, not an automated contract.
