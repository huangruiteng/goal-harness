import { z } from "zod";

import {
  todoApplyResultMatchesRequest,
  todoPreviewMatchesRequest,
  type TodoApplyResult,
  type TodoPreview,
} from "./chat-model.js";

const configuredChatOrigin = String(import.meta.env?.VITE_LOOPX_CHAT_ORIGIN ?? "")
  .trim()
  .replace(/\/+$/, "");

function chatApiUrl(path: string) {
  if (!configuredChatOrigin || /^https?:\/\//.test(path)) {
    return path;
  }
  return new URL(path, `${configuredChatOrigin}/`).toString();
}

export {
  agentBackendLabel,
  answerLocalStatusQuestion,
  buildGoalStudioNodes,
  chatFailureMessage,
  completedGoalReviews,
  pendingGoalReviews,
  proposalReviewState,
  sessionInvalidatedByPayload,
  selectAvailableChatAgent,
  selectChatGoal,
  stewardPrompts,
  turnReplaySafeByPayload,
  todoNoWriteReceiptFromPayload,
  todoNoWriteReceiptLabel,
  todoApplyResultMatchesRequest,
  todoPreviewMatchesRequest,
  todoReceiptLabel,
  todoReceiptOutcomeLabel,
  todoReceiptProjected,
} from "./chat-model.js";
export type {
  AgentResponse,
  ChatCapabilities,
  ChatGoal,
  ChatStatus,
  ChatTodo,
  GoalStudioNode,
  ProposalDecisionOutcome,
  ProposalReviewState,
  StewardPrompt,
  TodoNoWriteReceipt,
  TodoPreview,
  TodoProposal,
  TodoApplyResult,
  TodoWriteReceipt,
} from "./chat-model.js";

export const chatTodoSchema = z.object({
  todo_id: z.string().nullable(),
  role: z.string().nullable(),
  status: z.string(),
  priority: z.string().nullable(),
  text: z.string(),
  action_kind: z.string().nullable(),
  task_class: z.string().nullable(),
  claimed_by: z.string().nullable(),
  evidence: z.string().nullable(),
});

export const chatGoalSchema = z.object({
  goal_id: z.string(),
  title: z.string(),
  objective: z.string(),
  status: z.string(),
  waiting_on: z.string().nullable(),
  severity: z.string().nullable(),
  gate: z.string(),
  next_action: z.string(),
  top_todo: chatTodoSchema.nullable(),
  todos: z.array(chatTodoSchema),
  evidence: z.array(z.string()),
  quota: z.object({
    state: z.string().nullable(),
    spent_slots: z.number().nullable(),
    allowed_slots: z.number().nullable(),
    reason: z.string().nullable(),
  }),
});

export const chatStatusSchema = z.object({
  ok: z.boolean(),
  schema_version: z.literal("loopx_chat_status_v0"),
  selected_goal_id: z.string().nullable(),
  goal_count: z.number(),
  goals: z.array(chatGoalSchema),
});

export const chatCapabilitiesSchema = z.object({
  ok: z.literal(true),
  schema_version: z.enum(["loopx_chat_capabilities_v0", "loopx_chat_capabilities_v1"]),
  agent_backend: z.string(),
  sandbox: z.string(),
  approval_policy: z.string(),
  todo_write: z.string(),
  goal_id: z.string().nullable(),
  streaming: z.boolean().optional(),
  resume: z.boolean().optional(),
  interrupt: z.boolean().optional(),
  typed_actions: z.boolean().optional(),
  action_kinds: z.array(z.string()).optional(),
  adapters: z.array(z.object({
    agent_id: z.string(),
    display_name: z.string(),
    adapter_kind: z.string(),
    available: z.boolean(),
    streaming: z.boolean(),
    resume: z.boolean(),
    interrupt: z.boolean(),
    location: z.string().optional(),
    source: z.string().optional(),
    tool_calls: z.boolean().optional(),
    trust_scope: z.string().optional(),
  })).optional(),
  lark_cli: z.object({
    available: z.boolean(),
    source: z.string(),
    version: z.string().nullable(),
    error_code: z.string().nullable(),
  }).optional(),
});

export const todoProposalSchema = z.object({
  kind: z.literal("todo"),
  text: z.string(),
  priority: z.enum(["P0", "P1", "P2"]),
  rationale: z.string(),
});

export const protectedActionProposalSchema = z.object({
  operation: z.enum(["merge", "release", "deploy", "delete", "payment"]),
  target: z.string().min(1).max(160),
  summary: z.string().max(300),
});

export type ProtectedActionProposal = z.infer<typeof protectedActionProposalSchema>;

export const agentResponseSchema = z.object({
  schema_version: z.literal("loopx_chat_agent_response_v0"),
  message: z.string(),
  proposals: z.array(todoProposalSchema),
  protected_action: protectedActionProposalSchema.nullable().optional().default(null),
  gate: z
    .object({
      kind: z.string(),
      summary: z.string(),
      next_action: z.string(),
    })
    .nullable(),
});

export const chatSessionCloseSchema = z.object({
  closed: z.literal(true),
  ok: z.literal(true),
  session_id: z.string().min(1),
});

export const todoPreviewSchema = z.object({
  dry_run: z.literal(true),
  ok: z.literal(true),
  preview_id: z.string().min(1),
  todo: z.object({
    goal_id: z.string().min(1),
    text: z.string(),
    todo_id: z.string().optional(),
  }),
});

export const todoWriteReceiptSchema = z.object({
  schema_version: z.literal("loopx_chat_todo_receipt_v0"),
  receipt_id: z.string().min(1),
  preview_id: z.string().min(1),
  goal_id: z.string().min(1),
  todo_id: z.string().min(1),
  status: z.literal("applied"),
  outcome: z.enum(["todo_added", "todo_already_exists"]),
  already_exists: z.boolean(),
  preview_revision: z.string().nullable(),
});

export const todoApplyResultSchema = z.object({
  applied: z.literal(true),
  ok: z.literal(true),
  receipt: todoWriteReceiptSchema,
  todo: z.object({
    text: z.string(),
    todo_id: z.string(),
  }),
});

export const storedDecisionHistoryItemSchema = z
  .object({
    id: z.string().min(1),
    outcome: z.enum(["approved", "rejected", "cancelled"]),
    projectionVerified: z.boolean().nullable(),
    proposal: todoProposalSchema,
    receipt: todoWriteReceiptSchema.nullable(),
  })
  .superRefine((item, context) => {
    if (item.outcome === "approved" && !item.receipt) {
      context.addIssue({
        code: "custom",
        message: "approved decision history requires a Todo receipt",
        path: ["receipt"],
      });
    }
    if (item.outcome !== "approved" && item.receipt) {
      context.addIssue({
        code: "custom",
        message: "zero-write decision history must not include a Todo receipt",
        path: ["receipt"],
      });
    }
  });

export const storedDecisionHistorySchema = z.object({
  schema_version: z.literal("loopx_chat_decision_history_v0"),
  goal_id: z.string().min(1),
  decisions: z.array(storedDecisionHistoryItemSchema).max(24),
});

export type StoredDecisionHistoryItem = z.infer<typeof storedDecisionHistoryItemSchema>;

export class ChatApiError extends Error {
  payload: Record<string, unknown>;

  constructor(message: string, payload: Record<string, unknown>) {
    super(message);
    this.payload = payload;
  }
}

export const typedActionKindSchema = z.enum([
  "goal.create",
  "goal.update",
  "goal.lifecycle",
  "todo.create",
  "todo.update",
  "agent.bind",
  "heartbeat.bind",
  "monitor.create",
  "monitor.update",
  "gate.resolve",
  "run.correct",
]);

export const typedActionProposalSchema = z.object({
  schema_version: z.literal("loopx_chat_action_proposal_v1"),
  proposal_id: z.string().min(1),
  action_kind: typedActionKindSchema,
  summary: z.string().min(1),
  normalized_parameters: z.record(z.string(), z.unknown()),
  context: z.record(z.string(), z.unknown()),
  expected_state_fingerprint: z.string().min(1),
  permission_classification: z.string().min(1),
  validation_evidence: z.array(z.unknown()),
  available_transitions: z.array(z.enum(["apply", "cancel", "regenerate", "reject", "defer"])),
  status: z.enum(["preview_ready", "applying", "gated", "failed", "rejected", "deferred", "cancelled", "stale", "applied"]),
  receipt: z.record(z.string(), z.unknown()).nullable(),
  stale: z.record(z.string(), z.unknown()).nullable(),
  gate: z.record(z.string(), z.unknown()).nullable().optional(),
  error: z.record(z.string(), z.unknown()).nullable().optional(),
  checkpoint: z.record(z.string(), z.unknown()).nullable().optional(),
  regenerated_from: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type TypedActionKind = z.infer<typeof typedActionKindSchema>;
export type TypedActionProposal = z.infer<typeof typedActionProposalSchema>;

export type TypedActionPreviewRequest = {
  actionKind: TypedActionKind;
  context: Record<string, unknown>;
  idempotencyKey: string;
  normalizedParameters: Record<string, unknown>;
  summary: string;
};

const typedActionEnvelopeSchema = z.object({
  ok: z.literal(true),
  proposal: typedActionProposalSchema,
});

export async function previewTypedAction(request: TypedActionPreviewRequest) {
  const payload = await requestJson<unknown>("/api/actions/preview", {
    method: "POST",
    body: JSON.stringify({
      action_kind: request.actionKind,
      context: request.context,
      idempotency_key: request.idempotencyKey,
      normalized_parameters: request.normalizedParameters,
      summary: request.summary,
    }),
  });
  return typedActionEnvelopeSchema.parse(payload).proposal;
}

export async function loadTypedAction(proposalId: string) {
  return typedActionEnvelopeSchema.parse(
    await requestJson<unknown>(`/api/actions/${encodeURIComponent(proposalId)}`),
  ).proposal;
}

const typedActionListEnvelopeSchema = z.object({
  ok: z.literal(true),
  schema_version: z.literal("loopx_chat_action_list_v1"),
  proposals: z.array(typedActionProposalSchema),
});

export async function listTypedActions(filters: { contextKind?: string; goalId?: string } = {}) {
  const query = new URLSearchParams();
  if (filters.contextKind) query.set("context_kind", filters.contextKind);
  if (filters.goalId) query.set("goal_id", filters.goalId);
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return typedActionListEnvelopeSchema.parse(
    await requestJson<unknown>(`/api/actions${suffix}`),
  ).proposals;
}

export async function applyTypedAction(proposalId: string) {
  const payload = await requestJson<unknown>(
    `/api/actions/${encodeURIComponent(proposalId)}/apply`,
    { method: "POST", body: "{}" },
  );
  return z.object({
    ok: z.literal(true),
    proposal: typedActionProposalSchema,
    turn: z.record(z.string(), z.unknown()).nullable().optional(),
  }).parse(payload);
}

export async function cancelTypedAction(proposalId: string) {
  return typedActionEnvelopeSchema.parse(
    await requestJson<unknown>(`/api/actions/${encodeURIComponent(proposalId)}/cancel`, {
      method: "POST",
      body: "{}",
    }),
  ).proposal;
}

export async function transitionTypedAction(
  proposalId: string,
  transition: "regenerate" | "reject" | "defer",
) {
  return typedActionEnvelopeSchema.parse(
    await requestJson<unknown>(`/api/actions/${encodeURIComponent(proposalId)}/${transition}`, {
      method: "POST",
      body: "{}",
    }),
  ).proposal;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(chatApiUrl(url), {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    const proposal = payload.proposal && typeof payload.proposal === "object"
      ? payload.proposal as Record<string, unknown>
      : null;
    const staleMessage = proposal?.status === "stale"
      ? "来源状态已变化，请重新生成预览。"
      : null;
    throw new ChatApiError(staleMessage ?? String(payload.error || `HTTP ${response.status}`), payload);
  }
  return payload as T;
}

export async function fetchChatStatus() {
  return chatStatusSchema.parse(await requestJson<unknown>("/status.json"));
}

export async function fetchChatCapabilities() {
  return chatCapabilitiesSchema.parse(await requestJson<unknown>("/api/chat/capabilities"));
}

export async function recordProjectionExchange(options: {
  answer: string;
  contextKind: "goal" | "manager";
  goalId?: string;
  question: string;
}) {
  return requestJson<{ ok: true; schema_version: "loopx_chat_projection_exchange_v1"; session_id: string }>(
    "/api/chat/projection-messages",
    {
      method: "POST",
      body: JSON.stringify({
        answer: options.answer,
        context_kind: options.contextKind,
        goal_id: options.goalId,
        question: options.question,
      }),
    },
  );
}

export async function createChatSession(
  goalId: string,
  agentId = "codex",
  mode: "resume_latest" | "new" = "resume_latest",
  contextKind: "goal" | "manager" = "goal",
) {
  return requestJson<{
    agent_id: string;
    goal_id: string;
    ok: true;
    resumed: boolean;
    session_id: string;
  }>("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ goal_id: goalId, agent_id: agentId, mode, context_kind: contextKind }),
  });
}

export type ChatStreamEvent = {
  event_id: string;
  sequence: number;
  kind: string;
  created_at: string;
  payload: Record<string, unknown>;
};

export type ChatSessionSummary = {
  session_id: string;
  goal_id: string;
  agent_id: string;
  adapter_kind: string;
  channel_id?: string;
  status: string;
  active_turn_id: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  resumable: boolean;
};

export type ChatVisibleMessage = {
  attachments?: ChatImageAttachment[];
  message_id: string;
  turn_id: string | null;
  role: string;
  text: string;
  created_at: string;
};

export type ChatImageAttachment = {
  data_url: string;
  id: string;
  mime_type: string;
  name: string;
  size: number;
};

export type ChatImageAttachmentInput = {
  dataUrl: string;
  id: string;
  mimeType: string;
  name: string;
  size: number;
};

export type ChatSessionSnapshot = {
  ok: true;
  schema_version: "loopx_chat_store_v1";
  session: ChatSessionSummary;
  messages: ChatVisibleMessage[];
  active_turn: Record<string, unknown> | null;
};

export async function fetchChatSession(sessionId: string) {
  return requestJson<ChatSessionSnapshot>(`/api/chat/sessions/${sessionId}`);
}

export async function fetchChatSessions(options: {
  agentId?: string;
  channelId?: string;
  goalId?: string;
}) {
  const query = new URLSearchParams();
  if (options.agentId) query.set("agent_id", options.agentId);
  if (options.channelId) query.set("channel_id", options.channelId);
  if (options.goalId) query.set("goal_id", options.goalId);
  return requestJson<{
    ok: true;
    schema_version: "loopx_chat_session_list_v1";
    sessions: ChatSessionSummary[];
  }>(`/api/chat/sessions?${query.toString()}`);
}

export function mergeChatSessionMessages(snapshots: ChatSessionSnapshot[]) {
  const messages = new Map<string, ChatVisibleMessage>();
  for (const snapshot of snapshots) {
    for (const message of snapshot.messages) {
      messages.set(message.message_id, message);
    }
  }
  return [...messages.values()].sort((left, right) =>
    left.created_at.localeCompare(right.created_at)
      || left.message_id.localeCompare(right.message_id)
  );
}

export async function fetchChatHistory(options: {
  agentId: string;
  channelId: string;
  goalId?: string;
}) {
  const listed = await fetchChatSessions(options);
  const snapshots = await Promise.all(
    listed.sessions.map((session) => fetchChatSession(session.session_id)),
  );
  return {
    messages: mergeChatSessionMessages(snapshots),
    sessions: listed.sessions,
    snapshots,
  };
}

export async function acceptChatTurn(
  sessionId: string,
  message: string,
  clientTurnId: string,
  attachments: ChatImageAttachmentInput[] = [],
) {
  return requestJson<{
    ok: true;
    session_id: string;
    turn_id: string;
    created: boolean;
    status: string;
    events_url: string;
  }>(`/api/chat/sessions/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({
      message,
      client_turn_id: clientTurnId,
      ...(attachments.length ? { attachments: attachments.map((attachment) => ({
        data_url: attachment.dataUrl,
        id: attachment.id,
        mime_type: attachment.mimeType,
        name: attachment.name,
        size: attachment.size,
      })) } : {}),
    }),
  });
}

function parseSseBlock(block: string): ChatStreamEvent | null {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Partial<ChatStreamEvent>;
    if (!parsed.kind || !parsed.payload || typeof parsed.payload !== "object") return null;
    return {
      event_id: String(parsed.event_id ?? ""),
      sequence: Number(parsed.sequence ?? 0),
      kind: String(parsed.kind),
      created_at: String(parsed.created_at ?? ""),
      payload: parsed.payload as Record<string, unknown>,
    };
  } catch {
    return null;
  }
}

export async function streamChatTurn(
  eventsUrl: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
) {
  let cursor = "";
  let attempts = 0;
  let terminal = false;
  while (!terminal && attempts < 4) {
    const origin = typeof window === "undefined" ? "http://127.0.0.1" : window.location.origin;
    const url = new URL(chatApiUrl(eventsUrl), origin);
    if (cursor) url.searchParams.set("after", cursor);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "text/event-stream" },
        signal,
      });
      if (!response.ok || !response.body) {
        throw new ChatApiError(`SSE HTTP ${response.status}`, { status: response.status });
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const event = parseSseBlock(block);
          if (event) {
            if (event.event_id) cursor = event.event_id;
            onEvent(event);
            terminal = ["turn.completed", "turn.interrupted", "turn.failed"].includes(event.kind);
          }
          boundary = buffer.indexOf("\n\n");
        }
        if (done || terminal) break;
      }
      attempts = terminal ? attempts : attempts + 1;
    } catch (error) {
      if (signal?.aborted) throw error;
      attempts += 1;
      if (attempts >= 4) throw error;
      await new Promise((resolve) => globalThis.setTimeout(resolve, 250 * 2 ** (attempts - 1)));
    }
  }
  if (!terminal) {
    throw new ChatApiError("Agent 事件流连接已断开。", { reconnect_attempts: attempts });
  }
}

export async function interruptChatTurn(sessionId: string, turnId: string) {
  return requestJson<{ ok: true; session_id: string; turn_id: string; status: string }>(
    `/api/chat/sessions/${sessionId}/turns/${turnId}/interrupt`,
    { method: "POST", body: "{}" },
  );
}

export async function sendChatTurnStreaming(
  sessionId: string,
  message: string,
  options: {
    attachments?: ChatImageAttachmentInput[];
    clientTurnId?: string;
    onDelta?: (text: string) => void;
    onActivity?: (label: string) => void;
    onPhase?: (phase: string, turnId: string) => void;
    signal?: AbortSignal;
  } = {},
) {
  const accepted = await acceptChatTurn(
    sessionId,
    message,
    options.clientTurnId ?? crypto.randomUUID(),
    options.attachments,
  );
  options.onPhase?.("turn.accepted", accepted.turn_id);
  return receiveChatTurnStreaming(
    sessionId,
    accepted.turn_id,
    accepted.events_url,
    options,
  );
}

async function receiveChatTurnStreaming(
  sessionId: string,
  turnId: string,
  eventsUrl: string,
  options: {
    onDelta?: (text: string) => void;
    onActivity?: (label: string) => void;
    onPhase?: (phase: string, turnId: string) => void;
    signal?: AbortSignal;
  } = {},
) {
  let finalResponse: unknown = null;
  const outcome: {
    failure: Record<string, unknown> | null;
    interrupted: Record<string, unknown> | null;
  } = { failure: null, interrupted: null };
  try {
    await streamChatTurn(
      eventsUrl,
      (event) => {
        options.onPhase?.(event.kind, turnId);
        if (event.kind === "answer.delta" || event.kind === "assistant.delta") {
          options.onDelta?.(String(event.payload.text ?? ""));
        }
        if (event.kind === "agent.phase") {
          options.onActivity?.(String(event.payload.label ?? "Agent 正在处理"));
        }
        if (event.kind === "turn.completed") {
          finalResponse = event.payload.response;
        }
        if (event.kind === "turn.failed") {
          outcome.failure = event.payload;
        }
        if (event.kind === "turn.interrupted") {
          outcome.interrupted = event.payload;
        }
      },
      options.signal,
    );
  } catch (error) {
    if (error instanceof ChatApiError && !options.signal?.aborted) {
      throw new ChatApiError(error.message, {
        ...error.payload,
        events_url: eventsUrl,
        reconnectable: true,
        session_id: sessionId,
        turn_id: turnId,
      });
    }
    throw error;
  }
  if (outcome.failure) {
    throw new ChatApiError(
      String(outcome.failure.message || "Agent 回合失败。"),
      outcome.failure,
    );
  }
  if (outcome.interrupted) {
    throw new ChatApiError("Agent 回合已中断。", {
      ...outcome.interrupted,
      error_code: "turn_interrupted",
      session_id: sessionId,
      turn_id: turnId,
    });
  }
  return {
    response: agentResponseSchema.parse(finalResponse),
    sessionId,
    turnId,
  };
}

export async function resumeChatTurnStreaming(
  sessionId: string,
  turnId: string,
  options: {
    onDelta?: (text: string) => void;
    onActivity?: (label: string) => void;
    onPhase?: (phase: string, turnId: string) => void;
    signal?: AbortSignal;
  } = {},
) {
  return receiveChatTurnStreaming(
    sessionId,
    turnId,
    `/api/chat/sessions/${sessionId}/turns/${turnId}/events`,
    options,
  );
}

export async function sendChatTurn(sessionId: string, message: string) {
  const payload = await requestJson<{ response: unknown }>(`/api/chat/sessions/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
  return agentResponseSchema.parse(payload.response);
}

export async function closeChatSession(sessionId: string) {
  const result = chatSessionCloseSchema.parse(
    await requestJson<unknown>(`/api/chat/sessions/${sessionId}`, {
      keepalive: true,
      method: "DELETE",
    }),
  );
  if (result.session_id !== sessionId) {
    throw new ChatApiError("Agent 会话关闭回执与本次请求不一致。", {
      session_id: result.session_id,
    });
  }
  return result;
}

export async function resumeChatSession(sessionId: string) {
  return requestJson<{ ok: true; schema_version: "loopx_chat_session_resume_v1"; session: ChatSessionSummary }>(
    `/api/chat/sessions/${sessionId}/resume`,
    { method: "POST", body: "{}" },
  );
}

export async function previewTodo(goalId: string, text: string) {
  const preview = todoPreviewSchema.parse(
    await requestJson<unknown>("/api/chat/todo/dry-run", {
      method: "POST",
      body: JSON.stringify({ goal_id: goalId, text }),
    }),
  );
  if (!todoPreviewMatchesRequest(preview, { goalId, text })) {
    throw new ChatApiError("Todo 写入预览与本次请求不一致，已停止进入批准状态。", {
      preview,
    });
  }
  return preview;
}

export async function applyTodo(goalId: string, text: string, previewId: string) {
  const result = todoApplyResultSchema.parse(
    await requestJson<TodoApplyResult>("/api/chat/todo/apply", {
      method: "POST",
      body: JSON.stringify({ goal_id: goalId, text, preview_id: previewId }),
    }),
  );
  if (!todoApplyResultMatchesRequest(result, { goalId, previewId, text })) {
    throw new ChatApiError("Todo 写入回执与本次批准不一致，界面已停止更新。", {
      receipt: result.receipt,
      todo: result.todo,
    });
  }
  return result;
}

export function parseCompletedDecisionHistory(raw: string | null, goalId: string) {
  if (!raw) return [];
  try {
    const parsed = storedDecisionHistorySchema.safeParse(JSON.parse(raw));
    if (!parsed.success || parsed.data.goal_id !== goalId) return [];
    return parsed.data.decisions;
  } catch {
    return [];
  }
}

export function serializeCompletedDecisionHistory(
  goalId: string,
  decisions: StoredDecisionHistoryItem[],
) {
  return JSON.stringify(
    storedDecisionHistorySchema.parse({
      schema_version: "loopx_chat_decision_history_v0",
      goal_id: goalId,
      decisions: decisions.slice(0, 24),
    }),
  );
}

export type GoalChannelTarget = {
  enabled: boolean;
  provider: string;
  target_name: string;
};

const goalChannelTargetsSchema = z.object({
  ok: z.literal(true),
  targets: z.array(
    z.object({
      enabled: z.boolean(),
      provider: z.string(),
      target_name: z.string(),
    }),
  ),
});

export async function fetchGoalChannelTargets() {
  return goalChannelTargetsSchema.parse(
    await requestJson<unknown>("/api/chat/goal-channel/targets"),
  ).targets;
}

const goalChannelOperationSchema = z.object({
  ok: z.boolean(),
  blocker: z.string().optional(),
  public_summary: z.string().optional(),
  status: z.string().optional(),
});

export type GoalChannelOperation = z.infer<typeof goalChannelOperationSchema>;

export async function setupGoalChannel(options: { execute: boolean; goalId: string; target: string }) {
  return goalChannelOperationSchema.parse(
    await requestJson<unknown>("/api/chat/goal-channel/setup", {
      method: "POST",
      body: JSON.stringify({
        execute: options.execute,
        goal_id: options.goalId,
        target: options.target,
      }),
    }),
  );
}

export async function configureGoalChannelAutoNotify(options: { autoNotify: boolean; goalId: string }) {
  return goalChannelOperationSchema.parse(
    await requestJson<unknown>("/api/chat/goal-channel/configure", {
      method: "POST",
      body: JSON.stringify({
        auto_notify_human_gates: options.autoNotify,
        goal_id: options.goalId,
      }),
    }),
  );
}

export type GoalRepositoryContext = {
  branch: string;
  identity: string;
  label: string;
  read_only: true;
};

const goalContextsSchema = z.object({
  ok: z.literal(true),
  goals: z.array(z.object({
    goal_id: z.string(),
    repository: z.object({
      branch: z.string(),
      identity: z.string(),
      label: z.string(),
      read_only: z.literal(true),
    }),
  })),
});

export async function fetchGoalContexts() {
  return goalContextsSchema.parse(
    await requestJson<unknown>("/api/chat/goals/contexts"),
  ).goals;
}

export type LarkApp = {
  active: boolean;
  app_ref: string;
  brand: string;
  health_error_code: string | null;
  label: string;
  ready: boolean;
  reply_ready: boolean;
};

const larkAppsSchema = z.object({
  ok: z.literal(true),
  apps: z.array(z.object({
    active: z.boolean(),
    app_ref: z.string(),
    brand: z.string(),
    health_error_code: z.string().nullable().default(null),
    label: z.string(),
    ready: z.boolean(),
    reply_ready: z.boolean().default(false),
  })),
});

export async function fetchLarkApps() {
  return larkAppsSchema.parse(
    await requestJson<unknown>("/api/chat/lark/apps"),
  ).apps;
}

export type LarkAppSetup = {
  app_ref: string;
  error: string | null;
  setup_id: string;
  status: "starting" | "waiting_for_feishu" | "ready" | "failed" | "cancelled";
  verification_url: string | null;
};

const larkAppSetupSchema = z.object({
  ok: z.literal(true),
  app_ref: z.string(),
  error: z.string().nullable(),
  setup_id: z.string(),
  status: z.enum(["starting", "waiting_for_feishu", "ready", "failed", "cancelled"]),
  verification_url: z.string().url().nullable(),
});

export async function startLarkAppSetup(options: { appRef: string; brand: "feishu" | "lark" }) {
  return larkAppSetupSchema.parse(
    await requestJson<unknown>("/api/chat/lark/app-setups", {
      method: "POST",
      body: JSON.stringify({ app_ref: options.appRef, brand: options.brand }),
    }),
  );
}

export async function fetchLarkAppSetup(setupId: string) {
  return larkAppSetupSchema.parse(
    await requestJson<unknown>(`/api/chat/lark/app-setups/${encodeURIComponent(setupId)}`),
  );
}

export async function cancelLarkAppSetup(setupId: string) {
  return larkAppSetupSchema.parse(
    await requestJson<unknown>(`/api/chat/lark/app-setups/${encodeURIComponent(setupId)}`, {
      method: "DELETE",
    }),
  );
}

export type LarkGroupChat = { chat_id: string; chat_name: string };
export type LarkCaptureScope = "addressed_only" | "configured_chat_all";
export type LarkIngressMode = "live_steering" | "session_queue" | "async_inbox" | "direct_session";
export type LarkReplyMode = "topic_reply";
const larkTopicEventRejectionReasons = [
  "invalid_event",
  "binding_unavailable",
  "chat_mismatch",
  "topic_mismatch",
  "route_ambiguous",
  "self_message",
  "invalid_routing_state",
  "not_addressed",
] as const;
export type LarkTopicEventRejectionReason = typeof larkTopicEventRejectionReasons[number];
export type LarkPermissionGuidance = {
  action: "enable_application_scopes_and_publish";
  api_document_url: string;
  capability: "group_history_pagination";
  identity: "bot";
  required_scopes: ["im:message.group_msg", "im:message.group_msg.include_bot:read"];
  schema_version: "lark_bot_group_history_permission_guidance_v0";
};

const larkGroupChatsSchema = z.object({
  ok: z.literal(true),
  chats: z.array(z.object({ chat_id: z.string(), chat_name: z.string() })),
});

export async function fetchLarkGroupChats(appRef: string, query?: string) {
  const params = new URLSearchParams({ app_ref: appRef });
  if (query) params.set("query", query);
  return larkGroupChatsSchema.parse(
    await requestJson<unknown>(`/api/chat/lark/chats?${params.toString()}`),
  ).chats;
}

export type LarkGoalConnection = {
  agent_id: string | null;
  app_label: string;
  app_ref: string;
  capture_scope: LarkCaptureScope;
  chat_name: string;
  enabled: boolean;
  goal_id: string;
  goal_title: string;
  health_error_code: string | null;
  history_permission_guidance: LarkPermissionGuidance | null;
  incoming_mode: "mentions" | "all";
  ingress_mode: LarkIngressMode;
  event_count: number;
  last_event_reason: LarkTopicEventRejectionReason | null;
  last_event_status: string | null;
  listener_error_code: string | null;
  listener_status: "starting" | "listening" | "retrying" | "stopped" | null;
  replied_count: number;
  reply_ready: boolean;
  reply_mode: LarkReplyMode;
  session_bound: boolean;
  target_ref: string;
  topic_name: string;
  topic_setup_required: boolean;
};

const larkConnectionsSchema = z.object({
  ok: z.literal(true),
  connections: z.array(z.object({
    agent_id: z.string().nullable().default(null),
    app_label: z.string(),
    app_ref: z.string(),
    capture_scope: z.enum(["addressed_only", "configured_chat_all"]).default("addressed_only"),
    chat_name: z.string(),
    enabled: z.boolean(),
    goal_id: z.string(),
    goal_title: z.string(),
    health_error_code: z.string().nullable().default(null),
    history_permission_guidance: z.object({
      action: z.literal("enable_application_scopes_and_publish"),
      api_document_url: z.string().url(),
      capability: z.literal("group_history_pagination"),
      identity: z.literal("bot"),
      required_scopes: z.tuple([
        z.literal("im:message.group_msg"),
        z.literal("im:message.group_msg.include_bot:read"),
      ]),
      schema_version: z.literal("lark_bot_group_history_permission_guidance_v0"),
    }).nullable().default(null),
    incoming_mode: z.enum(["mentions", "all"]),
    ingress_mode: z.enum(["live_steering", "session_queue", "async_inbox", "direct_session"]).default("async_inbox"),
    event_count: z.number().int().nonnegative().default(0),
    last_event_reason: z.enum(larkTopicEventRejectionReasons).nullable().default(null).catch(null),
    last_event_status: z.string().nullable().default(null),
    listener_error_code: z.string().nullable().default(null),
    listener_status: z.enum(["starting", "listening", "retrying", "stopped"]).nullable().default(null),
    replied_count: z.number().int().nonnegative().default(0),
    reply_ready: z.boolean().default(false),
    reply_mode: z.literal("topic_reply"),
    session_bound: z.boolean().default(false),
    target_ref: z.string(),
    topic_name: z.string(),
    topic_setup_required: z.boolean(),
  })),
});

export async function fetchLarkConnections() {
  return larkConnectionsSchema.parse(
    await requestJson<unknown>("/api/chat/lark/connections"),
  ).connections;
}

export async function connectLarkGoalTopic(options: {
  agentId?: string;
  appRef: string;
  captureScope: LarkCaptureScope;
  chatId: string;
  chatName: string;
  execute: boolean;
  goalId: string;
  incomingMode: "mentions" | "all";
  ingressMode: LarkIngressMode;
  replyMode: LarkReplyMode;
}) {
  return goalChannelOperationSchema.parse(
    await requestJson<unknown>("/api/chat/lark/connections", {
      method: "POST",
      body: JSON.stringify({
        ...(options.agentId ? { agent_id: options.agentId } : {}),
        app_ref: options.appRef,
        capture_scope: options.captureScope,
        chat_id: options.chatId,
        chat_name: options.chatName,
        execute: options.execute,
        goal_id: options.goalId,
        incoming_mode: options.incomingMode,
        ingress_mode: options.ingressMode,
        reply_mode: options.replyMode,
      }),
    }),
  );
}

export async function disconnectLarkGoalTopic(goalId: string) {
  return goalChannelOperationSchema.parse(
    await requestJson<unknown>(`/api/chat/lark/connections?goal_id=${encodeURIComponent(goalId)}`, {
      method: "DELETE",
    }),
  );
}
