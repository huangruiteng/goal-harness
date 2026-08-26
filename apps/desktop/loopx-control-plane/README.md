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

The desktop shell still depends on a local `loopx` command at runtime. Install
or update the LoopX CLI first, then open the desktop app.

Official macOS release artifacts must be signed with an Apple Developer ID
certificate and notarized before upload. Maintainers configure
`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `KEYCHAIN_PASSWORD`,
`APPLE_ID`, `APPLE_PASSWORD`, and `APPLE_TEAM_ID` as GitHub Actions secrets.
Pull requests still build unsigned preview artifacts, but the release workflow
fails closed when those secrets are unavailable rather than publishing a DMG
that macOS Gatekeeper rejects.

## Runtime Model

The shell:

1. verifies or starts `loopx serve-status` on `127.0.0.1:8766`;
2. verifies or starts `loopx chat` on `127.0.0.1:8767`;
3. loads the versioned LoopX Chat workspace from the local Chat service;
4. opens the existing personal workspace in one native window;
5. terminates only the service process groups it started when the window exits.

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

- LoopX installed and available as `loopx`; set `LOOPX_BIN` to override it.
- Node.js 20.19+ or 22.12+ for dashboard builds.
- Rust stable and the platform-specific Tauri build dependencies.

Linux requires WebKitGTK 4.1 and GTK 3 development packages. See the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Development

```bash
cd apps/desktop/loopx-control-plane
npm install
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
It notarizes both the app and its disk image, then validates macOS code
signing, Gatekeeper assessment, and both stapled tickets before upload. A
separate `DESKTOP-SHA256SUMS` manifest covers all desktop artifacts attached
by the workflow, and release builds use the Git tag as the desktop bundle
version.

## Disable Or Remove

Close the desktop window to stop service processes owned by the shell. Services
that were already running before the shell opened are left untouched. Removing
the desktop package does not modify LoopX project or runtime state.
