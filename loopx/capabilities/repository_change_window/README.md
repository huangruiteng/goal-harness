# Repository Change Window

`repository-change-window` is a built-in, default-off capability for two
related caller outcomes:

1. apply a typed local schedule before repository commits and pushes; and
2. retain a restart-safe inventory of unmerged work when that schedule blocks
   delivery.

The capability owns policy evaluation and pending-change lifecycle. The
bundled `git-hook` provider owns Git integration. The LoopX Kernel remains the
authority for goals, todos, gates, and quota; installing this provider does not
grant repository or remote-write authority.

## Install and inspect

Every mutating command previews by default. The built-in schedule shown below
blocks Monday through Friday from 10:00 inclusive until 21:00 exclusive in
`Asia/Shanghai`:

```bash
loopx change-window install --repo-path . --format json
loopx change-window install --repo-path . --execute --format json

loopx change-window status --repo-path . --format json
loopx change-window verify --repo-path . --format json
```

Customize one typed v0 window with repeatable weekdays and IANA timezone data:

```bash
loopx change-window install \
  --repo-path . \
  --timezone Europe/Berlin \
  --blocked-weekday mon \
  --blocked-weekday tue \
  --blocked-start 09:30 \
  --blocked-end 18:00 \
  --execute \
  --format json
```

An end earlier than its start is an overnight window associated with the day
on which it starts. Equal start and end values are rejected instead of being
interpreted as an implicit full-day lock.

The provider writes only repository-local Git configuration and private state
under the repository's Git common directory. Linked worktrees therefore share
one installation and policy. The managed `pre-commit` and `pre-push` wrappers
evaluate the policy and then call the hook route that was effective before
installation. A modified wrapper, changed hook route, invalid policy, or
missing state fails verification closed.

The execution clock is not a caller argument. Live hooks use the invocation
clock; tests inject an aware fake clock through the Python contract so an
artifact timestamp cannot move a commit or push into an allowed window.

## Pending-change ledger

When a hook blocks a commit or push, it automatically records or refreshes a
stable branch-scoped pending change. The shared runtime event contains:

- a stable `change_id` and credential-free repository identity;
- branch and exact head OID;
- counts and content digests for staged, unstaged, and untracked state;
- the typed gate decision and next eligible time; and
- lifecycle source and update time.

It does **not** contain code, a patch, a diff body, credential material, file
names, or a local absolute path. A separate mode-`0600` machine-private locator
lets `verify` find the producing worktree; list/readback packets never expose
that path.

Add goal, Todo, PR, write-scope, and validation lineage explicitly when it is
available:

```bash
loopx change-window record \
  --repo-path . \
  --goal-id example-goal \
  --todo-id todo_example123 \
  --write-scope 'src/**' \
  --validation-ref 'pytest:tests/unit:passed' \
  --execute \
  --format json

loopx change-window list --state open --format json
loopx change-window verify --change-id change_example123 --format json
```

`record` is idempotent for the same identity and fingerprint. A changed head
or worktree fingerprint appends a `refreshed` event rather than overwriting
history. `verify` distinguishes missing locator/worktree, repository mismatch,
missing branch, missing recorded head, branch movement, and worktree-fingerprint
drift.

Close the lifecycle only with a typed outcome and compact public-safe evidence:

```bash
loopx change-window resolve \
  --change-id change_example123 \
  --resolution merged \
  --evidence 'github:owner/repo#123' \
  --execute \
  --format json
```

The terminal outcomes are `merged`, `superseded`, and `abandoned`.
`superseded` also requires `--superseded-by`. Exact retries are idempotent;
conflicting terminal evidence fails closed. Resolution retains the public-safe
event history and removes the no-longer-needed machine-private worktree locator.

## Uninstall and rollback

Preview first, then remove the managed provider:

```bash
loopx change-window uninstall --repo-path . --format json
loopx change-window uninstall --repo-path . --execute --format json
```

Uninstall restores the exact repository-local `core.hooksPath` value that
preceded installation, or removes the local override when none existed. It
refuses to overwrite drifted provider state. Pending-change history is not
deleted by uninstall; resolve it through the ledger lifecycle instead.

## Authority and enforcement boundary

This is local workflow enforcement, not branch protection. Git client options
such as `--no-verify`, another machine, or a server-side write can bypass local
hooks. Use remote branch protection or server-side hooks for a security
boundary. The capability does not push, merge, create a PR, modify protected
branches, or treat schedule admission as permission for any of those effects.
