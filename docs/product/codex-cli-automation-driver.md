# Codex CLI Automation Driver Audit

Status: product contract and implementation target.

Goal Harness should make Codex CLI feel easy before it feels automated. The
primary path is still the Codex TUI: the user starts from a project repo, sends
one Goal-Harness-generated message, and can keep watching, steering, reviewing,
or taking over. Automation is allowed only when it preserves that visible
control surface or falls back explicitly.

## Current Finding

The current local Codex CLI help surface exposes useful execution and session
primitives:

- `codex [PROMPT]` starts the interactive TUI with an initial prompt.
- `codex resume [SESSION_ID] [PROMPT]` can resume an interactive session and
  start it with a prompt.
- `codex exec [PROMPT]` runs a non-interactive executor loop.
- `codex --remote <ADDR>`, `codex app-server`, and `codex remote-control` expose
  experimental app-server / remote-control surfaces worth probing.

It does not expose a mature native recurring scheduler for Goal Harness. Treat
recurrence as a Goal Harness local-driver concern until Codex provides a
first-class automation primitive.

The important product distinction is:

| Surface | What It Proves | What It Does Not Prove |
| --- | --- | --- |
| `codex [PROMPT]` | one-message TUI bootstrap is viable | scheduled wakeups |
| `codex resume ... [PROMPT]` | a visible resume proof is plausible | safe injection into an already-open TUI |
| `codex exec` | headless fallback is viable | preserved TUI experience |
| `remote-control` / app-server | a future visible-control bridge may exist | production-safe Goal Harness driver semantics |

## Driver Shape

The v0 driver should be explicit and conservative:

1. A scheduler wakes up: manual command, `launchd`, cron, or a future local
   daemon.
2. The driver runs `goal-harness quota should-run --goal-id <goal> --agent-id
   <agent>`.
3. If user action is required, the driver surfaces only the concrete user gate
   and stops.
4. If the side-agent workspace guard fires, the driver relocates to an
   independent worktree before any file edit.
5. The driver runs `goal-harness codex-cli-visible-driver-plan`.
6. If the plan proves a visible attach path, the driver may attempt a visible
   `resume` / remote-control turn behind an idle guard.
7. If no visible attach path is proven, the driver keeps TUI bootstrap primary
   and offers `goal-harness codex-cli-exec-handoff` as an explicit headless
   fallback.
8. The driver spends quota only after validated writeback.

The local driver must never read or publish:

- raw Codex transcripts;
- credentials;
- hidden session files;
- private logs;
- local Goal Harness runtime state that would leak into public docs or
  fixtures.

## Scheduler Options

| Option | Good For | Not Good For | v0 Use |
| --- | --- | --- | --- |
| Manual command | transparent user testing | unattended work | default proof path |
| `launchd` | local recurring wakeups on macOS | cross-platform install, visible TUI attach by itself | first packaged scheduler |
| cron | simple Unix recurrence | user-friendly install, logs, env repair | documented fallback |
| GitHub Actions | public docs/build/status checks | local TUI, local credentials, workstation state | Pages and public bundle only |
| Local daemon | best long-term UX | install/update/auth complexity | later product milestone |

## Success Criteria

- One pasted TUI message can start the Goal Harness loop in a repo.
- A scheduled driver can decide whether work is allowed without reading private
  Codex session data.
- A visible resume / remote-control proof shows the turn is visible,
  interruptible, and idle-guarded before Goal Harness calls it
  session-attached automation.
- Headless `codex exec` remains a named fallback, not the default user story.
- Every automatic turn writes compact evidence or a precise blocker before
  quota spend.

## Next Build Slice

Implement a dry-run-first local driver command that composes the existing
pieces:

```bash
goal-harness codex-cli-visible-driver-plan --project . --goal-id <goal> --agent-id <agent>
goal-harness codex-cli-bootstrap-message --project . --goal-id <goal> --agent-id <agent>
goal-harness codex-cli-exec-handoff --project . --goal-id <goal> --agent-id <agent>
```

The first runnable milestone should not try to be clever. It should emit the
exact driver decision, explain whether the user keeps the TUI path or has opted
into headless fallback, and include an idle-guard placeholder before any
visible resume / remote-control experiment.
