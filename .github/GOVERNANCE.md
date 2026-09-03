# LoopX Project Governance

This document defines the public project roles and decision process for LoopX.
It governs the repository and its releases. It is separate from LoopX runtime
concepts such as agent peers, todo claims, quota, gates, and write scopes.

## Current Maintainer

| Person | Role | Since | Public evidence |
| --- | --- | --- | --- |
| [`@huangruiteng`](https://github.com/huangruiteng) | Creator and lead maintainer | 2026-05-31 | [Initial public commit](https://github.com/huangruiteng/loopx/commit/7dcdc9dc79226d157ba57d3e8ff4bae664f020c1) |

The lead maintainer is currently the final decision maker for releases,
maintainer appointments, security-sensitive handling, and changes to this
governance model. That tie-break role should be revisited when the active
maintainer group grows.

Path-scoped subsystem appointments and preferred review assignments are
recorded below. A subsystem appointment does not by itself grant
repository-wide maintainer authority.

## Repository Developers With Write Access

The following developers have, or have been invited to accept, GitHub's
repository `write` role. Write access supports day-to-day pull-request and
branch work within the repository rules. It does not by itself appoint someone
as a maintainer or grant release, security, or governance authority.

| GitHub account | Repository role | Access status |
| --- | --- | --- |
| [`@wujc12`](https://github.com/wujc12) | Write | Active |
| [`@ZaynJarvis`](https://github.com/ZaynJarvis) | Write | Active |
| [`@Hoey041`](https://github.com/Hoey041) | Write | Active |
| [`@maxliux5`](https://github.com/maxliux5) | Write | Active |
| [`@JackyCSer`](https://github.com/JackyCSer) | Write | Active |
| [`@steven-kid`](https://github.com/steven-kid) | Write | Active |
| [`@liubf21`](https://github.com/liubf21) | Write | Invitation pending |
| [`@wchwawa`](https://github.com/wchwawa) | Write | Invitation pending |

GitHub's repository settings are the operational source of truth for access.
This public snapshot should be updated through a pull request when a write-role
invitation is accepted, expires, or is revoked. Maintainer appointments remain
subject to the process below.

## Subsystem Maintainers

A subsystem maintainer is accountable for review quality and contract
coherence inside a named surface. The appointment does not grant authority
over unrelated subsystems, releases, security handling, repository settings,
or admin-bypass merges.

### Lark Integration

| Role | Account | Scope |
| --- | --- | --- |
| Subsystem maintainer | [`@steven-kid`](https://github.com/steven-kid) | Bundled Lark extension, its direct CLI delegates, Lark capability and integration documentation, and focused Lark validation |
| Lead maintainer and fallback reviewer | [`@huangruiteng`](https://github.com/huangruiteng) | Repository governance, cross-subsystem decisions, and review of changes authored by the subsystem maintainer |

The Lark integration maintainer is expected to:

- provide the first substantive response and design review for Lark pull
  requests;
- keep extension implementation, direct CLI delegates, public documentation,
  and focused validation consistent;
- protect authority, readback, owner-private receipt, retry, idempotency, and
  cross-platform boundaries;
- submit approval or change-request reviews on pull requests authored by other
  contributors; and
- escalate changes that alter shared extension lifecycle, status, quota, todo,
  release, security, or repository-governance contracts.

The appointment does not authorize the subsystem maintainer to approve their
own pull requests. A non-author reviewer must still approve those changes under
the repository rules. Merge, release, security, repository-settings, and
admin-bypass authority remain governed by this document and the lead
maintainer.

The matching paths are recorded in [`CODEOWNERS`](CODEOWNERS). That file
provides automatic review routing. This appointment does not make code-owner
approval a branch-protection requirement. After at least three, and normally
five, completed cross-author exact-head review cycles, the lead maintainer may
separately decide whether to propose required code-owner review.

### Shared Host Integration Seams

`@steven-kid` is a preferred reviewer, not the sole code owner, for the shared
host integration seams currently centered on:

- `loopx/host_loop_activation.py`;
- `loopx/host_mode_planner.py`;
- `loopx/cli_commands/host_mode_plan.py`; and
- `docs/integrations/runtime-connector-catalog.md`.

Host integration spans Codex, Claude Code, OpenCode, DeepSeek Harness, and
other runtime providers. Provider-specific implementation remains with the
relevant contributors and repository maintainers, while shared status, quota,
todo, scheduler, and Turn contracts remain outside the Lark appointment. These
host paths are therefore not assigned to `@steven-kid` in `CODEOWNERS` at this
stage.

### Changing A Subsystem Appointment

Adding, expanding, narrowing, or retiring a subsystem appointment requires a
public pull request that updates this document and any matching `CODEOWNERS`
routes. Contribution count alone is not sufficient evidence. The decision
should consider sustained technical judgment, cross-author review quality,
boundary discipline, responsiveness, and whether the proposed path scope is
cohesive.

## Project Roles

### Maintainers

Maintainers may review and merge pull requests, publish releases, triage
security reports, and make repository governance decisions. They are expected
to protect compatibility, the public/private boundary, contributor trust, and
the quality of LoopX's control-plane contracts.

Maintainer authority is explicit: it comes from this document and repository
permissions, not from commit count, a runtime todo claim, or an agent role.

### Contributors

Anyone who improves code, tests, documentation, design, issues, or reviews is a
contributor. Accepted commits and co-authored commits are credited through the
public Git history and GitHub contributor views. Contribution does not by
itself grant merge, release, or governance authority.

### Agents And Automation

Agents and automation may prepare changes, run validation, or appear in commit
provenance. They do not become human maintainers and cannot grant themselves
repository authority. A human maintainer remains accountable for merges,
releases, and boundary decisions.

## How Decisions Are Made

- Routine changes use pull-request review, focused validation, and maintainer
  judgment. Silence is not approval when a change requires an explicit gate.
- Changes to persisted state, public contracts, defaults, permissions,
  evidence policy, or compatibility should explain the behavioral impact and
  include proportionate regression coverage.
- Significant product or governance changes should be discussed in a public
  issue or pull request before they are finalized.
- Security reports, credentials, private evidence, and other sensitive matters
  must not be posted in a public issue. Ask a maintainer for a private contact
  path without including the sensitive details.
- Releases are cut by a maintainer after the documented release checks pass.
  Exceptions and known skips should be recorded in the release or pull request.
- When consensus is not reached, the lead maintainer records the decision and
  rationale in the relevant issue or pull request.

## Technical Direction Governance

The versioned
[Current Technical Directions](../docs/project/technical-directions.md) page is
the canonical map of active strategic programs, maturity, contribution routes,
and promotion gates. The pinned
[GitHub Discussion](https://github.com/huangruiteng/loopx/discussions/2851) is
its community-facing projection; an issue, Discussion, RFC, or integration
branch does not override merged runtime and stable reference contracts.

Each strategic direction has one long-lived tracking issue. Trackers record
outcomes, boundaries, implementation leads, material decisions, and links to
bounded work. They are not themselves blanket implementation authorization.
A claimable change should have a separate issue or public task-board row with
an explicit smallest slice, base branch, non-goals, and validation plan.

A material change to a direction's stage, scope, implementation lead,
integration branch, or promotion gate requires a pull request updating the
canonical map. The RFC index and contributor task board should change in the
same pull request when their routing changes. Maintainers update the pinned
Discussion after merge and should not maintain an independent roadmap body
there.

The `direction/*` labels route discovery and review. They do not grant
authority, promise delivery, or imply that a Draft or Research item is ready
for implementation. Recognition as an implementation lead records current
public work; it is separate from repository write access, subsystem maintainer
appointment, and repository-wide maintainer authority.

## Becoming A Maintainer

Maintainers are selected from contributors who have shown sustained technical
judgment, reliable review, respect for project boundaries, and care for other
contributors. An active maintainer nominates the candidate; the active
maintainers approve the appointment; and the change is recorded here through a
pull request.

A maintainer may step down at any time. Inactive or emeritus status, when
needed, should likewise be recorded in this file rather than inferred from
recent commit activity.

## Accountability And Scope

Important decisions should leave durable public rationale in an issue, pull
request, release, or stable project document. Private incident details and raw
agent trajectories do not belong in that public record.

This charter does not create a legal entity, employment relationship,
copyright assignment, or trademark registration. See
[Authors and Contributors](../docs/project/authors.md) for attribution,
[Name and Marks](../docs/project/trademarks.md) for name and mark usage, and
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the contribution workflow.
