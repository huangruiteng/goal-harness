import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

function runCli(...args) {
  return spawnSync(process.execPath, ["src/cli.js", ...args], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
}

function parseJsonLine(stream) {
  const line = stream.trim();
  assert.notEqual(line, "", "expected one non-empty JSON line");
  return JSON.parse(line);
}

test("status emits JSON on stdout with exit code 0", () => {
  const result = runCli("status");
  assert.equal(result.status, 0);
  assert.equal(result.stderr.trim(), "");

  const record = parseJsonLine(result.stdout);
  assert.equal(record.context.command, "status");
  assert.equal(record.context.logLevel, 30);
  assert.equal(record.message, "completed");
});

test("no argument behaves like status", () => {
  const result = runCli();
  assert.equal(result.status, 0);
  assert.equal(parseJsonLine(result.stdout).context.command, "status");
});

test("fail emits JSON on stderr with exit code 1", () => {
  const result = runCli("fail");
  assert.equal(result.status, 1);
  assert.equal(result.stdout.trim(), "");

  const record = parseJsonLine(result.stderr);
  assert.equal(record.context.command, "fail");
  assert.equal(record.context.logLevel, 50);
  assert.equal(record.message, "failed");
});
