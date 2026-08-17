# Installing LoopX

PyPI is the default LoopX release channel. Use Python 3.11 or later in an
active virtual environment, a managed user environment, or another environment
whose console scripts are on `PATH`:

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx doctor
```

The package has no runtime dependencies outside the Python standard library.
`workflow-skills --install` copies the packaged LoopX workflow skills into the
user's Codex skill directory and writes a revision readback; it does not change
project state or grant repository, network, or merge authority. Restart the
host after first install so it reloads the new skills.

If Python packages are externally managed on the machine, use a dedicated tool
environment instead of modifying the system interpreter:

```bash
pipx install loopx
loopx workflow-skills --install
loopx doctor
```

## Host Command Surfaces

The workflow-skill command installs the rich Codex workflows and managed
`$loopx` entry. Install additional command facades only for hosts that need
them:

```bash
loopx slash-commands --install
```

The default command-facade set covers Codex, Claude Code, and OpenCode. Other
surfaces remain explicit; inspect `loopx slash-commands --help` before enabling
one. Host integration changes command discovery only. It does not grant LoopX
permission to write a repository, contact external systems, or bypass a user
gate.

## Upgrade And Repair

Upgrade the Python distribution first, then refresh the host material from the
same version:

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx slash-commands --install
loopx doctor
```

`loopx doctor` reports `install_kind: python_distribution` for this path and
returns the same pip-native repair sequence when packaged skills are missing or
stale.

## Archive Fallback

The GitHub Pages installer remains a fallback for machines where an appropriate
Python package environment is unavailable or the CLI is too damaged to run its
own repair path:

```bash
curl -fsSL https://huangruiteng.github.io/loopx/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
loopx doctor
```

This fallback installs an archive snapshot, wrapper, man page, and host
materials together. Its update path remains `loopx update`; do not mix the
archive and PyPI upgrade mechanisms for the same active executable.

## Uninstall

Remove LoopX-owned host material before uninstalling the Python package:

```bash
loopx slash-commands --uninstall
loopx workflow-skills --uninstall
python3 -m pip uninstall loopx
```

Both host uninstallers preserve same-name files whose content changed after
LoopX installed them. Project-local `.loopx/`, `.codex/goals/`, evidence, and
runtime state are not deleted by package uninstall.

Contributors who need a live canary should use a real checkout and
`scripts/install-local.sh`; see [Getting Started](getting-started.md).
