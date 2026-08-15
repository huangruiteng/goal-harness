# LoopX Subsystem Maintainers

This document records path-scoped subsystem maintenance and preferred review
assignments. Repository-wide roles, release authority, and final governance
decisions remain defined by [GOVERNANCE.md](GOVERNANCE.md). GitHub repository
settings remain the operational source of truth for access.

A subsystem maintainer is accountable for review quality and contract
coherence inside a named surface. The appointment does not grant authority
over unrelated subsystems, releases, security handling, repository settings,
or admin-bypass merges.

## Lark Integration

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
admin-bypass authority remain governed by `GOVERNANCE.md` and the lead
maintainer.

The matching paths are recorded in [`.github/CODEOWNERS`](.github/CODEOWNERS).
That file provides automatic review routing. This appointment does not make
code-owner approval a branch-protection requirement. After at least three, and
normally five, completed cross-author exact-head review cycles, the lead
maintainer may separately decide whether to propose required code-owner review.

## Shared Host Integration Seams

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

## Changing An Appointment

Adding, expanding, narrowing, or retiring a subsystem appointment requires a
public pull request that updates this document and any matching `CODEOWNERS`
routes. Contribution count alone is not sufficient evidence. The decision
should consider sustained technical judgment, cross-author review quality,
boundary discipline, responsiveness, and whether the proposed path scope is
cohesive.
