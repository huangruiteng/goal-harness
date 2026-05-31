# Goal Harness

Goal Harness is a lightweight control plane for long-running agent goals. It is
designed to sit above local agent apps, CLI sessions, recurring heartbeats, and
goal-mode runs.

It does not replace an agent or a project-specific workflow. It gives each goal
four durable things:

- a project-local goal state file,
- a registry entry that says where the goal lives and which adapter reads it,
- a shared runtime directory for run logs,
- a read-only contract check before the next agent tick.

## Why

Long-running agent work fails less from a single weak prompt than from drift:
lost next actions, stale assumptions, unclear handoffs, mixed project state,
and unreviewed private data. Goal Harness keeps those boundaries explicit.

## Recommended Layout

Use one local checkout as the shared base:

```bash
git clone <your-fork-or-repo-url> ~/goal-harness
python3 -m pip install -e ~/goal-harness
```

Each project keeps its own private state and thin adapter:

```text
project/
  .local/ACTIVE_GOAL_STATE.md        # private, not committed
  .local/GOAL_HARNESS_REGISTRY.json  # private, can contain local paths
  scripts/project-pre-tick.py        # optional thin adapter

~/.codex/goal-harness/
  goals/<goal-id>/runs/index.jsonl   # shared runtime history
```

The core code is not copied into every project. Project files call the shared
CLI and keep only project-specific policy, evidence readers, and guards.

## CLI

```bash
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json registry
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json history
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json check --scan-root .
```

JSON output is available for pre-tick integration:

```bash
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json --format json check --scan-root .
```

For a project that has many unrelated historical files, restrict the public
boundary check to the adapter files you intend to publish:

```bash
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json check \
  --scan-path scripts/project-pre-tick.py \
  --scan-path docs/goal-harness-contract.md
```

The example registry uses `./runtime` on purpose, so demo commands do not read
your real local goal history.

## Integration Model

1. Keep the shared package at one stable local path, usually `~/goal-harness`.
2. Add a private registry in each project.
3. Add or keep a project-specific pre-tick script that calls Goal Harness.
4. Save adapter run logs into `~/.codex/goal-harness/goals/<goal-id>/runs/`.
5. A future UI can read the same runtime root instead of scraping projects.

## Public / Private Boundary

Safe to publish:

- registry schema,
- runtime layout,
- adapter lifecycle,
- generic validation commands,
- sanitized examples.

Keep private:

- real project paths,
- task ids,
- production logs,
- internal document links,
- credentials,
- user-specific active goal state,
- raw experiment metrics.

See [docs/public-private-boundary.md](docs/public-private-boundary.md).

## Current Status

This repository is intentionally small. The first milestone is not a full agent
platform; it is a reliable shared substrate for local goal state, run history,
and contract checks across several projects.
