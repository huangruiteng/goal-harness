# Local Synthetic Overlay

`local-synthetic-overlay` is a built-in LoopX authority path for one narrow
case: a task needs a disposable local container and synthetic database to
validate an exact candidate, while product-write authority remains exactly
zero.

It does not use the legacy Dispatcher task schema. It does not enqueue work,
issue leases, inherit historical grants, or turn runtime availability into
product authority.

## Closed envelope

Every issued receipt binds all of the following:

- one live Goal and one active Todo;
- one exact local Git worktree, 40-character HEAD, and commit tree, belonging
  to the same Git repository as the Goal registry entry (linked worktrees are
  supported);
- a tracked-clean candidate;
- one task-specific Compose project used for cleanup readback;
- exactly `local_container` and `synthetic_database`;
- `scope=local_synthetic_validation_only`;
- `product_write_scope=ZERO`;
- `lifetime=task_bound`, a short expiry, and no cross-task reuse;
- no real customer or child data, real audio, real provider, or production;
- one digest-pinned database image already present on the local machine.

Changing any binding invalidates the receipt. The validator re-reads the live
Goal/Todo and Git state; the digest alone is not authority.

## Provider doctor

The doctor performs read-only checks:

```bash
loopx local-synthetic-overlay doctor \
  --synthetic-database-image '<image>@sha256:<digest>' \
  --format json
```

`local_container` is ready only when the Docker client can reach a Docker
daemon. `synthetic_database` is ready only when the exact digest-pinned image
is already local. The doctor never pulls an image or creates a resource.

## Issue and validate

Preview is the default. `--execute` is required to create a system-managed
receipt beneath the configured LoopX runtime root:

```bash
loopx local-synthetic-overlay issue \
  --goal-id <goal> --todo-id <todo> \
  --repo-path <candidate-worktree> \
  --candidate-head <40-char-head> --candidate-tree <40-char-tree> \
  --capability local_container --capability synthetic_database \
  --synthetic-database-image '<image>@sha256:<digest>' \
  --compose-project <task-project> \
  --product-write-scope ZERO --lifetime task_bound \
  --execute --format json
```

Before every governed action, call `validate` with the same exact bindings,
including `compose_project`, and the returned `receipt_id`. Receipt files are
mode `0600`; their containing directory is mode `0700`.

## Cleanup readback

The caller owns its known validation flow and cleanup command. LoopX does not
accept an arbitrary container command. After cleanup, `cleanup-check` uses the
Compose project bound into the digest-protected receipt to prove no container,
volume, or network remains. A different caller-supplied project, an unavailable
Docker daemon, or any residual resource fails closed.
