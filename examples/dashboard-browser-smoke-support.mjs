import { existsSync, readdirSync } from "node:fs";
import { once } from "node:events";
import { rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { basename, resolve } from "node:path";

const require = createRequire(import.meta.url);

export function loadPlaywright() {
  const candidates = [
    process.env.LOOPX_PLAYWRIGHT_PACKAGE,
    resolve(homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"),
  ].filter(Boolean);

  try {
    return require("playwright");
  } catch {
    // Try the configured or bundled runtime below.
  }

  for (const candidate of candidates) {
    if (!existsSync(candidate)) {
      continue;
    }
    try {
      return require(candidate);
    } catch {
      // Keep looking for a usable runtime.
    }
  }

  throw new Error("Playwright package not found; install playwright or set LOOPX_PLAYWRIGHT_PACKAGE");
}

function findChromeHeadlessShell(root) {
  if (!existsSync(root)) {
    return null;
  }
  const matches = [];
  const pending = [root];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = resolve(current, entry.name);
      if (entry.isDirectory()) {
        pending.push(path);
      } else if (entry.isFile() && entry.name === "chrome-headless-shell") {
        matches.push(path);
      }
    }
  }
  return matches.sort().at(-1) ?? null;
}

export async function launchBrowser(chromium) {
  const configuredPath = process.env.LOOPX_CHROME_HEADLESS_SHELL;
  const playwrightPath = chromium.executablePath();
  const executablePath = [configuredPath, playwrightPath]
    .find((candidate) => candidate && basename(candidate) === "chrome-headless-shell" && existsSync(candidate))
    ?? findChromeHeadlessShell(resolve(homedir(), ".cache/hyperframes/chrome"))
    ?? findChromeHeadlessShell(resolve(homedir(), ".cache/ms-playwright"))
    ?? findChromeHeadlessShell(resolve(homedir(), "Library/Caches/ms-playwright"));
  if (!executablePath) {
    throw new Error("chrome-headless-shell not found; set LOOPX_CHROME_HEADLESS_SHELL");
  }
  return chromium.launch({ executablePath, headless: true });
}

async function stopServer(server) {
  if (!server || server.exitCode !== null || server.signalCode !== null) {
    return;
  }
  const exited = once(server, "exit");
  server.kill("SIGTERM");
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise((resolveTimeout) => setTimeout(() => resolveTimeout(false), 5_000)),
  ]);
  if (!stopped && server.exitCode === null && server.signalCode === null) {
    const forceExited = once(server, "exit");
    server.kill("SIGKILL");
    await forceExited;
  }
}

export async function cleanupBrowserSmoke({ browser, fixturePaths, server }) {
  const errors = [];
  try {
    if (browser) {
      await browser.close();
    }
  } catch (error) {
    errors.push(error);
  }
  try {
    await stopServer(server);
  } catch (error) {
    errors.push(error);
  }
  for (const fixturePath of fixturePaths) {
    try {
      await rm(fixturePath, { force: true });
    } catch (error) {
      errors.push(error);
    }
  }
  if (errors.length > 0) {
    throw new AggregateError(errors, "Browser smoke cleanup failed");
  }
}
