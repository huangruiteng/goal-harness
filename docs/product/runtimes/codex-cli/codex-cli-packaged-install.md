# Codex CLI Packaged Install Path

Status: shipped PyPI path with archive fallback.

LoopX should be easy to adopt from the tool the user already has open.
For Codex CLI users, the first successful path is:

1. Open Codex CLI TUI in a project repo.
2. Paste one LoopX start message.
3. If `loopx` is missing, let the agent install the PyPI distribution and its
   packaged workflow skills.
4. Return to the same TUI with current objective, gate, todo, and next safe action.

The user should not have to clone this repository before learning whether
LoopX helps their project.

## Current User Path

For a fresh machine, install the release without a manual clone:

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx doctor
```

The wheel installs the `loopx` CLI and carries the reusable Codex workflows.
`workflow-skills --install` materializes the rich workflow skills and managed
`$loopx` entry under `~/.codex/skills`, with a versioned readback. Additional
host command facades remain explicit through `loopx slash-commands --install`:

- `~/.codex/skills/loopx*/SKILL.md` for explicit Codex command-facade
  invocation through `$loopx` or `/skills`;
- `~/.codex/skills/loopx-project/SKILL.md` for the distinct project workflow
  skill shown as `LoopX Project` in `/skills`;
- `~/.claude/skills/loopx*/SKILL.md` for Claude Code slash-command discovery.

Current verified Codex CLI builds still reject user-installed `/loopx` and
`/prompts:loopx` commands, so the packaged install reports Codex CLI as an
unsupported native slash surface. For an explicit Codex skill invocation, use
`$loopx` or choose `loopx` from `/skills`. For the visible long-running TUI
loop, use `loopx codex-cli-bootstrap-message --project .`, paste the generated
setup into the TUI, then set the generated `/goal <thin task_body>`.

The GitHub Pages archive installer remains the recovery fallback when a usable
Python package environment is unavailable. It intentionally skips
`loopx-canary`; contributors who want a canary should clone the repository and
run `scripts/install-local.sh`.

## Codex CLI TUI Message

The agent-first start message can now be stricter about install repair:

```text
Start LoopX for this repo. If `loopx` is missing, install it with
`python3 -m pip install --upgrade loopx`, run
`loopx workflow-skills --install`, then connect this project. Show me the
current objective, concrete user gate if any, top todos, and next safe action before
running longer work. Keep me in this Codex CLI TUI unless I explicitly accept a
headless fallback.
```

This keeps the product hierarchy clear:

- first run: one visible TUI message;
- install repair: no manual clone required;
- generated bootstrap packet: exact TUI paste block, no-clone repair command,
  and transcript-free validation checklist;
- copy-only mode: `codex-cli-bootstrap-message --message-only` prints just the
  pasteable TUI block, while the default output remains the review packet;
- smoke bundle: `codex-cli-tui-bootstrap-smoke-bundle` verifies the fresh-repo
  installer, paste block, quota guard, and bounded writeback commands without
  launching Codex or reading transcripts;
- recurring automation: separate driver work;
- contributor development: clone plus canary remains available.

## Update Path

For PyPI users, upgrade the distribution and refresh host material together:

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx slash-commands --install
loopx doctor
```

For users installed through the archive fallback, keep the explicit archive
update flow:

```bash
loopx update --check
loopx update --dry-run
loopx update --execute
loopx doctor
```

The update command plans the source archive, reports the installed release
snapshot, preserves runtime state under `~/.codex/loopx`, and refreshes the
executable and skills together when `--execute` is accepted.

For the normal GitHub repo/ref source, `--check` compares the installed package
version with that exact ref using a short, read-only network probe. Offline
checks still report local install health and make the missing remote comparison
explicit. Custom archive URLs skip this comparison rather than guessing which
version they contain.

`loopx update` uses the same `stable` ref by default. Use `loopx update --ref
main` only when you intentionally want a dev/head refresh instead of the stable
channel.

Re-running the curl installer is still the repair/fallback path when the local
wrapper or release snapshot is broken enough that `loopx update` cannot run.

## Contributor Path

For contributors and registered peers working on LoopX itself, keep using a
real checkout:

```bash
git clone https://github.com/huangruiteng/loopx ~/loopx
~/loopx/scripts/install-local.sh
loopx doctor
loopx-canary doctor
```

That path installs both the stable release wrapper and a live canary wrapper,
which is useful for validating local changes before promotion.

## Future Packaging

PyPI is the current default. Later channels may add:

- a signed or checksum-pinned release archive;
- a Homebrew formula for macOS users;
- signed release manifests that report current release id, latest available
  release, and installed skill freshness.

Do not make these future channels block the current Codex CLI TUI path. The
first product win is that a user can paste one message and get a working local
control plane without leaving the repo.
