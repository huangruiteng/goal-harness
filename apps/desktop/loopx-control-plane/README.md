# LoopX Control Plane Desktop

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

## Runtime Model

The shell:

1. verifies or starts `loopx serve-status` on `127.0.0.1:8766`;
2. verifies or starts `loopx chat` on `127.0.0.1:8767`;
3. serves the compiled dashboard from a random loopback port;
4. opens the existing personal workspace in one native window;
5. terminates only the service process groups it started when the window exits.

An unknown process on either LoopX port is a hard startup error. Existing
services are reused only after a successful response exposes the exact expected
top-level JSON fingerprint; marker-like text in headers or nested values is not
accepted.

The WebView can navigate only inside its own loopback asset origin. Dashboard
requests to the status and Chat services remain restricted to loopback CORS and
the existing preview/apply authority boundary.

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

## Disable Or Remove

Close the desktop window to stop service processes owned by the shell. Services
that were already running before the shell opened are left untouched. Removing
the desktop package does not modify LoopX project or runtime state.
