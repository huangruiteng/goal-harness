import { createServer, type Socket } from "node:net";
import { chmod, rm } from "node:fs/promises";

import type { JsonObject } from "./effect_program.ts";
import {
  createEffectRuntimeHandlers,
  dispatchEffectRuntimeMethod,
} from "./effect_runtime_handlers.ts";
import { atomicWriteJson } from "./effect_runtime_io.ts";

const REQUEST_SCHEMA = "loopx_effect_runtime_request_v0";
const RESPONSE_SCHEMA = "loopx_effect_runtime_response_v0";
const INFO_SCHEMA = "loopx_effect_runtime_info_v0";
const MAX_REQUEST_BYTES = 2 * 1024 * 1024;
const DEFAULT_IDLE_MS = 5 * 60 * 1_000;
let shutdownRequested = false;

interface RuntimeRequest {
  schema_version: typeof REQUEST_SCHEMA;
  token: string;
  request_id: string;
  method: string;
  params: JsonObject;
}

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function parseArg(name: string): string {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) {
    throw new Error(`missing ${name}`);
  }
  return requiredString(process.argv[index + 1], name);
}

const infoPath = parseArg("--info");
const fingerprint = parseArg("--fingerprint");
const token = requiredString(process.env.LOOPX_EFFECT_RUNTIME_TOKEN, "runtime token");
const idleMs = Number(process.env.LOOPX_EFFECT_RUNTIME_IDLE_MS ?? DEFAULT_IDLE_MS);
let idleTimer: NodeJS.Timeout;
const handlers = createEffectRuntimeHandlers({
  fingerprint,
  requestShutdown: () => {
    shutdownRequested = true;
  },
});

function resetIdleTimer(server: ReturnType<typeof createServer>): void {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => server.close(), idleMs);
  idleTimer.unref();
}

function writeResponse(socket: Socket, response: JsonObject): void {
  socket.end(`${JSON.stringify(response)}\n`);
}

const server = createServer((socket) => {
  resetIdleTimer(server);
  socket.setEncoding("utf8");
  let raw = "";
  socket.on("data", (chunk: string) => {
    raw += chunk;
    if (Buffer.byteLength(raw, "utf8") > MAX_REQUEST_BYTES) {
      socket.destroy();
      return;
    }
    if (!raw.includes("\n")) return;
    socket.pause();
    void (async () => {
      let requestId = "unknown";
      try {
        const request = JSON.parse(raw.slice(0, raw.indexOf("\n"))) as RuntimeRequest;
        requestId = requiredString(request.request_id, "request_id");
        if (request.schema_version !== REQUEST_SCHEMA || request.token !== token) {
          throw new Error("Effect runtime request authentication failed");
        }
        const result = await dispatchEffectRuntimeMethod(
          handlers,
          requiredString(request.method, "method"),
          asObject(request.params),
        );
        writeResponse(socket, {
          schema_version: RESPONSE_SCHEMA,
          request_id: requestId,
          ok: true,
          result,
        });
        if (shutdownRequested) setImmediate(() => server.close());
      } catch (error) {
        writeResponse(socket, {
          schema_version: RESPONSE_SCHEMA,
          request_id: requestId,
          ok: false,
          error: {
            kind: "runtime_request_failed",
            message: error instanceof Error ? error.message : String(error),
          },
        });
      }
    })();
  });
});

server.on("close", () => {
  void rm(infoPath, { force: true }).finally(() => process.exit(0));
});

server.listen(0, "127.0.0.1", async () => {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("invalid address");
  await atomicWriteJson(infoPath, {
    schema_version: INFO_SCHEMA,
    fingerprint,
    pid: process.pid,
    host: "127.0.0.1",
    port: address.port,
    token,
  });
  await chmod(infoPath, 0o600);
  resetIdleTimer(server);
});
