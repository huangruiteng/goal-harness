# Sanitized CS-Notes Integration Example

This is a sanitized shape, not a copy of a private local setup.

## Project Files

```text
CS-Notes/
  .local/ACTIVE_GOAL_STATE.md
  .local/GOAL_HARNESS_REGISTRY.json
  Notes/snippets/codex-goal-pre-tick.py
```

## Pre-Tick Pattern

The project pre-tick reads project-specific state, then adds Goal Harness
signals:

```bash
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json --format json history
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json --format json check --scan-root Notes/snippets
```

The returned compact signal can be exposed as:

```json
{
  "goal_harness_contract_health": {
    "ok": true,
    "errors": 0,
    "warnings": 0,
    "checks": 3
  }
}
```

Keep the real registry and active state private.
