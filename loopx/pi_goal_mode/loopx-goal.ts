// <!-- loopx-managed-slash-command:v1 command=/loopx surface=pi-extension -->
//
// LoopX Pi goal extension — the Pi host adapter for LoopX.
//
// Pi is a terminal coding agent whose extensions register commands, tools, and
// event handlers. This extension gives a Pi session a LoopX surface:
//
// - `/loopx` inspects the project packet, or starts a guided LoopX goal when
//   arguments are provided.
// - `loopx_goal_activate` binds the current session to a LoopX goal after
//   `loopx start-goal` wrote todos and produced a heartbeat task_body.
// - Once bound, every `agent_settled` continuation runs through
//   `loopx quota should-run --runtime-profile generic_cli`; LoopX decides
//   whether to continue (injecting the heartbeat task_body as a follow-up),
//   wait with backoff, or stop only at a validated terminal no-follow-up.
//
// The extension is self-contained: pi's extension loader aliases `typebox` and
// the `@earendil-works/*` packages, so no local node_modules are required.
// The quota/wait/store loop core lives in the sibling
// `pi-goal-loop-runtime.mjs` (installed alongside, not auto-discovered as an
// extension); it is directly executable by node:test, and session shutdown
// atomically disposes it so an in-flight quota probe can never continue the
// old session past a reload / session-replacement boundary.
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import { Type } from "typebox";
import {
  buildQuotaArgs,
  createBindingStore,
  createEphemeralSessionIdentity,
  createGoalLoop,
  sessionKey,
} from "./pi-goal-loop-runtime.mjs";

const execFile = promisify(execFileCallback);
const LOOPX_CLI_TIMEOUT_MS = 30_000;

async function runLoopxCli(args: string[], directory: string): Promise<string> {
  const { stdout } = await execFile(process.env.LOOPX_BIN || "loopx", args, {
    cwd: directory,
    timeout: LOOPX_CLI_TIMEOUT_MS,
    maxBuffer: 8 * 1024 * 1024,
  });
  return stdout;
}

async function probeLoopxQuota(binding: Record<string, unknown>): Promise<Record<string, unknown>> {
  const args = buildQuotaArgs(binding);
  const stdout = await runLoopxCli(args, String(binding.directory || ""));
  const decision: unknown = JSON.parse(stdout || "{}");
  if (!decision || typeof decision !== "object" || Array.isArray(decision)) {
    throw new Error("loopx quota should-run returned a non-object payload");
  }
  return decision as Record<string, unknown>;
}

export default function (pi: ExtensionAPI) {
  // Durable, TUI-only digest of the last inspected LoopX packet. Custom entries
  // never enter LLM context; the agent reads full state through the CLI itself.
  pi.registerEntryRenderer("loopx-packet", (entry, _options, theme) => {
    const data = (entry.data ?? {}) as { text?: string };
    const preview = String(data.text || "").split("\n").slice(0, 3).join("\n");
    return new Text(
      `${theme.fg("accent", "[loopx]")} packet ready:\n${preview || "(empty)"}`,
      0,
      0,
    );
  });

  const keyFor = (ctx: ExtensionContext) => {
    const file = ctx.sessionManager.getSessionFile();
    // Use the full path digest so two files whose first 161 bytes collide
    // never produce the same durable key.
    return file ? sessionKey(file) : ephemeral.key;
  };
  // One stable store instance per key, so the runtime's per-key commit queue
  // and compare-and-swap are shared across every event for the same session.
  const stores = new Map<string, ReturnType<typeof createBindingStore>>();

  // One loop per extension instance. Session services (store, idle probe,
  // notify) are bound per key on every event, and `session_shutdown` disposes
  // the whole instance so no old session can keep continuing.
  const loop = createGoalLoop({
    quotaProbe: probeLoopxQuota,
    sendMessage: (prompt: string) => {
      pi.sendUserMessage(prompt, { deliverAs: "followUp", triggerTurn: true });
    },
    setTimer: (callback: () => void, delayMs: number) => {
      const timer = setTimeout(callback, delayMs);
      if (typeof (timer as NodeJS.Timeout & { unref?: () => void })?.unref === "function") {
        (timer as NodeJS.Timeout & { unref: () => void }).unref();
      }
      return timer;
    },
    clearTimer: (timer: NodeJS.Timeout) => clearTimeout(timer),
  });
  // One unique, non-persisted identity per extension instance for ephemeral
  // sessions; declared here so keyFor stays stable within the run.
  const ephemeral = createEphemeralSessionIdentity();

  const bindContext = (ctx: ExtensionContext) => {
    const key = keyFor(ctx);
    const file = ctx.sessionManager.getSessionFile();
    let store = ephemeral.store;
    if (file) {
      const cached = stores.get(key);
      if (cached) {
        store = cached;
      } else {
        store = createBindingStore(ctx.cwd);
        stores.set(key, store);
      }
    }
    loop.bind(key, {
      store,
      isIdle: () => ctx.isIdle(),
      notify: (message: string, kind: string) => ctx.ui.notify(message, kind),
    });
    return { key, store };
  };

  // /loopx — inspect the project packet, or start a guided LoopX goal.
  pi.registerCommand("loopx", {
    description:
      "Inspect LoopX state, or start a concrete LoopX goal when arguments are provided.",
    handler: async (args, ctx) => {
      const trimmed = String(args || "").trim();
      const { key, store } = bindContext(ctx);
      const binding = await store.read(key).catch(() => null);
      if (
        !trimmed ||
        trimmed === "status" ||
        trimmed === "history" ||
        trimmed === "list" ||
        trimmed === "resume"
      ) {
        if (trimmed === "resume" && binding) {
          await loop.resume(key);
          return;
        }
        try {
          const stdout = await runLoopxCli(["bootstrap-command-pack", "--project", "."], ctx.cwd);
          ctx.ui.setWidget("loopx", stdout.split("\n").slice(0, 24));
          ctx.ui.notify("LoopX packet ready (widget above the editor).", "info");
          pi.appendEntry("loopx-packet", { text: stdout });
        } catch (error) {
          ctx.ui.notify(
            `LoopX inspect failed: ${(error as Error)?.message || String(error)}`,
            "error",
          );
        }
        return;
      }
      // Start a guided goal for the exact Pi host; the returned packet
      // includes ordered todos and the heartbeat task_body the agent needs.
      try {
        const stdout = await runLoopxCli(
          ["start-goal", "--guided", "--project", ".", "--goal-text", trimmed, "--host-surface", "pi"],
          ctx.cwd,
        );
        ctx.ui.setEditorText(stdout);
        ctx.ui.notify(
          "LoopX start-goal packet ready in the editor; review and send it, then the agent calls loopx_goal_activate.",
          "info",
        );
      } catch (error) {
        ctx.ui.notify(
          `LoopX start-goal failed: ${(error as Error)?.message || String(error)}`,
          "error",
        );
      }
    },
  });

  // loopx_goal_activate — bind this session to a LoopX goal and start the
  // quota-gated auto-continuation loop. Called by the agent after start-goal.
  pi.registerTool({
    name: "loopx_goal_activate",
    label: "Activate LoopX Goal",
    description:
      "Activate a LoopX-backed Pi goal after LoopX start-goal has written todos and produced a heartbeat task_body. The extension then auto-continues through LoopX quota should-run; it never self-declares closure.",
    parameters: Type.Object({
      goalId: Type.String({ description: "LoopX goal id from the start-goal packet (goal_id)." }),
      objective: Type.String({
        description: "Heartbeat task_body from the start-goal packet.",
      }),
      agentId: Type.Optional(
        Type.String({ description: "Registered agent id when present." }),
      ),
      registryPath: Type.Optional(
        Type.String({ description: "Explicit LoopX registry path when present." }),
      ),
      availableCapabilities: Type.Optional(
        Type.Array(Type.String(), { description: "Declared host capabilities when present." }),
      ),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const { key } = bindContext(ctx);
      const binding = await loop.activate(key, {
        directory: ctx.cwd,
        goalId: String(params.goalId),
        agentId: params.agentId ? String(params.agentId) : "",
        registryPath: params.registryPath ? String(params.registryPath) : "",
        availableCapabilities: Array.isArray(params.availableCapabilities)
          ? params.availableCapabilities.map(String)
          : [],
        taskBody: String(params.objective),
        autoResume: true,
        terminal: false,
        schedulerToken: "",
        unchangedPolls: 0,
        lastInjectedPrompt: "",
      });
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              version: 1,
              operation: "loopx_activate",
              ok: true,
              message: "LoopX-backed Pi goal activated.",
              goalId: binding.goalId,
            }),
          },
        ],
        details: {},
      };
    },
  });

  // When the agent settles and a goal is bound, let LoopX decide the next move.
  pi.on("agent_settled", async (_event, ctx) => {
    const { key } = bindContext(ctx);
    await loop.settle(key);
  });

  // User-driven prompts pause the auto loop; only prompts we injected for the
  // same goal keep auto-resume armed.
  pi.on("before_agent_start", async (event, ctx) => {
    const { key } = bindContext(ctx);
    await loop.userPrompt(key, String(event.prompt || ""));
  });

  // Session shutdown / session replacement: atomically dispose the whole
  // extension instance. Every timer is cancelled and an in-flight quota probe
  // returns to the runtime's disposed guard, so the old session cannot send a
  // follow-up or reschedule past this boundary.
  pi.on("session_shutdown", async (_event, _ctx) => {
    loop.dispose();
  });
}
