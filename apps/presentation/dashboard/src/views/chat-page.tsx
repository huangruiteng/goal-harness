import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  FileCheck2,
  Flag,
  Gauge,
  Inbox,
  Layers3,
  Loader2,
  LockKeyhole,
  MessageSquareText,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  UserRound,
  X,
} from "lucide-react";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  ChatApiError,
  agentBackendLabel,
  answerLocalStatusQuestion,
  applyTodo,
  buildGoalStudioNodes,
  chatFailureMessage,
  completedGoalReviews,
  createChatSession,
  fetchChatSession,
  fetchChatCapabilities,
  fetchChatStatus,
  pendingGoalReviews,
  parseCompletedDecisionHistory,
  previewTodo,
  proposalReviewState,
  resumeChatTurnStreaming,
  sessionInvalidatedByPayload,
  selectChatGoal,
  interruptChatTurn,
  sendChatTurnStreaming,
  serializeCompletedDecisionHistory,
  stewardPrompts,
  todoNoWriteReceiptFromPayload,
  todoNoWriteReceiptLabel,
  todoReceiptLabel,
  todoReceiptOutcomeLabel,
  todoReceiptProjected,
  type ChatCapabilities,
  type ChatStatus,
  type ChatTodo,
  type ProposalDecisionOutcome,
  type StoredDecisionHistoryItem,
  type TodoNoWriteReceipt,
  type TodoPreview,
  type TodoProposal,
  type TodoWriteReceipt,
} from "../data/chat";
import { cn } from "../lib/utils";

type ChatMessage = {
  id: string;
  reconnect?: boolean;
  role: "agent" | "user";
  source?: "agent" | "error" | "local";
  text: string;
};

type AgentPhase = "idle" | "starting" | "resuming" | "thinking" | "streaming" | "interrupting";

const agentPhaseLabel: Record<AgentPhase, string> = {
  idle: "Codex 会话就绪",
  starting: "正在连接 Codex",
  resuming: "正在恢复原会话",
  thinking: "Codex 正在分析",
  streaming: "Codex 正在回复",
  interrupting: "正在中断",
};

type InboxView = "pending" | "completed";

type DecisionItem = {
  busy: boolean;
  error: string;
  id: string;
  noWriteReceipt: TodoNoWriteReceipt | null;
  outcome: ProposalDecisionOutcome;
  preview: TodoPreview | null;
  projectionVerified: boolean | null;
  proposal: TodoProposal;
  receipt: TodoWriteReceipt | null;
};

type HostGate = {
  kind: string;
  summary: string;
  next_action: string;
};

const nodeTone = {
  violet: "border-violet-200 bg-violet-50/75 text-violet-950",
  blue: "border-sky-200 bg-sky-50/75 text-sky-950",
  amber: "border-amber-200 bg-amber-50/75 text-amber-950",
  mint: "border-emerald-200 bg-emerald-50/75 text-emerald-950",
  slate: "border-slate-200 bg-slate-50/80 text-slate-950",
};

const nodeDotTone = {
  violet: "bg-violet-500",
  blue: "bg-sky-500",
  amber: "bg-amber-500",
  mint: "bg-emerald-500",
  slate: "bg-slate-500",
};

function randomId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function decisionHistoryStorageKey(goalId: string) {
  return `loopx-chat:completed-decisions:${goalId}`;
}

function restoreDecisionHistoryItem(item: StoredDecisionHistoryItem): DecisionItem {
  return {
    ...item,
    busy: false,
    error: "",
    noWriteReceipt: null,
    preview: null,
  };
}

function completedDecisionHistory(decisions: DecisionItem[]) {
  return decisions.flatMap((decision): StoredDecisionHistoryItem[] => {
    if (decision.outcome === "pending") return [];
    if (decision.outcome === "approved" && !decision.receipt) return [];
    return [
      {
        id: decision.id,
        outcome: decision.outcome,
        projectionVerified: decision.projectionVerified,
        proposal: decision.proposal,
        receipt: decision.outcome === "approved" ? decision.receipt : null,
      },
    ];
  });
}

function gateFromError(error: unknown): HostGate | null {
  if (!(error instanceof ChatApiError)) {
    return null;
  }
  const gate = error.payload.gate;
  if (!gate || typeof gate !== "object") {
    return null;
  }
  const record = gate as Record<string, unknown>;
  return {
    kind: String(record.kind || "host_tool_gate"),
    summary: String(record.summary || error.message),
    next_action: String(record.next_action || "Resolve the host gate, then retry."),
  };
}

function quotaLabel(status: string | null) {
  if (!status) return "Quota unknown";
  if (status === "eligible") return "Ready for a bounded turn";
  if (status === "operator_gate") return "Waiting for review";
  return status.replaceAll("_", " ");
}

function GoalMap({ status, preferredGoalId }: { status: ChatStatus | null; preferredGoalId: string }) {
  const goal = selectChatGoal(status, preferredGoalId);
  const nodes = useMemo(() => (goal ? buildGoalStudioNodes(goal) : []), [goal]);

  if (!goal) {
    return (
      <div className="grid min-h-72 place-items-center rounded-2xl border border-dashed border-slate-200 bg-white/70 p-8 text-center">
        <div>
          <Loader2 className="mx-auto mb-3 size-5 animate-spin text-slate-400" />
          <p className="text-sm font-medium text-slate-700">正在读取 Goal 视图</p>
          <p className="mt-1 text-xs text-slate-400">LoopX 会从当前状态投影生成工作台。</p>
        </div>
      </div>
    );
  }

  const [goalNode, todoNode, gateNode, evidenceNode, nextNode] = nodes;
  return (
    <div className="chat-goal-map rounded-2xl border border-slate-200/80 bg-white px-5 py-5 shadow-[0_12px_36px_rgba(15,23,42,0.045)] sm:px-7 sm:py-6">
      <div className="chat-map-goal relative z-10 mx-auto max-w-xl rounded-2xl border border-violet-200 bg-violet-50/75 p-5 text-violet-950 shadow-[0_8px_24px_rgba(124,58,237,0.07)]">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-[11px] font-bold tracking-[0.18em] text-violet-600">
            <Target className="size-3.5" />
            {goalNode?.eyebrow}
          </div>
          <Badge className="border-violet-200 bg-white/70 text-violet-700">{goal.status || "active"}</Badge>
        </div>
        <h2 className="mt-3 text-xl font-semibold tracking-tight">{goalNode?.title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-violet-800/80">{goalNode?.detail}</p>
      </div>

      <div className="chat-map-branches relative z-10 mt-12 grid gap-3 md:grid-cols-3">
        {[todoNode, gateNode, evidenceNode].map((node) => (
          <div
            className={cn(
              "min-h-36 rounded-xl border p-4 shadow-[0_4px_18px_rgba(15,23,42,0.035)]",
              node && nodeTone[node.tone],
            )}
            key={node?.kind}
          >
            <div className="flex items-center gap-2 text-[10px] font-bold tracking-[0.16em] opacity-65">
              <span className={cn("size-2 rounded-full", node && nodeDotTone[node.tone])} />
              {node?.eyebrow}
            </div>
            <h3 className="mt-3 text-sm font-semibold">{node?.title}</h3>
            <p className="mt-2 line-clamp-3 text-xs leading-5 opacity-70">{node?.detail}</p>
          </div>
        ))}
      </div>

      <div className="chat-map-next relative z-10 mt-10 rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3.5 text-slate-900">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white text-slate-600 shadow-sm ring-1 ring-slate-200">
            <ArrowUp className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] font-bold tracking-[0.16em] text-slate-400">{nextNode?.eyebrow}</div>
            <p className="mt-1 text-sm font-medium leading-5">{nextNode?.detail}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function DecisionCard({
  decision,
  goalId,
  onChange,
  onApplied,
}: {
  decision: DecisionItem;
  goalId: string;
  onChange: (next: DecisionItem) => void;
  onApplied: () => Promise<ChatStatus | null>;
}) {
  const reviewState = proposalReviewState(decision.proposal, decision.preview, decision.outcome);
  const resolved = decision.outcome !== "pending";
  const decisionSubtitle =
    decision.outcome === "approved"
      ? decision.receipt?.already_exists
        ? "Todo · 已存在，未重复写入"
        : "Todo · 已批准并写入"
      : decision.outcome === "rejected"
        ? "Todo · 已拒绝，零写入"
        : decision.outcome === "cancelled"
          ? "Todo · 已取消，零写入"
          : "Todo · 等待你的决定";

  async function handleReview() {
    onChange({ ...decision, busy: true, error: "", noWriteReceipt: null, projectionVerified: null });
    try {
      if (reviewState === "needs_preview") {
        const preview = await previewTodo(goalId, decision.proposal.text);
        onChange({
          ...decision,
          busy: false,
          preview,
          error: "",
          noWriteReceipt: null,
          projectionVerified: null,
        });
        return;
      }
      if (reviewState === "ready_to_approve" && decision.preview) {
        const result = await applyTodo(goalId, decision.proposal.text, decision.preview.preview_id);
        const refreshedStatus = await onApplied();
        onChange({
          ...decision,
          busy: false,
          outcome: "approved",
          error: "",
          noWriteReceipt: null,
          projectionVerified: refreshedStatus
            ? todoReceiptProjected(refreshedStatus, result.receipt)
            : null,
          receipt: result.receipt,
        });
      }
    } catch (error) {
      const noWriteReceipt =
        error instanceof ChatApiError ? todoNoWriteReceiptFromPayload(error.payload) : null;
      onChange({
        ...decision,
        busy: false,
        preview: reviewState === "ready_to_approve" ? null : decision.preview,
        error: error instanceof Error ? error.message : "审批动作失败，请重试。",
        noWriteReceipt,
      });
    }
  }

  function handleDecline() {
    const outcome = decision.preview ? "cancelled" : "rejected";
    onChange({
      ...decision,
      busy: false,
      error: "",
      noWriteReceipt: null,
      outcome,
      preview: null,
      projectionVerified: null,
      receipt: null,
    });
  }

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_10px_30px_rgba(15,23,42,0.045)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-sky-50 text-sky-600 ring-1 ring-sky-100">
            <Sparkles className="size-4" />
          </span>
          <div>
            <p className="text-xs font-semibold text-slate-900">Agent 建议</p>
            <p className="mt-0.5 text-[11px] text-slate-400">{decisionSubtitle}</p>
          </div>
        </div>
        <Badge
          variant={decision.proposal.priority === "P0" ? "danger" : "info"}
          className="rounded-full px-2.5"
        >
          {decision.proposal.priority}
        </Badge>
      </div>
      <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{decision.proposal.text}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{decision.proposal.rationale}</p>

      {decision.preview && decision.outcome === "pending" ? (
        <div className="mt-4 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-emerald-800">
            <ShieldCheck className="size-3.5" />
            预览已锁定
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-emerald-700/80">
            将写入当前 Goal 的 Agent Todo。状态变化后需要重新预览。
          </p>
        </div>
      ) : null}

      {decision.outcome === "approved" && decision.receipt ? (
        <div className="mt-4 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-emerald-800">
            <FileCheck2 className="size-3.5" />
            写入回执
          </div>
          <p className="mt-1.5 break-all text-[10px] leading-4 text-emerald-700/80">
            {todoReceiptLabel(decision.receipt)}
          </p>
          <p className="mt-1 text-[11px] font-medium leading-4 text-emerald-800">
            {todoReceiptOutcomeLabel(decision.receipt)}
          </p>
          {decision.projectionVerified === true ? (
            <p className="mt-1.5 text-[11px] leading-4 text-emerald-700">
              状态刷新已确认：Todo 已出现在当前 Goal。
            </p>
          ) : (
            <p className="mt-1.5 text-[11px] leading-4 text-amber-700">
              Todo 已写入；状态投影尚未确认，可点击顶部刷新重试。
            </p>
          )}
        </div>
      ) : null}

      {decision.outcome === "rejected" || decision.outcome === "cancelled" ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/80 p-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-700">
            <ShieldCheck className="size-3.5" />
            {decision.outcome === "rejected" ? "建议已拒绝" : "写入已取消"}
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-slate-500">没有调用 Todo 写入接口，当前 Goal 保持不变。</p>
        </div>
      ) : null}

      {decision.error ? (
        <div className="mt-3 rounded-xl border border-rose-100 bg-rose-50/70 p-3 text-xs leading-5 text-rose-700">
          <p>{decision.error}</p>
          {decision.noWriteReceipt ? (
            <p className="mt-1.5 text-[10px] font-semibold text-rose-600">
              {todoNoWriteReceiptLabel(decision.noWriteReceipt)}
            </p>
          ) : null}
        </div>
      ) : null}

      {resolved ? (
        <Button
          className={cn(
            "mt-4 w-full rounded-xl",
            reviewState === "approved"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-slate-200 bg-slate-50 text-slate-500",
          )}
          disabled
          variant="secondary"
        >
          {reviewState === "approved" ? <Check className="size-4" /> : <X className="size-4" />}
          {reviewState === "approved" && decision.receipt?.already_exists
            ? "已确认，无重复写入"
            : null}
          {reviewState === "approved" && !decision.receipt?.already_exists
            ? "已写入当前 Goal"
            : null}
          {reviewState === "rejected" ? "已拒绝，未写入" : null}
          {reviewState === "cancelled" ? "已取消，未写入" : null}
        </Button>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button className="rounded-xl" disabled={decision.busy} onClick={handleDecline} variant="ghost">
            <X className="size-4" />
            {reviewState === "ready_to_approve" ? "取消写入" : "拒绝建议"}
          </Button>
          <Button
            className={cn(
              "rounded-xl",
              reviewState === "ready_to_approve" && "border-slate-950 bg-slate-950 text-white hover:bg-slate-800",
            )}
            disabled={decision.busy}
            onClick={handleReview}
            variant={reviewState === "ready_to_approve" ? "primary" : "secondary"}
          >
            {decision.busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {reviewState === "needs_preview" ? "查看写入预览" : null}
            {reviewState === "ready_to_approve" ? "批准并写入" : null}
          </Button>
        </div>
      )}
    </article>
  );
}

function GoalReviewCard({ todo, onDiscuss }: { todo: ChatTodo; onDiscuss: () => void }) {
  const isGate = todo.task_class === "user_gate";
  return (
    <article className="rounded-2xl border border-amber-200/90 bg-white p-4 shadow-[0_10px_30px_rgba(15,23,42,0.04)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-amber-50 text-amber-600 ring-1 ring-amber-100">
            <Flag className="size-4" />
          </span>
          <div>
            <p className="text-xs font-semibold text-slate-900">{isGate ? "LoopX Gate" : "User action"}</p>
            <p className="mt-0.5 text-[11px] text-slate-400">已保存在当前 Goal</p>
          </div>
        </div>
        <Badge variant="warning" className="rounded-full px-2.5">待处理</Badge>
      </div>
      <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{todo.text}</p>
      {todo.evidence ? <p className="mt-2 text-xs leading-5 text-slate-500">{todo.evidence}</p> : null}
      <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50/65 p-3 text-[11px] leading-5 text-amber-800">
        这个项目会持续存在于 LoopX 状态中。Agent 可以解释影响，最终决定仍由你确认。
      </div>
      <Button className="mt-3 w-full rounded-xl" onClick={onDiscuss} variant="secondary">
        <MessageSquareText className="size-4" />
        在对话中处理
      </Button>
    </article>
  );
}

function CompletedGoalReviewCard({ todo }: { todo: ChatTodo }) {
  const isGate = todo.task_class === "user_gate";
  return (
    <article className="rounded-2xl border border-emerald-100 bg-white p-4 shadow-[0_10px_30px_rgba(15,23,42,0.035)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100">
            <Check className="size-4" />
          </span>
          <div>
            <p className="text-xs font-semibold text-slate-900">{isGate ? "LoopX Gate" : "User action"}</p>
            <p className="mt-0.5 text-[11px] text-slate-400">已保存在当前 Goal</p>
          </div>
        </div>
        <Badge variant="success" className="rounded-full px-2.5">已完成</Badge>
      </div>
      <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{todo.text}</p>
      {todo.evidence ? (
        <div className="mt-3 rounded-xl border border-emerald-100 bg-emerald-50/65 p-3 text-[11px] leading-5 text-emerald-800">
          {todo.evidence}
        </div>
      ) : null}
    </article>
  );
}

export function ChatPage({ initialGoalId = "" }: { initialGoalId?: string }) {
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [capabilities, setCapabilities] = useState<ChatCapabilities | null>(null);
  const [selectedGoalId, setSelectedGoalId] = useState(initialGoalId);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [decisions, setDecisions] = useState<DecisionItem[]>([]);
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [agentPhase, setAgentPhase] = useState<AgentPhase>("idle");
  const [activeTurnId, setActiveTurnId] = useState("");
  const [inboxView, setInboxView] = useState<InboxView>("pending");
  const [statusError, setStatusError] = useState("");
  const [sessionRecoveryNeeded, setSessionRecoveryNeeded] = useState(false);
  const [hostGate, setHostGate] = useState<HostGate | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const hydratedDecisionGoalRef = useRef("");
  const skipDecisionHistoryPersistRef = useRef(false);
  const streamAbortRef = useRef<AbortController | null>(null);
  const sessionConnectSequenceRef = useRef(0);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await fetchChatStatus();
      setStatus(next);
      setStatusError("");
      setSelectedGoalId((current) => current || next.selected_goal_id || next.goals[0]?.goal_id || "");
      return next;
    } catch (error) {
      setStatusError(error instanceof Error ? error.message : "状态读取失败");
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    void fetchChatCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
  }, []);

  const connectSession = useCallback(async (mode: "resume_latest" | "new") => {
    if (!selectedGoalId) return;
    const sequence = ++sessionConnectSequenceRef.current;
    setSessionRecoveryNeeded(false);
    setStatusError("");
    setSessionId("");
    setActiveTurnId("");
    setAgentPhase("starting");
    try {
      const created = await createChatSession(selectedGoalId, "codex", mode);
      if (sequence !== sessionConnectSequenceRef.current) return;
      setSessionId(created.session_id);
      setAgentPhase(created.resumed ? "resuming" : "idle");
      const snapshot = await fetchChatSession(created.session_id);
      if (sequence !== sessionConnectSequenceRef.current) return;
      setMessages(snapshot.messages.map((item) => ({
        id: item.message_id,
        role: item.role === "user" ? "user" : "agent",
        source: item.role === "error" ? "error" : item.role === "user" ? undefined : "agent",
        text: item.text,
      })));
      const turnId = snapshot.session.active_turn_id ?? "";
      setActiveTurnId(turnId);
      setAgentPhase(turnId ? "thinking" : "idle");
      if (!turnId) return;
      setSending(true);
      const streamedMessageId = randomId("agent-resume");
      setMessages((current) => [
        ...current,
        { id: streamedMessageId, role: "agent", source: "agent", text: "" },
      ]);
      const abortController = new AbortController();
      streamAbortRef.current = abortController;
      let streamedText = "";
      try {
        const streamed = await resumeChatTurnStreaming(created.session_id, turnId, {
          signal: abortController.signal,
          onDelta: (delta) => {
            streamedText += delta;
            setAgentPhase("streaming");
            setMessages((current) => current.map((item) =>
              item.id === streamedMessageId ? { ...item, text: streamedText } : item
            ));
          },
          onPhase: (phase, activeId) => {
            setActiveTurnId(activeId);
            if (phase === "turn.started") setAgentPhase("thinking");
          },
        });
        if (sequence !== sessionConnectSequenceRef.current) return;
        setMessages((current) => current.map((item) =>
          item.id === streamedMessageId
            ? {
                ...item,
                text: streamed.response.message || streamedText.trim() || "Codex 已完成分析。",
              }
            : item
        ));
        if (streamed.response.proposals.length) {
          setInboxView("pending");
          setDecisions((current) => [
            ...streamed.response.proposals.map((proposal) => ({
              id: randomId("decision"),
              noWriteReceipt: null,
              proposal,
              preview: null,
              projectionVerified: null,
              receipt: null,
              outcome: "pending" as const,
              busy: false,
              error: "",
            })),
            ...current,
          ]);
        }
        if (streamed.response.gate) {
          setInboxView("pending");
          setHostGate(streamed.response.gate);
        }
      } catch (error) {
        if (sequence !== sessionConnectSequenceRef.current) return;
        setMessages((current) => current.map((item) =>
          item.id === streamedMessageId
            ? {
                ...item,
                source: "error",
                reconnect: error instanceof ChatApiError && error.payload.reconnectable === true,
                text: error instanceof Error ? error.message : "无法恢复进行中的 Agent 回合。",
              }
            : item
        ));
      } finally {
        if (sequence === sessionConnectSequenceRef.current) {
          setSending(false);
          setActiveTurnId("");
          setAgentPhase("idle");
          streamAbortRef.current = null;
        }
      }
    } catch (error) {
      if (sequence !== sessionConnectSequenceRef.current) return;
      setAgentPhase("idle");
      setSessionRecoveryNeeded(
        error instanceof ChatApiError && error.payload.error_code === "resume_failed",
      );
      setStatusError(error instanceof Error ? error.message : "Codex 会话连接失败");
    }
  }, [selectedGoalId]);

  useEffect(() => {
    if (!selectedGoalId) return;
    void connectSession("resume_latest");
    return () => {
      sessionConnectSequenceRef.current += 1;
      streamAbortRef.current?.abort();
    };
  }, [connectSession, selectedGoalId]);

  useEffect(() => {
    if (!selectedGoalId || hydratedDecisionGoalRef.current === selectedGoalId) return;
    let restored: StoredDecisionHistoryItem[] = [];
    try {
      restored = parseCompletedDecisionHistory(
        window.sessionStorage.getItem(decisionHistoryStorageKey(selectedGoalId)),
        selectedGoalId,
      );
    } catch {
      restored = [];
    }
    hydratedDecisionGoalRef.current = selectedGoalId;
    skipDecisionHistoryPersistRef.current = true;
    setDecisions(restored.map(restoreDecisionHistoryItem));
  }, [selectedGoalId]);

  useEffect(() => {
    if (!selectedGoalId || hydratedDecisionGoalRef.current !== selectedGoalId) return;
    if (skipDecisionHistoryPersistRef.current) {
      skipDecisionHistoryPersistRef.current = false;
      return;
    }
    try {
      window.sessionStorage.setItem(
        decisionHistoryStorageKey(selectedGoalId),
        serializeCompletedDecisionHistory(selectedGoalId, completedDecisionHistory(decisions)),
      );
    } catch {
      // Session history is an optional local convenience; the Goal projection remains canonical.
    }
  }, [decisions, selectedGoalId]);

  const selectedGoal = selectChatGoal(status, selectedGoalId);
  const durableReviews = selectedGoal ? pendingGoalReviews(selectedGoal) : [];
  const completedDurableReviews = selectedGoal ? completedGoalReviews(selectedGoal) : [];
  const pendingDecisions = decisions.filter((decision) => decision.outcome === "pending");
  const completedDecisions = decisions.filter((decision) => decision.outcome !== "pending");
  const pendingDecisionCount =
    durableReviews.length + pendingDecisions.length + (hostGate ? 1 : 0);
  const completedDecisionCount = completedDurableReviews.length + completedDecisions.length;

  useEffect(() => {
    if (!status) return;
    setDecisions((current) => {
      let changed = false;
      const next = current.map((decision) => {
        if (decision.outcome !== "approved" || !decision.receipt) return decision;
        const projectionVerified = todoReceiptProjected(status, decision.receipt);
        if (decision.projectionVerified === projectionVerified) return decision;
        changed = true;
        return { ...decision, projectionVerified };
      });
      return changed ? next : current;
    });
  }, [status]);

  function changeGoal(goalId: string) {
    if (goalId === selectedGoalId) return;
    hydratedDecisionGoalRef.current = "";
    setSelectedGoalId(goalId);
    setSessionId("");
    setActiveTurnId("");
    setMessages([]);
    setDecisions([]);
    setHostGate(null);
    setSessionRecoveryNeeded(false);
    setAgentPhase("idle");
    setInboxView("pending");
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    const message = composer.trim();
    if (!message || !selectedGoal || sending) return;
    setComposer("");
    setHostGate(null);
    setMessages((current) => [...current, { id: randomId("user"), role: "user", text: message }]);
    const localAnswer = answerLocalStatusQuestion(status, message);
    if (localAnswer) {
      setMessages((current) => [
        ...current,
        { id: randomId("local"), role: "agent", source: "local", text: localAnswer },
      ]);
      requestAnimationFrame(() => composerRef.current?.focus());
      return;
    }
    setSending(true);
    setAgentPhase(sessionId ? "thinking" : "starting");
    const streamedMessageId = randomId("agent-stream");
    setMessages((current) => [
      ...current,
      { id: streamedMessageId, role: "agent", source: "agent", text: "" },
    ]);
    try {
      let activeSessionId = sessionId;
      if (!activeSessionId) {
        const session = await createChatSession(selectedGoal.goal_id);
        activeSessionId = session.session_id;
        setSessionId(activeSessionId);
      }
      setAgentPhase("thinking");
      const abortController = new AbortController();
      streamAbortRef.current = abortController;
      let streamedText = "";
      const streamed = await sendChatTurnStreaming(activeSessionId, message, {
        signal: abortController.signal,
        onDelta: (delta) => {
          streamedText += delta;
          setAgentPhase("streaming");
          setMessages((current) => current.map((item) =>
            item.id === streamedMessageId ? { ...item, text: streamedText } : item
          ));
        },
        onPhase: (phase, turnId) => {
          setActiveTurnId(turnId);
          if (phase === "turn.started") setAgentPhase("thinking");
        },
      });
      const response = streamed.response;
      setMessages((current) => current.map((item) =>
        item.id === streamedMessageId
          ? { ...item, text: response.message || streamedText.trim() || "Codex 已完成分析。" }
          : item
      ));
      if (response.proposals.length) {
        setInboxView("pending");
        setDecisions((current) => [
          ...response.proposals.map((proposal) => ({
            id: randomId("decision"),
            noWriteReceipt: null,
            proposal,
            preview: null,
            projectionVerified: null,
            receipt: null,
            outcome: "pending" as const,
            busy: false,
            error: "",
          })),
          ...current,
        ]);
      }
      if (response.gate) {
        setInboxView("pending");
        setHostGate(response.gate);
      }
    } catch (error) {
      const gate = gateFromError(error);
      const sessionWasInvalidated =
        error instanceof ChatApiError && sessionInvalidatedByPayload(error.payload);
      if (sessionWasInvalidated) setSessionId("");
      if (gate) setHostGate(gate);
      const summary = gate?.summary || (error instanceof Error ? error.message : "Agent 会话暂时不可用。");
      setMessages((current) => current.map((item) =>
        item.id === streamedMessageId
          ? {
              ...item,
              reconnect: error instanceof ChatApiError && error.payload.reconnectable === true,
              source: "error",
              text: chatFailureMessage(summary, sessionWasInvalidated),
            }
          : item
      ));
    } finally {
      setSending(false);
      setAgentPhase("idle");
      setActiveTurnId("");
      streamAbortRef.current = null;
      composerRef.current?.focus();
    }
  }

  async function interruptActiveTurn() {
    if (!sessionId || !activeTurnId) return;
    setAgentPhase("interrupting");
    try {
      await interruptChatTurn(sessionId, activeTurnId);
      streamAbortRef.current?.abort();
    } finally {
      setSending(false);
      setActiveTurnId("");
      setAgentPhase("idle");
    }
  }

  function updateDecision(next: DecisionItem) {
    setDecisions((current) => current.map((item) => (item.id === next.id ? next : item)));
  }

  function discussGoalReview(todo: ChatTodo) {
    setComposer(`请说明并协助处理这个 LoopX ${todo.task_class === "user_gate" ? "Gate" : "待办"}：${todo.text}`);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  function openStewardPrompt(prompt: string) {
    setComposer(prompt);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  return (
    <main className="chat-shell min-h-screen bg-[#f7f8f6] text-slate-950">
      <header className="chat-topbar sticky top-0 z-40 flex h-16 items-center justify-between border-b border-slate-200/80 bg-white/92 px-5 backdrop-blur-xl lg:px-7">
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-xl bg-slate-950 text-white shadow-sm">
              <Layers3 className="size-4" strokeWidth={2.2} />
            </span>
            <span className="text-sm font-bold tracking-tight">LoopX</span>
          </div>
          <span className="hidden h-5 w-px bg-slate-200 sm:block" />
          <div className="hidden min-w-0 sm:block">
            <p className="truncate text-xs font-semibold text-slate-700">Goal Studio</p>
            <p className="truncate text-[10px] text-slate-400">{selectedGoal?.goal_id || "正在连接状态"}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="刷新 Goal 状态"
            className="grid size-9 place-items-center rounded-xl border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-900"
            onClick={() => void refreshStatus()}
            type="button"
          >
            <RefreshCw className="size-4" />
          </button>
          <div className="hidden items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700 sm:flex">
            <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.12)]" />
            {agentBackendLabel(capabilities?.agent_backend)} · {capabilities?.sandbox === "read-only" ? "只读" : "只读模式"}
          </div>
        </div>
      </header>

      <div className="chat-workspace-grid mx-auto grid min-h-[calc(100vh-4rem)] max-w-[1680px] grid-cols-1 xl:grid-cols-[224px_minmax(560px,1fr)_360px]">
        <aside className="hidden border-r border-slate-200/70 bg-white/55 px-4 py-5 xl:block">
          <div className="flex items-center justify-between px-2">
            <p className="text-[10px] font-bold tracking-[0.17em] text-slate-400">WORKSPACE</p>
            <button className="grid size-7 place-items-center rounded-lg text-slate-400 hover:bg-white hover:text-slate-800" type="button">
              <Plus className="size-3.5" />
            </button>
          </div>
          <nav className="mt-3 space-y-1">
            <button className="flex w-full items-center gap-2.5 rounded-xl bg-white px-3 py-2.5 text-left text-xs font-semibold text-slate-900 shadow-sm ring-1 ring-slate-200/80" type="button">
              <Target className="size-4 text-violet-500" />
              Goal Studio
            </button>
            <button className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-xs font-medium text-slate-500 hover:bg-white" type="button">
              <MessageSquareText className="size-4" />
              对话记录
            </button>
            <button className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-xs font-medium text-slate-500 hover:bg-white" type="button">
              <FileCheck2 className="size-4" />
              Evidence
            </button>
          </nav>

          <div className="mt-7 flex items-center justify-between px-2">
            <p className="text-[10px] font-bold tracking-[0.17em] text-slate-400">GOALS</p>
            <Search className="size-3.5 text-slate-300" />
          </div>
          <div className="mt-3 space-y-1.5">
            {status?.goals.map((goal) => (
              <button
                className={cn(
                  "group w-full rounded-xl border px-3 py-3 text-left transition",
                  goal.goal_id === selectedGoalId
                    ? "border-slate-200 bg-white shadow-sm"
                    : "border-transparent hover:border-slate-200/70 hover:bg-white/70",
                )}
                key={goal.goal_id}
                onClick={() => changeGoal(goal.goal_id)}
                type="button"
              >
                <div className="flex items-center gap-2">
                  <span className={cn("size-1.5 rounded-full", goal.waiting_on === "user_or_controller" ? "bg-amber-400" : "bg-emerald-400")} />
                  <span className="truncate text-xs font-semibold text-slate-700">{goal.title}</span>
                </div>
                <p className="mt-1.5 truncate pl-3.5 text-[10px] text-slate-400">{goal.top_todo?.text || goal.next_action}</p>
              </button>
            ))}
          </div>

          <div className="mt-7 rounded-2xl border border-slate-200 bg-white/80 p-3.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              <Gauge className="size-4 text-sky-500" />
              {quotaLabel(selectedGoal?.quota.state || null)}
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-sky-400"
                style={{
                  width: `${Math.min(
                    100,
                    ((selectedGoal?.quota.spent_slots || 0) / Math.max(1, selectedGoal?.quota.allowed_slots || 1)) * 100,
                  )}%`,
                }}
              />
            </div>
            <p className="mt-2 text-[10px] leading-4 text-slate-400">每次 Agent 回合都受当前 Goal、Gate 与配额约束。</p>
          </div>
        </aside>

        <section className="min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          <div className="mx-auto max-w-5xl">
            <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
              <div>
                <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-400">
                  <CircleDot className="size-3.5 text-emerald-500" />
                  LIVE GOAL PROJECTION
                </div>
                <h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em] text-slate-950">{selectedGoal?.title || "Goal Studio"}</h1>
                <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-500">
                  {selectedGoal?.objective || "从 Goal、Todo、Gate 和 Evidence 组织下一步。"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="neutral" className="rounded-full bg-white px-2.5 py-1 text-slate-500">
                  <LockKeyhole className="size-3" />
                  Agent 只读
                </Badge>
                <Badge variant="success" className="rounded-full px-2.5 py-1">
                  <ShieldCheck className="size-3" />
                  写入需批准
                </Badge>
              </div>
            </div>

            {statusError ? (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
                <span>{statusError}</span>
                {sessionRecoveryNeeded ? (
                  <span className="flex gap-2">
                    <button className="rounded-lg border border-rose-200 bg-white px-3 py-1.5 font-semibold" onClick={() => void connectSession("resume_latest")}>重新恢复</button>
                    <button className="rounded-lg bg-rose-600 px-3 py-1.5 font-semibold text-white" onClick={() => void connectSession("new")}>新建会话</button>
                  </span>
                ) : null}
              </div>
            ) : null}

            <section className="mb-5 overflow-hidden rounded-2xl border border-violet-100 bg-[linear-gradient(135deg,rgba(255,255,255,0.98),rgba(245,243,255,0.78))] shadow-[0_12px_36px_rgba(76,29,149,0.055)]">
              <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div className="flex min-w-0 items-center gap-3.5">
                  <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-violet-600 text-white shadow-[0_8px_20px_rgba(124,58,237,0.22)]">
                    <Sparkles className="size-4.5" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-semibold tracking-tight text-slate-950">问问管家</h2>
                      <Badge className="rounded-full border-violet-100 bg-white/80 px-2 text-[9px] text-violet-600">只读</Badge>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-slate-500">读懂 Goal、Todo 与 Gate，先把复杂状态翻译成下一步。</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 sm:justify-end">
                  {stewardPrompts.map((item) => (
                    <button
                      className="rounded-full border border-slate-200/90 bg-white/90 px-3 py-1.5 text-[11px] font-semibold text-slate-600 shadow-sm transition hover:-translate-y-0.5 hover:border-violet-200 hover:text-violet-700 hover:shadow-md"
                      key={item.id}
                      onClick={() => openStewardPrompt(item.prompt)}
                      type="button"
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="border-t border-violet-100/80 bg-white/45 px-5 py-2 text-[10px] text-slate-400 sm:px-6">
                管家只生成分析与候选动作；写入 Todo 前会送到右侧 Decision Inbox。
              </div>
            </section>

            <GoalMap preferredGoalId={selectedGoalId} status={status} />

            <section className="mt-5 overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_12px_36px_rgba(15,23,42,0.04)]">
              <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
                <div className="flex items-center gap-2">
                  <span className="grid size-7 place-items-center rounded-lg bg-slate-950 text-white">
                    <Bot className="size-3.5" />
                  </span>
                  <div>
                    <p className="text-xs font-semibold text-slate-800">管家对话</p>
                    <p className="text-[10px] text-slate-400">状态问题读取本地投影；推理问题交给只读 Agent</p>
                  </div>
                </div>
                {sending ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-medium text-violet-600">
                      {agentPhaseLabel[agentPhase]}
                    </span>
                    {activeTurnId ? (
                      <button
                        className="rounded-lg border border-rose-200 px-2 py-1 text-[10px] font-semibold text-rose-600 hover:bg-rose-50"
                        onClick={() => void interruptActiveTurn()}
                        type="button"
                      >
                        中断
                      </button>
                    ) : null}
                  </div>
                ) : sessionId ? (
                  <span className="text-[10px] font-medium text-emerald-600">Codex 会话就绪</span>
                ) : null}
              </div>

              <div className="max-h-72 min-h-24 space-y-3 overflow-y-auto px-5 py-4">
                {messages.length === 0 ? (
                  <div className="flex items-start gap-3 rounded-xl bg-slate-50/80 p-3.5">
                    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-white text-violet-500 shadow-sm ring-1 ring-slate-200">
                      <Sparkles className="size-3.5" />
                    </span>
                    <p className="text-xs leading-5 text-slate-500">
                      可以问：“结合当前 Goal，下一步最值得做什么？” Agent 只会生成候选动作，Todo 写回会等待你的确认。
                    </p>
                  </div>
                ) : null}
                {messages.map((message) => (
                  <div className={cn("flex gap-2.5", message.role === "user" && "justify-end")} key={message.id}>
                    {message.role === "agent" ? (
                      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-violet-50 text-violet-600 ring-1 ring-violet-100">
                        <Bot className="size-3.5" />
                      </span>
                    ) : null}
                    <div
                      className={cn(
                        "max-w-[82%] rounded-2xl px-3.5 py-2.5 text-xs leading-5",
                        message.role === "user"
                          ? "rounded-br-md bg-slate-950 text-white"
                          : "rounded-bl-md border border-slate-200 bg-white text-slate-600",
                      )}
                    >
                      {message.source === "local" ? (
                        <span className="mb-1 block text-[9px] font-bold tracking-[0.12em] text-emerald-600">
                          LOOPX 状态直答
                        </span>
                      ) : null}
                      {message.text}
                      {message.reconnect ? (
                        <button
                          className="mt-2 block rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-slate-700 hover:bg-slate-100"
                          onClick={() => window.location.reload()}
                          type="button"
                        >
                          继续连接
                        </button>
                      ) : null}
                    </div>
                    {message.role === "user" ? (
                      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
                        <UserRound className="size-3.5" />
                      </span>
                    ) : null}
                  </div>
                ))}
                {sending ? (
                  <div className="flex items-center gap-2 text-[11px] text-slate-400">
                    <Loader2 className="size-3.5 animate-spin" />
                    {agentPhaseLabel[agentPhase]}…
                  </div>
                ) : null}
              </div>

              <form className="border-t border-slate-100 p-3" onSubmit={submitMessage}>
                <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50/65 p-2 pl-3 focus-within:border-slate-300 focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(148,163,184,0.1)]">
                  <textarea
                    className="max-h-28 min-h-10 flex-1 resize-none bg-transparent py-2 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400"
                    onChange={(event) => setComposer(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                    placeholder="和 Agent 讨论这个 Goal…"
                    ref={composerRef}
                    rows={1}
                    value={composer}
                  />
                  <button
                    aria-label="发送消息"
                    className="grid size-9 shrink-0 place-items-center rounded-xl bg-slate-950 text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                    disabled={!composer.trim() || !selectedGoal || sending}
                    type="submit"
                  >
                    {sending ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
                  </button>
                </div>
                <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-slate-400">
                  <span>Enter 发送 · Shift + Enter 换行</span>
                  <span>只读分析 · 审批后写 Todo</span>
                </div>
                {sessionId ? (
                  <details className="mt-2 rounded-xl border border-slate-100 bg-white px-3 py-2 text-[10px] text-slate-400">
                    <summary className="cursor-pointer font-semibold text-slate-500">高级诊断</summary>
                    <div className="mt-2 grid gap-1 sm:grid-cols-2">
                      <span>Session · {sessionId.slice(0, 12)}</span>
                      <span>Turn · {activeTurnId ? activeTurnId.slice(0, 12) : "无运行中回合"}</span>
                      <span>Adapter · Codex app-server</span>
                      <span>恢复 · {capabilities?.resume ? "可恢复" : "不可用"}</span>
                    </div>
                  </details>
                ) : null}
              </form>
            </section>
          </div>
        </section>

        <aside className="border-l border-slate-200/70 bg-[#fafaf8] px-4 py-5 sm:px-5 lg:py-7">
          <div className="sticky top-24">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Inbox className="size-4 text-slate-600" />
                  <h2 className="text-sm font-semibold text-slate-900">Decision Inbox</h2>
                  {pendingDecisionCount ? (
                    <span className="grid min-w-5 place-items-center rounded-full bg-slate-950 px-1.5 py-0.5 text-[10px] font-bold text-white">
                      {pendingDecisionCount}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-[11px] text-slate-400">待你审阅的 Agent 建议与 Gate</p>
              </div>
              <Clock3 className="size-4 text-slate-300" />
            </div>

            <div
              aria-label="Decision Inbox 视图"
              className="mt-4 flex rounded-xl border border-slate-200 bg-white p-1 text-[11px] font-semibold text-slate-500"
              role="tablist"
            >
              <button
                aria-controls="decision-inbox-panel"
                aria-selected={inboxView === "pending"}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 transition",
                  inboxView === "pending" ? "bg-slate-100 text-slate-900" : "hover:bg-slate-50",
                )}
                onClick={() => setInboxView("pending")}
                role="tab"
                type="button"
              >
                待你处理
                {pendingDecisionCount ? (
                  <span className="rounded-full bg-slate-950 px-1.5 text-[9px] leading-4 text-white">
                    {pendingDecisionCount}
                  </span>
                ) : null}
              </button>
              <button
                aria-controls="decision-inbox-panel"
                aria-selected={inboxView === "completed"}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 transition",
                  inboxView === "completed" ? "bg-slate-100 text-slate-900" : "hover:bg-slate-50",
                )}
                onClick={() => setInboxView("completed")}
                role="tab"
                type="button"
              >
                最近完成
                {completedDecisionCount ? (
                  <span className="rounded-full bg-emerald-100 px-1.5 text-[9px] leading-4 text-emerald-700">
                    {completedDecisionCount}
                  </span>
                ) : null}
              </button>
            </div>

            <div
              className="mt-4 max-h-[calc(100vh-13rem)] space-y-3 overflow-y-auto pb-6"
              id="decision-inbox-panel"
              role="tabpanel"
            >
              {inboxView === "pending" ? durableReviews.map((todo) => (
                <GoalReviewCard
                  key={todo.todo_id || todo.text}
                  onDiscuss={() => discussGoalReview(todo)}
                  todo={todo}
                />
              )) : null}

              {inboxView === "pending" && hostGate ? (
                <article className="rounded-2xl border border-amber-200 bg-amber-50/80 p-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-amber-900">
                    <Flag className="size-4" />
                    {hostGate.kind.replaceAll("_", " ")}
                  </div>
                  <p className="mt-3 text-sm font-semibold leading-5 text-amber-950">{hostGate.summary}</p>
                  <div className="mt-3 flex gap-2 rounded-xl border border-amber-200/80 bg-white/65 p-3 text-xs leading-5 text-amber-800">
                    <ChevronRight className="mt-0.5 size-3.5 shrink-0" />
                    {hostGate.next_action}
                  </div>
                </article>
              ) : null}

              {inboxView === "pending" ? pendingDecisions.map((decision) => (
                <DecisionCard
                  decision={decision}
                  goalId={selectedGoalId}
                  key={decision.id}
                  onApplied={refreshStatus}
                  onChange={updateDecision}
                />
              )) : null}

              {inboxView === "completed" ? completedDecisions.map((decision) => (
                <DecisionCard
                  decision={decision}
                  goalId={selectedGoalId}
                  key={decision.id}
                  onApplied={refreshStatus}
                  onChange={updateDecision}
                />
              )) : null}

              {inboxView === "completed" ? completedDurableReviews.slice(0, 12).map((todo) => (
                <CompletedGoalReviewCard key={todo.todo_id || todo.text} todo={todo} />
              )) : null}

              {inboxView === "pending" && !hostGate && pendingDecisions.length === 0 && durableReviews.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-white/55 px-5 py-10 text-center">
                  <div className="mx-auto grid size-10 place-items-center rounded-2xl bg-white text-slate-400 shadow-sm ring-1 ring-slate-200">
                    <Inbox className="size-4" />
                  </div>
                  <p className="mt-3 text-xs font-semibold text-slate-700">Inbox 很安静</p>
                  <p className="mx-auto mt-1.5 max-w-[220px] text-[11px] leading-5 text-slate-400">
                    Agent 生成候选 Todo 或遇到 Gate 后，会在这里等待你的决定。
                  </p>
                </div>
              ) : null}

              {inboxView === "completed" && completedDecisions.length === 0 && completedDurableReviews.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-white/55 px-5 py-10 text-center">
                  <div className="mx-auto grid size-10 place-items-center rounded-2xl bg-white text-slate-400 shadow-sm ring-1 ring-slate-200">
                    <Clock3 className="size-4" />
                  </div>
                  <p className="mt-3 text-xs font-semibold text-slate-700">还没有完成记录</p>
                  <p className="mx-auto mt-1.5 max-w-[220px] text-[11px] leading-5 text-slate-400">
                    处理过的 Gate、User action 与已批准 Todo 会保留在这里。
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
