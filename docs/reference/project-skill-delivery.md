# Project Skill Delivery

LoopX can ship a canonical skill without adding it to every user's global agent
configuration. A release-owned skill opts into project delivery by adding:

```text
skills/<skill-id>/.loopx-skill-scope
```

with the exact content:

```text
project
```

The global installer keeps that source in the versioned LoopX release and skips
global skill installation. A connected project can then install one or more
host-native managed copies:

```bash
loopx project-skill install \
  --project . \
  --skill <skill-id> \
  --surface codex \
  --surface claude-code \
  --surface opencode \
  --execute
```

## Surface Map

| Surface | Project target |
| --- | --- |
| `codex` | `.agents/skills/<skill-id>/` |
| `claude-code` | `.claude/skills/<skill-id>/` |
| `opencode` | `.opencode/skills/<skill-id>/` |

These locations follow the host discovery contracts documented by
[Codex](https://developers.openai.com/codex/skills),
[Claude Code](https://code.claude.com/docs/en/slash-commands#where-skills-live),
and [OpenCode](https://opencode.ai/docs/skills/#place-files).

## Lifecycle

All mutations are preview-first:

```bash
loopx project-skill status \
  --project . \
  --skill <skill-id> \
  --surface codex

loopx project-skill install \
  --project . \
  --skill <skill-id> \
  --surface codex

loopx project-skill uninstall \
  --project . \
  --skill <skill-id> \
  --surface codex
```

Add `--execute` only after reviewing the plan. The managed marker records the
release version, source digest, skill id, and host surface. Install and
uninstall fail closed for unmanaged targets, local modifications, symlink
escapes, missing project connection, or failed digest readback.

Multi-surface installation stages every target before replacement and restores
earlier targets if a later replacement fails. The implementation copies the
whole skill directory instead of linking `SKILL.md`, so supporting scripts,
references, and host metadata remain complete.

## Authority Boundary

Project skill delivery controls discoverability, not domain authority. A
project-local skill cannot create a LoopX goal, todo, write scope, operator
gate, material-store authority, or external permission. Each consumer
capability still declares its own activation and mutation contract.

`loopx-material` is the first consumer: the skill can be visible in a project
while Material Lifecycle remains default-off for every goal that has not
explicitly activated it.
