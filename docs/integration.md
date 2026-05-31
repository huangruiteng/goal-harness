# Integration Guide

Goal Harness should be used as a shared local base, not copied into every
project.

## Local Base

Clone or symlink one copy:

```bash
git clone <repo-url> ~/goal-harness
python3 -m pip install -e ~/goal-harness
```

Then projects can call:

```bash
goal-harness --registry <private-registry> registry
goal-harness --registry <private-registry> history
goal-harness --registry <private-registry> check --scan-root <project-root>
```

## Project Adapter

A project adapter should be thin and project-specific. It may read:

- active goal state,
- git status,
- test or experiment status,
- cheap health checks,
- project-specific guards.

It should output:

- `classification`,
- exactly one `recommended_action`,
- relevant warnings,
- hard guards,
- optional run log paths.

By default it should be read-only. Launching jobs, stopping jobs, syncing docs,
or editing production state requires explicit user approval.

## Shared Runtime

All adapters should save compact run history under:

```text
~/.codex/goal-harness/goals/<goal-id>/runs/index.jsonl
```

This gives the app, CLI, heartbeats, and future UI one place to inspect goal
history.

## Public Repo vs Project Repo

Put generic code here:

- registry and history readers,
- contract checker,
- generic schema and docs,
- sanitized adapter examples.

Keep in the project repo:

- project-specific adapter code,
- active goal state,
- private registry,
- domain-specific health checks.

This split lets many local projects share one stable Goal Harness base while
keeping their real evidence and safety policies local.
