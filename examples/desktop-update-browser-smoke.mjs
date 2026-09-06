// Production bundle, synthetic status and native IPC double. Never installs software.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { launchBrowser, loadPlaywright } from "./dashboard-browser-smoke-support.mjs";

const root = resolve(import.meta.dirname, "..");
const output = resolve(root, "output/playwright/desktop-update");
const status = await readFile(resolve(root, "examples/status.example.json"));
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png" };
const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/status.json") { res.setHeader("Content-Type", "application/json"); res.end(status); return; }
  if (url.pathname.startsWith("/api/")) { res.setHeader("Content-Type", "application/json"); res.end('{"ok":true,"sessions":[],"adapters":[]}'); return; }
  const relative = url.pathname === "/chat/" ? "/chat/index.html" : url.pathname;
  const base = url.pathname.startsWith("/boot/") ? resolve(root, "apps/desktop/loopx-control-plane/static") : resolve(root, "loopx/web");
  const path = resolve(base, `.${url.pathname.startsWith("/boot/") ? url.pathname.slice(5) : relative}`);
  if (!path.startsWith(`${base}/`)) { res.writeHead(403).end(); return; }
  try { res.setHeader("Content-Type", types[extname(path)] ?? "application/octet-stream"); res.end(await readFile(path)); }
  catch { res.writeHead(404).end(); }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await launchBrowser(loadPlaywright().chromium);
try {
  await mkdir(output, { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const calls = [];
  let nativeState = null;
  let failUpdate = false;
  await page.exposeFunction("nativeInvoke", async (command, args) => {
    if (command === "desktop_update_status") return { state: nativeState, app_version: "0.5.4" };
    calls.push({ command, args });
    if (failUpdate) throw new Error("private diagnostic must not be displayed");
    await new Promise((done) => setTimeout(done, 150));
    nativeState = { phase: args.action === "check" ? "available" : "restart_required", details: { version: "0.5.5", channel: args.channel } };
    return nativeState;
  });
  await page.addInitScript(() => {
    localStorage.setItem("loopx-pw-locale", "zh-CN");
    window.__TAURI__ = { core: { invoke: (...args) => window.nativeInvoke(...args) } };
  });
  await page.goto(`${origin}/chat/?statusUrl=/status.json`);
  const trigger = page.getByRole("button", { name: "有可用更新" });
  await trigger.waitFor();
  assert.equal(await trigger.getAttribute("aria-expanded"), "false");
  const footerBefore = await page.locator(".personal-sidebar-footer").boundingBox();
  await page.screenshot({ path: resolve(output, "update-collapsed.png") });
  await trigger.click();
  assert.deepEqual(await page.locator(".personal-sidebar-footer").boundingBox(), footerBefore, "opening updates must not shrink Goal navigation");
  assert.equal(await page.getByRole("combobox", { name: "更新通道" }).isVisible(), false);
  await page.keyboard.press("Escape");
  await trigger.click();
  await page.getByRole("button", { name: "更新并准备重启", exact: true }).waitFor();
  assert.deepEqual(calls.map((call) => call.args?.action), ["check"], "auto-check must not mutate installation");
  await page.screenshot({ path: resolve(output, "update-panel.png") });
  await page.getByRole("button", { name: "更新并准备重启", exact: true }).click();
  await page.locator(".personal-update-panel").getByRole("button", { name: "重启完成更新", exact: true }).waitFor();
  assert.deepEqual(calls.map((call) => call.args?.action), ["check", "apply"]);
  await page.reload();
  await page.getByRole("button", { name: /重启完成更新/ }).waitFor();
  assert.deepEqual(calls.map((call) => call.args?.action), ["check", "apply"], "reload must recover native progress, not repeat install");
  nativeState = { phase: "available", details: { channel: "stable", version: "0.5.5" } };
  failUpdate = true;
  await page.reload();
  await page.getByRole("button", { name: "有可用更新" }).click();
  await page.getByRole("button", { name: "更新并准备重启", exact: true }).click();
  await page.getByText("更新未完成。请检查网络后重试；启动失败可尝试修复当前版本。").waitFor();
  assert.ok(!(await page.locator("body").innerText()).includes("private diagnostic"));
  assert.equal(await page.getByRole("button", { name: "更新并准备重启", exact: true }).count(), 0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "打开 Goal 导航" }).click();
  await page.getByRole("button", { name: "更新需重试" }).waitFor({ state: "visible" });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: resolve(output, "update-mobile.png") });

  const missing = await browser.newPage();
  await missing.route("**/assets/*.js", (route) => route.abort());
  await missing.goto(`${origin}/chat/`);
  await missing.getByText("正在加载工作区… / Loading workspace…").waitFor();
  await missing.getByRole("link", { name: "重新加载 / Reload" }).waitFor();
  await missing.screenshot({ path: resolve(output, "missing-assets.png") });
  await missing.unroute("**/assets/*.js");
  await missing.getByRole("link", { name: "重新加载 / Reload" }).click();
  await missing.getByRole("button", { name: "更新 LoopX" }).waitFor();

  await page.setViewportSize({ width: 1280, height: 900 });
  nativeState = null;
  failUpdate = false;
  await page.goto(`${origin}/boot/index.html`);
  await page.getByText("恢复与更新 / Recovery & updates").click();
  await page.getByRole("button", { name: "检查更新 / Check for updates" }).click();
  await page.getByRole("button", { name: "更新并准备重启 / Install update" }).waitFor();
  await page.screenshot({ path: resolve(output, "startup-recovery.png") });
  console.log("desktop-update-browser-smoke: passed (confirmation, failure redaction, mobile, missing assets + reload, startup recovery)");
} finally {
  await browser.close();
  await new Promise((done) => server.close(done));
}
