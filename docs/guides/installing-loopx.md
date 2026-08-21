# Installing LoopX

PyPI is the default LoopX release channel. Use Python 3.11 or later in an
active virtual environment, a managed user environment, or another environment
whose console scripts are on `PATH`:

```bash
python3 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx doctor
```

LoopX's Effect Program core runs in a managed, idle-exiting TypeScript runtime
and requires Node.js 22.6 or later. LoopX starts and reuses that local runtime
automatically; users do not run a daemon manually. The runtime binds only to
loopback, authenticates requests with a user-private token, rotates when the
packaged Effect core changes, and exits after an idle period. `loopx doctor`
reports it as `ready`, `missing`, `unsupported`, or `probe_failed`; a missing
or stale runtime fails closed instead of falling back to a second Python rule
engine. The same doctor projection exposes `runtime_lifecycle.state` as
`running`, `stopped`, or `unavailable`, plus a public-safe `diagnostic_code`;
the App can render this projection without inventing a second health model.
`stopped` is healthy and means the idle-exited runtime will restart on the next
control-plane request. Validate Node before installing or upgrading LoopX:

```bash
node --version
# v22.6.0 or newer
```

Use `loopx doctor --deep` after installation to start the managed runtime and
exercise the packaged Effect semantics and native journal checkpoint handler.
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

## Native Windows PowerShell 7

The PyPI distribution is also the default native Windows path. From PowerShell
7, use a Python 3.11+ interpreter and validate the installed console script:

```powershell
py -3.11 -m pip install --upgrade loopx
loopx workflow-skills --install
loopx doctor
```

Contributors and operators who deliberately need an immutable snapshot from a
trusted checkout can install the native PowerShell launcher without Bash,
POSIX symlinks, or WSL:

```powershell
git clone https://github.com/huangruiteng/loopx.git "$HOME/loopx"
Set-Location "$HOME/loopx"
pwsh -NoLogo -NoProfile -File .\scripts\install-windows.ps1 `
  -Python (Get-Command python).Source `
  -AddToUserPath
loopx doctor --deep
```

The snapshot installer validates the candidate before promotion, writes an
atomic release pointer, and places `loopx.ps1` plus its release-pointer sidecar
in `$HOME/.local/bin` by default. `-InstallRoot`, `-BinDir`, and `-SkillsDir`
remain explicit overrides; a fresh shell discovers a custom install through
the sidecar, without requiring `LOOPX_CURRENT_RELEASE_FILE`. Use `-SkipSkills`
when another trusted host manager owns the LoopX skill files, and omit
`-AddToUserPath` when PATH changes are not authorized.

Native snapshot `loopx update` and automatic rollback fail closed. To upgrade
or roll back, check out the intended trusted revision, rerun
`scripts/install-windows.ps1`, then verify `loopx doctor --deep`. The previous
release directories remain under the selected install root until the operator
removes them; changing a pointer by hand is not the supported rollback path.

Before removing a native snapshot, run the managed host uninstallers while the
launcher is still available, then remove the launcher files and snapshot root:

```powershell
loopx slash-commands --uninstall
loopx workflow-skills --uninstall
Remove-Item -LiteralPath "$HOME/.local/bin/loopx.ps1" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$HOME/.local/bin/loopx-current-release.json" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$HOME/.local/share/loopx" -Recurse -Force -ErrorAction SilentlyContinue
```

If installation used `-AddToUserPath`, remove the chosen `BinDir` from the
Windows user PATH through Windows Environment Variables after uninstalling.
Installation and PATH opt-in only expose local command and skill files. They do
not grant repository, network, credential, external-system, or merge authority,
and uninstall does not delete project-local `.loopx/`, `.codex/goals/`, or
evidence state.

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
stale. It also verifies the required TypeScript Effect runtime before a
control-plane upgrade is considered healthy. Runtime metadata is fingerprinted
by the installed sources, so an upgraded LoopX starts a matching process while
an older process exits after becoming idle. When a release needs to be rolled
back, reinstall the previously selected version, refresh the packaged host
material, and validate again:

```bash
python3 -m pip install "loopx==<previous-version>"
loopx workflow-skills --install
loopx slash-commands --install
loopx doctor
```

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
