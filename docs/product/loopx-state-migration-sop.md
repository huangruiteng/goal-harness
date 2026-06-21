# LoopX State Migration SOP

Status: draft for the LoopX rename PR.

This SOP is for existing local users who already have Goal Harness state under
the legacy runtime and want to move that state into LoopX without keeping a
legacy CLI compatibility alias.

## What Moves

`loopx migrate-state` is a one-shot migration tool. It does not make
`goal-harness` a supported command. It only reads an explicit legacy registry,
rewrites selected goal ids and local path prefixes, then writes LoopX state.

It can move:

- a selected goal entry into `.loopx/registry.json`;
- the selected active-state file into the rewritten project path;
- selected runtime history under `~/.codex/loopx/goals/<new-goal-id>/`;
- the migrated project registry into `~/.codex/loopx/registry.global.json`.

It intentionally requires an explicit goal selection: either repeat
`--goal-id` for known goals or pass `--all-goals` after previewing the legacy
registry. There is no default “migrate everything” behavior.

## Recommended Sequence

1. Install LoopX from the rename branch or released package.

```bash
loopx doctor
```

2. Preview one goal migration.

```bash
loopx --registry .loopx/registry.json migrate-state \
  --legacy-registry ~/.codex/goal-harness/registry.global.json \
  --legacy-runtime-root ~/.codex/goal-harness \
  --goal-id goal-harness-meta \
  --goal-id-map goal-harness-meta=loopx-meta \
  --path-map /path/to/old/repo=/path/to/new/repo \
  --copy-active-state
```

The preview should show `dry_run=true`, the selected old goal id, and the
migrated new goal id. It should not create `.loopx/registry.json`.

3. Execute after the preview looks right.

```bash
loopx --registry .loopx/registry.json migrate-state \
  --legacy-registry ~/.codex/goal-harness/registry.global.json \
  --legacy-runtime-root ~/.codex/goal-harness \
  --goal-id goal-harness-meta \
  --goal-id-map goal-harness-meta=loopx-meta \
  --path-map /path/to/old/repo=/path/to/new/repo \
  --copy-active-state \
  --copy-runtime \
  --execute
```

Use `--copy-runtime` only when the old run history should remain visible to
LoopX. For a clean rename validation lane, copying active state alone is often
enough.

4. For a machine with several existing projects, preview the full legacy
   registry before doing a batch migration.

```bash
loopx --registry ~/.codex/loopx/registry.global.json migrate-state \
  --legacy-registry ~/.codex/goal-harness/registry.global.json \
  --legacy-runtime-root ~/.codex/goal-harness \
  --target-runtime-root ~/.codex/loopx \
  --all-goals \
  --copy-active-state \
  --copy-runtime \
  --no-global-sync
```

Only execute after the preview lists exactly the expected goals:

```bash
loopx --registry ~/.codex/loopx/registry.global.json migrate-state \
  --legacy-registry ~/.codex/goal-harness/registry.global.json \
  --legacy-runtime-root ~/.codex/goal-harness \
  --target-runtime-root ~/.codex/loopx \
  --all-goals \
  --copy-active-state \
  --copy-runtime \
  --no-global-sync \
  --execute
```

This batch path is for the shared local control plane. When a repo becomes the
active working checkout again, run the one-goal project-local migration from
that repo so it also has its own `.loopx/registry.json`.

5. Verify the migrated state.

```bash
loopx --registry .loopx/registry.json registry
loopx --registry .loopx/registry.json status --agent-id codex-side-bypass
loopx --registry .loopx/registry.json quota should-run \
  --goal-id loopx-meta \
  --agent-id codex-side-bypass
loopx --registry .loopx/registry.json check --scan-root .
```

6. Update automations only after the migrated goal is visible.

The heartbeat prompt should use the new goal id and the LoopX command:

```text
Advance `loopx-meta` from the registry-declared active state.
Use skills: `loopx-project`; if surprising/tiny/contradictory, `loopx-self-repair`.
LoopX CLI is source of truth.
```

Do not keep an old automation id or prompt body around as a hidden
compatibility path. If a Codex App heartbeat cannot be renamed in place, delete
the old heartbeat and create a new `loopx` heartbeat.

## Safety Rules

- Start with one goal, not the whole registry.
- Use `--all-goals` only after a dry-run shows the expected goal list.
- Keep migration state local-private; do not commit `.loopx/`, `.local/`, or
  runtime history.
- Keep old command names only in migration SOPs, migration code, and
  no-compat negative assertions.
- Stop before GitHub repository rename, Pages cutover, package publication, or
  destructive cleanup unless the maintainer explicitly approves that gate.
