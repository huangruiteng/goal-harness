import assert from "node:assert/strict";

import { projectEditableCapabilityConfiguration } from "../src/data/capability-configuration.js";

const periodicReportEditor = {
  fields: [
    { key: "enabled" },
    { key: "profile_preset" },
    { key: "route_ref" },
    { key: "timezone" },
  ],
};

assert.deepEqual(
  projectEditableCapabilityConfiguration(periodicReportEditor, {
    schema_version: "periodic_report_machine_defaults_v0",
    enabled: true,
    inheritance: "live_machine_default",
    profile_preset: "weekly-progress",
    route_ref: "loopx-manager",
    timezone: "Asia/Shanghai",
  }),
  {
    enabled: true,
    profile_preset: "weekly-progress",
    route_ref: "loopx-manager",
    timezone: "Asia/Shanghai",
  },
  "machine-only envelope fields must never enter a Goal write request",
);

assert.deepEqual(
  projectEditableCapabilityConfiguration(
    { fields: [{ key: "enabled" }] },
    { enabled: true, mode: "shadow_file", status: "active" },
  ),
  { enabled: true },
  "derived Goal readback fields must remain read-only",
);

assert.deepEqual(
  projectEditableCapabilityConfiguration(
    { fields: [{ key: "enabled" }, { key: "timezone" }] },
    { enabled: true },
    { enabled: false, timezone: "UTC", schema_version: "ignored" },
  ),
  { enabled: true, timezone: "UTC" },
  "editor defaults fill absent writable fields without granting authority to hidden keys",
);

console.log("capability configuration projection smoke: ok");
