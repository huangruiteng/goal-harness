# Architecture

Goal Harness has five layers.

1. **Registry**: lists known goals, their repos, adapters, status, and guards.
2. **Goal state**: the active state file for one goal.
3. **Adapter pre-tick**: a read-only project-specific probe.
4. **Run log**: JSON and Markdown reports saved per goal.
5. **Run history**: compact indexes consumed by agents, heartbeats, and UI.

```text
project goal state
  + private registry
  + project adapter
        |
        v
shared runtime root
        |
        v
goal-harness history/check
        |
        v
agent tick / heartbeat / future UI
```

The core repository intentionally avoids domain logic. A data experiment goal,
a note-maintenance goal, and a harness self-improvement goal should share the
same runtime and contract, but use different adapters.
