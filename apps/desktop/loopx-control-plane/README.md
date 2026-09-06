# LoopX Desktop

This directory contains the experimental Tauri shell for the LoopX personal
Agent workspace. It reuses the existing React dashboard and LoopX HTTP
services; it does not introduce another Goal, Todo, Gate, or Chat state owner.

This is currently a preview desktop shell. It is not installed by the LoopX
Python package; use `loopx dashboard` for the supported browser/PWA launch
path. Published LoopX releases attach desktop preview artifacts when the
desktop release workflow succeeds:

- macOS: `.dmg` plus a zipped `.app` bundle;
- Windows: `.msi` plus an NSIS `.exe` installer.

On Apple Silicon macOS, signed updater builds carry an exact matching runtime
source snapshot. Open **Update LoopX** in the bottom-left corner, check for an
update, select **Install update**, then **Restart to finish**. The App verifies
the archive signature before replacing itself; the restarted App installs its
bundled runtime and verifies the selected CLI revision before reconnecting.
This updates both layers without asking the operator to run a terminal command.
Existing desktop builds without this updater need a one-time App replacement.
Windows preview installers retain the manual CLI installation path; they are
not advertised in the signed update feed until their runtime installer is
qualified. Browser/PWA users continue to use `loopx update`.

## Updates And Recovery

The update panel is collapsed by default and opens above the sidebar without
reducing the Goal list height. Automatic checks never install software. Its
advanced options expose stable/main channels, repair, and macOS rollback.
The main channel points to the latest **complete signed build**, not arbitrary
moving Git HEAD. A missing feed or failed signature is an error, not proof that
the App is up to date. Release artifacts and matching runtime stay immutable;
only the main channel feed pointer is replaced.

The App binary owns native windowing, service startup, IPC and update/recovery.
The bundled runtime owns the CLI, HTTP APIs and workspace assets. A runtime-only
CLI update cannot patch native startup or updater bugs; those require an App
update. The App update workflow packages both layers from one Git revision.

If startup cannot proceed, the embedded **Recovery & updates** screen stays
available without a working HTTP service. **Repair this version** reinstalls
the bundled runtime. It may replace a separately updated CLI with this App's
matching snapshot, so it requires an explicit click. No automatic downgrade
is performed when the selected runtime differs. Explicit `LOOPX_BIN` overrides
are retained; an override that still selects another revision fails identity
verification instead of reporting success.

An update journal resumes an approved runtime installation after restart.
Concurrent transactions and additional installs before a required restart are
rejected. Service readiness is distinct from installer completion. macOS keeps
a verified previous App for **Restore previous version**; restart restores its
matching runtime too. Goal state is neither deleted nor migrated backwards by
this action, so data-schema compatibility still governs rollback suitability.
Older backup directories are retained for manual recovery and can consume disk.

The embedded Recovery & updates section includes selectable, copyable diagnostics
with the App version, last failure category, installer exit code when available,
and runtime identity availability/match results. The last failure survives a
subsequent update check within the same App process. Copying never includes raw
installer output, environment variables, local paths, or Goal content. Installation
failures, missing/corrupt bundles, and runtime mismatch show distinct recovery
instructions. A terminal `loopx doctor` checks the terminal-selected runtime;
it does not prove that Desktop selected the same installation or matching revision.

The updater accepts only fixed official HTTPS channels, not browser-provided
commands, paths or download URLs. Its signing private key is confined to the
release secret; the App embeds the public key. PR validation has no signing
secret. Updater signing does not provide Apple notarization. It also does not
change Goal authority, grant capabilities, or stop running agents on behalf of
the user. Services may briefly disconnect during reconciliation.

Published macOS preview artifacts use ad-hoc code signing to verify bundle
integrity without requiring an Apple Developer account. They are not signed
with a Developer ID and are not notarized, so macOS may require the operator
to approve the first launch in System Settings > Privacy & Security.

## Runtime Model

The shell:

1. immediately renders an embedded startup surface instead of a blank WebView;
2. verifies or starts `loopx serve-status` on `127.0.0.1:8766`;
3. verifies or starts `loopx chat` on `127.0.0.1:8767`;
4. loads the versioned LoopX Chat workspace only after its lightweight
   capabilities endpoint is readable, retrying transient service replacement;
5. opens the existing personal workspace in one native window;
6. terminates only the service process groups it started when the window exits.

An unknown process on either LoopX port is a hard startup error. Existing
services are reused only after a successful response exposes both the exact
top-level JSON fingerprint and the same installed release identity as the
selected `loopx` command. Marker-like text in headers or nested values is not
accepted. A service left running by an older installation is reported as stale
and is replaced automatically only after the shell resolves the listener PID
and confirms that its command is the expected `loopx serve-status` or
`loopx chat` invocation on the matching port. If process ownership cannot be
confirmed, startup fails closed without sending a termination signal. Unknown
services remain a hard error. Windows currently keeps this owner-facing error
path instead of terminating an existing process automatically.

Release launchers publish a stable process fingerprint that is independent of
their internal Python entry module. The shell also recognizes the historical
fixed-CLI and lightweight-entrypoint launcher shapes, so upgrading LoopX can
replace an already-running older service without asking the operator to find
and stop it manually.

On macOS, when the standard `com.loopx.status` or `com.loopx.chat` LaunchAgent
is loaded, Desktop keeps launchd as the single service owner. After replacing a
stale listener it requests a launchd wake and waits through the throttle
interval instead of racing a second Desktop-owned process onto the same port.

The WebView is pinned to the loopback Chat origin served by the installed
LoopX release. Dashboard requests to the status and Chat services remain
restricted to loopback CORS and the existing preview/apply authority boundary.

## Coexistence With `loopx dashboard`

The desktop shell and `loopx dashboard` share the same loopback services on
`8766` and `8767`, and both entry points reuse an already-running matching
LoopX service:

- Start `loopx dashboard` first, then open the desktop shell: the shell keeps
  using the running status and Chat services and only opens the native window.
- Start the desktop shell first, then run `loopx dashboard`: the command
  detects the matching LoopX Chat service, prints its URL, and opens the
  browser/PWA route without starting a second server.

Either order works. Closing the desktop window stops only the service process
groups it started; a Chat service started by `loopx dashboard` keeps running
until that command is stopped.

## Prerequisites

- A working Python interpreter for runtime installation; existing managed
  installations preserve their interpreter. Windows requires a separately
  installed LoopX CLI. Set `LOOPX_BIN` only for deliberate runtime overrides.
- Node.js 20.19+ or 22.12+ for dashboard builds.
- Rust stable and the platform-specific Tauri build dependencies.

Linux requires WebKitGTK 4.1 and GTK 3 development packages. See the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Development

```bash
cd apps/desktop/loopx-control-plane
npm install
python3 ../../../scripts/desktop_runtime_bundle.py
npm run dev
```

## Validation

```bash
cd apps/desktop/loopx-control-plane/src-tauri
cargo fmt --check
cargo test
cargo clippy --all-targets -- -D warnings

cd ..
./scripts/dashboard.sh build
npm run build
```

`npm run build` produces the configured platform bundles under
`src-tauri/target/release/bundle/`. The release workflow builds macOS `.dmg`
and `.app.zip` artifacts on macOS, Windows `.msi` and `.exe` artifacts on
Windows, and uploads them to the GitHub Release that triggered the workflow.
It verifies the ad-hoc macOS app signature and disk-image integrity before
upload. A separate `DESKTOP-SHA256SUMS` manifest covers all desktop artifacts
attached by the workflow, and release builds use the Git tag as the desktop
bundle version. A manual rerun for an existing tag is an explicit full desktop
republish: it rebuilds both macOS and Windows assets, preserves the previous
desktop set as a short-lived workflow artifact, validates the complete new
four-file set, replaces all desktop binaries, and uploads the new checksum
manifest last. Binary hashes may therefore change after a manual rerun.

## Disable Or Remove

Close the desktop window to stop service processes owned by the shell. Services
that were already running before the shell opened are left untouched. Removing
the desktop package does not modify LoopX project or runtime state.
