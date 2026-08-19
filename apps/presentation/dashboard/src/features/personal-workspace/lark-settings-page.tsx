import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Check,
  ExternalLink,
  Link2,
  Loader2,
  MessageSquareText,
  Plus,
  Search,
  Settings2,
  Unlink,
  X,
} from "lucide-react";

import {
  ChatApiError,
  cancelLarkAppSetup,
  connectLarkGoalTopic,
  disconnectLarkGoalTopic,
  fetchLarkAppSetup,
  fetchLarkApps,
  fetchLarkConnections,
  fetchLarkGroupChats,
  startLarkAppSetup,
  type LarkApp,
  type LarkAppSetup,
  type LarkGoalConnection,
  type LarkGroupChat,
} from "../../data/chat";
import type { WorkspaceGoal } from "./personal-workspace-model";

type Tab = "apps" | "connections";

function larkConnectionHealth(connection: LarkGoalConnection): { label: string; detail: string; ready: boolean } {
  if (connection.listener_status === "starting") {
    return { label: "正在启动", detail: "LoopX 正在启动该 App 的消息事件监听。", ready: false };
  }
  if (connection.listener_status === "retrying") {
    return { label: "监听重试中", detail: "事件监听暂时中断，LoopX 正在自动重试。", ready: false };
  }
  if (connection.listener_status === "stopped" || connection.listener_status === null) {
    return { label: "监听未启动", detail: "请刷新连接或重新启动 LoopX 后再试。", ready: false };
  }
  if (connection.last_event_status === "message_context_permission_required") {
    return { label: "消息权限不足", detail: "已收到消息事件，但无法读取群消息上下文。请发布并授权该 App 的群消息读取权限。", ready: false };
  }
  if (connection.last_event_status === "processing_failed") {
    return { label: "消息处理失败", detail: "已收到消息事件，但 Agent 处理失败。请查看本地诊断后重试。", ready: false };
  }
  if (connection.last_event_status === "ignored" && connection.last_event_reason === "not_addressed") {
    return {
      label: "最近消息未直接 @ 机器人",
      detail: "监听正常；当前连接只响应直接 @ 机器人或对机器人的回复。",
      ready: true,
    };
  }
  if (connection.last_event_status === "ignored" && connection.last_event_reason === "self_message") {
    return { label: "监听中", detail: "已忽略机器人自身发送的消息，避免重复回复。", ready: true };
  }
  if (
    connection.health_error_code === "lark_event_route_mismatch"
    || ["chat_mismatch", "topic_mismatch"].includes(connection.last_event_reason ?? "")
  ) {
    return {
      label: "消息未匹配当前 Goal Topic",
      detail: "事件来自其他群聊或 Topic。请重新选择群聊并连接该 Goal，然后发送一条新的 @ 消息。",
      ready: false,
    };
  }
  if (["invalid_event", "binding_unavailable"].includes(connection.last_event_reason ?? "")) {
    return {
      label: "消息无法路由到 Goal",
      detail: "当前连接信息不完整。请重新连接该 Goal 后再发送一条新的 @ 消息。",
      ready: false,
    };
  }
  if (connection.last_event_status === "replied_and_acknowledged") {
    return { label: "监听中", detail: `已处理 ${connection.event_count} 条事件，成功回复 ${connection.replied_count} 条。`, ready: true };
  }
  if (connection.health_error_code === "lark_event_delivery_unverified" || connection.event_count === 0) {
    return {
      label: "事件订阅待验证",
      detail: "长连接已启动，但尚未收到消息事件。请启用 im.message.receive_v1，开通群聊 @ 消息权限，发布新版后再发送一条新的 @ 消息。",
      ready: false,
    };
  }
  return { label: connection.reply_ready ? "监听中" : "自动回复不可用", detail: `最近事件状态：${connection.last_event_status ?? "等待处理"}`, ready: connection.reply_ready };
}

function larkErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ChatApiError) {
    const code = String(cause.payload.error_code ?? "");
    const messages: Record<string, string> = {
      lark_cli_not_installed: "未发现 lark-cli。请先安装 lark-cli，然后重新启动 LoopX。",
      lark_cli_not_executable: "已找到配置的 lark-cli，但当前无法执行。请检查安装或启动参数。",
      lark_cli_start_failed: "lark-cli 启动失败。请检查安装状态，然后重新启动 LoopX。",
      lark_message_permissions_required: "该 App 缺少自动回复所需的机器人权限。请开启 im:message.group_at_msg:readonly 和 im:message:send_as_bot，发布新版后回来刷新重试。",
      lark_app_required: "请选择一个 Lark App profile。",
      invalid_lark_app: "Lark App profile 不可用或尚未完成授权。",
      lark_group_lookup_failed: "无法读取该机器人已加入的群。请检查机器人状态后重试。",
      provider_api_failed: "飞书 API 调用失败，且没有生成已验证回执。请稍后重试。",
    };
    return messages[code] ?? cause.message;
  }
  return cause instanceof Error ? cause.message : fallback;
}

export function LarkSettingsPage({
  focusGoalConnection = false,
  goals,
  initialGoalId,
  onChanged,
  onClose,
}: {
  focusGoalConnection?: boolean;
  goals: WorkspaceGoal[];
  initialGoalId?: string | null;
  onChanged?: () => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("connections");
  const [apps, setApps] = useState<LarkApp[]>([]);
  const [connections, setConnections] = useState<LarkGoalConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(focusGoalConnection);
  const [appRef, setAppRef] = useState("");
  const [goalId, setGoalId] = useState(initialGoalId ?? goals[0]?.goalId ?? "");
  const [chatQuery, setChatQuery] = useState("");
  const [chats, setChats] = useState<LarkGroupChat[]>([]);
  const [chatId, setChatId] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatLoadError, setChatLoadError] = useState<string | null>(null);
  const [incomingMode, setIncomingMode] = useState<"mentions" | "all">("mentions");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [editingGoalId, setEditingGoalId] = useState<string | null>(null);
  const [disconnectGoalId, setDisconnectGoalId] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupAppRef, setSetupAppRef] = useState("loopx-workspace-bot");
  const [setupBrand, setSetupBrand] = useState<"feishu" | "lark">("feishu");
  const [setupSnapshot, setSetupSnapshot] = useState<LarkAppSetup | null>(null);
  const [setupStarting, setSetupStarting] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);
  const setupPopup = useRef<Window | null>(null);
  const openedSetupUrl = useRef<string | null>(null);
  const focusedGoalOpened = useRef(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [nextApps, nextConnections] = await Promise.all([
        fetchLarkApps(),
        fetchLarkConnections(),
      ]);
      setApps(nextApps);
      setConnections(nextConnections);
      setAppRef((current) => current || nextApps.find((app) => app.reply_ready)?.app_ref || nextApps.find((app) => app.ready)?.app_ref || nextApps[0]?.app_ref || "");
    } catch (cause) {
      setError(larkErrorMessage(cause, "Lark 配置加载失败"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (!focusGoalConnection || loading || focusedGoalOpened.current || !initialGoalId) return;
    focusedGoalOpened.current = true;
    const connection = connections.find((item) => item.goal_id === initialGoalId);
    if (connection) openConnectionEditor(connection);
    else openConnect(goals.find((goal) => goal.goalId === initialGoalId));
  }, [connections, focusGoalConnection, goals, initialGoalId, loading]);

  useEffect(() => {
    if (!modalOpen || !appRef) {
      setChats([]);
      setChatId("");
      setChatLoading(false);
      setChatLoadError(null);
      return;
    }
    let cancelled = false;
    setChatLoading(true);
    setChatLoadError(null);
    const timer = window.setTimeout(() => {
      void fetchLarkGroupChats(appRef, chatQuery)
        .then((items) => {
          if (cancelled) return;
          setChats(items);
          setChatId((current) => items.some((item) => item.chat_id === current) ? current : items[0]?.chat_id ?? "");
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setChats([]);
            setChatId("");
            setChatLoadError(larkErrorMessage(cause, "群聊加载失败"));
          }
        })
        .finally(() => {
          if (!cancelled) setChatLoading(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [appRef, chatQuery, modalOpen]);

  useEffect(() => {
    if (!setupOpen || !setupSnapshot || ["ready", "failed", "cancelled"].includes(setupSnapshot.status)) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void fetchLarkAppSetup(setupSnapshot.setup_id)
        .then(async (snapshot) => {
          if (cancelled) return;
          setSetupSnapshot(snapshot);
          if (snapshot.verification_url && openedSetupUrl.current !== snapshot.verification_url) {
            openedSetupUrl.current = snapshot.verification_url;
            if (setupPopup.current && !setupPopup.current.closed) {
              setupPopup.current.location.href = snapshot.verification_url;
            }
          }
          if (snapshot.status === "ready") {
            await refresh();
            setAppRef(snapshot.app_ref);
            setSetupOpen(false);
          }
          if (snapshot.status === "failed") {
            setSetupError(snapshot.error ?? "Lark App 创建失败");
          }
        })
        .catch((cause: unknown) => {
          if (!cancelled) setSetupError(larkErrorMessage(cause, "创建状态查询失败"));
        });
    }, 650);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [setupOpen, setupSnapshot]);

  const selectedGoal = goals.find((goal) => goal.goalId === goalId);
  const selectedApp = apps.find((app) => app.app_ref === appRef);
  const selectedChat = chats.find((chat) => chat.chat_id === chatId);
  const filteredConnections = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    if (!keyword) return connections;
    return connections.filter((connection) => [
      connection.app_label,
      connection.chat_name,
      connection.goal_title,
      connection.topic_name,
    ].some((value) => value.toLocaleLowerCase().includes(keyword)));
  }, [connections, query]);

  function openConnect(goal?: WorkspaceGoal) {
    setEditingGoalId(null);
    setGoalId(goal?.goalId ?? initialGoalId ?? goals[0]?.goalId ?? "");
    setChatQuery("");
    setConnectError(null);
    setModalOpen(true);
  }

  function openConnectionEditor(connection: LarkGoalConnection) {
    setEditingGoalId(connection.goal_id);
    setAppRef(connection.app_ref);
    setGoalId(connection.goal_id);
    setIncomingMode(connection.incoming_mode);
    setChatQuery(connection.chat_name);
    setConnectError(null);
    setModalOpen(true);
  }

  function openSetup() {
    setSetupSnapshot(null);
    setSetupError(null);
    openedSetupUrl.current = null;
    setSetupOpen(true);
  }

  async function startSetup() {
    if (setupStarting || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(setupAppRef)) return;
    setSetupStarting(true);
    setSetupError(null);
    openedSetupUrl.current = null;
    setupPopup.current = window.open(window.location.href, "_blank");
    try {
      const snapshot = await startLarkAppSetup({ appRef: setupAppRef, brand: setupBrand });
      setSetupSnapshot(snapshot);
    } catch (cause) {
      setupPopup.current?.close();
      setSetupError(larkErrorMessage(cause, "无法启动 Lark App 创建流程"));
    } finally {
      setSetupStarting(false);
    }
  }

  async function closeSetup() {
    const snapshot = setupSnapshot;
    setSetupOpen(false);
    setupPopup.current?.close();
    if (snapshot && !["ready", "failed", "cancelled"].includes(snapshot.status)) {
      try {
        await cancelLarkAppSetup(snapshot.setup_id);
      } catch {
        // The local setup process may already have completed while the modal closed.
      }
    }
  }

  async function connect() {
    if (!appRef || !goalId || !selectedChat || connecting) return;
    setConnecting(true);
    setConnectError(null);
    try {
      const input = {
        appRef,
        chatId: selectedChat.chat_id,
        chatName: selectedChat.chat_name,
        goalId,
        incomingMode,
      } as const;
      const preview = await connectLarkGoalTopic({ ...input, execute: false });
      if (!preview.ok) throw new ChatApiError(preview.public_summary ?? preview.blocker ?? "绑定预览失败", { error_code: preview.blocker ?? "provider_api_failed" });
      const result = await connectLarkGoalTopic({ ...input, execute: true });
      if (!result.ok) throw new ChatApiError(result.public_summary ?? result.blocker ?? "绑定失败", { error_code: result.blocker ?? "provider_api_failed" });
      setModalOpen(false);
      await refresh();
      onChanged?.();
    } catch (cause) {
      setConnectError(larkErrorMessage(cause, "绑定失败"));
    } finally {
      setConnecting(false);
    }
  }

  async function disconnect(goal: string) {
    if (disconnectGoalId !== goal) {
      setDisconnectGoalId(goal);
      return;
    }
    try {
      await disconnectLarkGoalTopic(goal);
      setDisconnectGoalId(null);
      await refresh();
      onChanged?.();
    } catch (cause) {
      setError(larkErrorMessage(cause, "解绑失败"));
    }
  }

  return (
    <section className="personal-lark-settings" aria-label="Lark configuration">
      <header className="personal-lark-header">
        <div>
          <small>Goal connections</small>
          <h1>Lark</h1>
          <p>管理可复用的 Lark App，并用独立 Topic 将群聊连接到 Goal。</p>
        </div>
        <button aria-label="关闭 Lark 设置" className="personal-icon-button" onClick={onClose} type="button"><X size={18} /></button>
      </header>

      <nav className="personal-lark-tabs" aria-label="Lark management sections">
        <button aria-current={tab === "apps" ? "page" : undefined} onClick={() => setTab("apps")} type="button">Lark Apps <span>{loading ? "…" : apps.length}</span></button>
        <button aria-current={tab === "connections" ? "page" : undefined} onClick={() => setTab("connections")} type="button">Connections <span>{loading ? "…" : connections.length}</span></button>
      </nav>

      {error ? <p className="personal-notification-error">{error}</p> : null}
      {loading ? <div className="personal-lark-loading"><Loader2 className="is-spinning" size={18} />加载 Lark 配置…</div> : null}

      {!loading && tab === "apps" ? (
        <div className="personal-lark-apps">
          <div className="personal-lark-app-toolbar"><span>{apps.length} reusable Apps</span><button className="personal-primary-action" onClick={openSetup} type="button"><Plus size={16} />New Lark App</button></div>
          <div className="personal-lark-app-grid">
            {apps.map((app) => (
              <article className="personal-lark-app-card" key={app.app_ref}>
                <span className="personal-lark-app-avatar"><Bot size={19} /></span>
                <div><strong>{app.label}</strong><small>{app.brand} · lark-cli profile</small></div>
                <em className={app.reply_ready ? "is-ready" : "is-off"}>{app.reply_ready ? "Auto reply ready" : app.ready ? "Needs message permissions" : "Needs setup"}</em>
                <p>{connections.filter((connection) => connection.app_ref === app.app_ref).length} Goal connections{app.ready && !app.reply_ready ? " · 自动回复暂不可用" : ""}</p>
              </article>
            ))}
            {apps.length === 0 ? <p className="personal-lark-empty">还没有可用的 lark-cli App profile。</p> : null}
          </div>
        </div>
      ) : null}

      {!loading && tab === "connections" ? (
        <div className="personal-lark-connections">
          <div className="personal-lark-toolbar">
            <label><Search size={16} /><input aria-label="搜索 Lark connections" onChange={(event) => setQuery(event.target.value)} placeholder="搜索 App、群、Goal 或 Topic" type="search" value={query} /></label>
            <button className="personal-primary-action" disabled={apps.length === 0 || goals.length === 0} onClick={() => openConnect()} type="button"><Plus size={16} />Connect Lark App</button>
          </div>
          <div className="personal-lark-table" role="table" aria-label="Lark Goal Topic connections">
            <div className="personal-lark-table-head" role="row"><span>Connection</span><span>Goal</span><span>Trigger</span><span>Reply mode</span><span>Actions</span></div>
            {filteredConnections.map((connection) => (
              <div className="personal-lark-table-row" key={connection.goal_id} role="row">
                <span>
                  <strong>{connection.chat_name}</strong>
                  <small>{connection.app_label} · {larkConnectionHealth(connection).label}</small>
                  <small>{larkConnectionHealth(connection).detail}</small>
                  {connection.health_error_code === "lark_event_delivery_unverified" ? (
                    <a href="https://open.feishu.cn/document/server-docs/im-v1/message/events/receive?lang=zh-CN" rel="noreferrer" target="_blank"><ExternalLink size={12} />查看飞书事件配置</a>
                  ) : null}
                </span>
                <span><strong>{connection.goal_title}</strong><small># {connection.topic_name}</small></span>
                <span>{connection.incoming_mode === "mentions" ? "Mentions" : "All messages"}</span>
                <span>Topic reply</span>
                <span className="personal-lark-row-actions">
                  <button aria-label={`配置 ${connection.goal_title}`} onClick={() => openConnectionEditor(connection)} type="button"><Settings2 size={15} /></button>
                  <button aria-label={`解绑 ${connection.goal_title}`} className={disconnectGoalId === connection.goal_id ? "is-confirm" : ""} onClick={() => void disconnect(connection.goal_id)} type="button"><Unlink size={15} />{disconnectGoalId === connection.goal_id ? "确认" : null}</button>
                </span>
              </div>
            ))}
            {filteredConnections.length === 0 ? <p className="personal-lark-empty">暂无匹配的连接。</p> : null}
          </div>
        </div>
      ) : null}

      {modalOpen ? (
        <div className="personal-lark-modal-backdrop" role="presentation">
          <section aria-labelledby="connect-lark-title" aria-modal="true" className="personal-lark-modal" role="dialog">
            <header><div><small>Goal Topic connection</small><h2 id="connect-lark-title">{editingGoalId ? "Edit Lark Connection" : "Connect Lark App"}</h2></div><button aria-label="关闭连接弹窗" onClick={() => setModalOpen(false)} type="button"><X size={18} /></button></header>
            <label><span>Lark App</span><select aria-label="Lark App" disabled={loading} onChange={(event) => { if (event.target.value === "__register__") openSetup(); else setAppRef(event.target.value); }} value={appRef}>{loading ? <option value="">正在加载可用的 Lark Apps…</option> : <>{apps.map((app) => <option disabled={!app.ready} key={app.app_ref} value={app.app_ref}>{app.label}{app.reply_ready ? "" : app.ready ? " · Needs message permissions" : " · Needs setup"}</option>)}<option value="__register__">＋ Register another Lark App — Create through Feishu</option></>}</select></label>
            {selectedApp?.ready && !selectedApp.reply_ready ? <div className="personal-lark-group-state is-error" role="alert">该 App 能发送建联消息，但缺少接收群聊 @ 消息或自动回复所需的机器人权限。请开启 <code>im:message.group_at_msg:readonly</code>、<code>im:message.send_as_bot</code> 和事件 <code>im.message.receive_v1</code>，发布新版后刷新。</div> : null}
            <label>
              <span>Group chat</span>
              <input aria-label="搜索飞书群" onChange={(event) => setChatQuery(event.target.value)} placeholder="搜索该机器人已加入的群" type="search" value={chatQuery} />
              {chatLoading ? <div className="personal-lark-group-state" role="status"><Loader2 className="is-spinning" size={15} />正在读取该机器人已加入的群…</div> : null}
              {!chatLoading && chatLoadError ? <div className="personal-lark-group-state is-error" role="alert">{chatLoadError}</div> : null}
              {!chatLoading && !chatLoadError && chats.length === 0 ? <div className="personal-lark-group-state" role="status">该机器人尚未加入可连接的群。请先在飞书群设置中添加这个机器人，再回来刷新或搜索。</div> : null}
              {!chatLoading && !chatLoadError && chats.length > 0 ? <select aria-label="Group chat" onChange={(event) => setChatId(event.target.value)} value={chatId}>{chats.map((chat) => <option key={chat.chat_id} value={chat.chat_id}>{chat.chat_name}</option>)}</select> : null}
            </label>
            <label><span>Bind to Goal</span><select aria-label="Bind to Goal" onChange={(event) => setGoalId(event.target.value)} value={goalId}>{goals.map((goal) => <option key={goal.goalId} value={goal.goalId}>{goal.title}</option>)}</select></label>
            <label className="personal-lark-check"><input checked readOnly type="checkbox" /><span><strong>Create Goal topic automatically</strong><small>A dedicated topic will be created for this Goal.</small></span></label>
            <label><span>Topic preview</span><div className="personal-lark-topic-preview"><MessageSquareText size={15} /># {selectedGoal?.title ?? selectedGoal?.goalId ?? "Goal"}</div></label>
            <label><span>Incoming messages</span><select aria-label="Incoming messages" onChange={(event) => setIncomingMode(event.target.value as "mentions" | "all")} value={incomingMode}><option value="mentions">Someone mentions the Agent</option><option value="all">All messages in this topic</option></select></label>
            <label><span>Reply mode</span><div className="personal-lark-topic-preview is-locked"><Link2 size={15} />Topic reply</div></label>
            <p className="personal-lark-cardinality"><Check size={15} />One Lark App · many Goals · one topic per Goal</p>
            {connectError ? <p className="personal-notification-error">{connectError}</p> : null}
            <footer><button className="personal-secondary-action" onClick={() => setModalOpen(false)} type="button">Cancel</button><button className="personal-primary-action" disabled={loading || !appRef || !selectedApp?.reply_ready || !goalId || !chatId || connecting} onClick={() => void connect()} type="button">{connecting ? <Loader2 className="is-spinning" size={15} /> : null}{editingGoalId ? "Save connection" : "Connect"}</button></footer>
          </section>
        </div>
      ) : null}

      {setupOpen ? (
        <div className="personal-lark-modal-backdrop is-setup" role="presentation">
          <section aria-labelledby="new-lark-app-title" aria-modal="true" className="personal-lark-modal personal-lark-setup-modal" role="dialog">
            <header><div><small>Reusable workspace App</small><h2 id="new-lark-app-title">New Lark App</h2></div><button aria-label="关闭创建弹窗" onClick={() => void closeSetup()} type="button"><X size={18} /></button></header>
            {!setupSnapshot ? (
              <>
                <p className="personal-lark-setup-copy">LoopX 将通过 lark-cli 打开飞书官方创建页面。应用凭证保存在系统 Keychain，LoopX 只保留 profile 引用。</p>
                <label><span>Profile name</span><input aria-label="Profile name" autoComplete="off" onChange={(event) => setSetupAppRef(event.target.value)} placeholder="loopx-workspace-bot" value={setupAppRef} /></label>
                <label><span>Region</span><select aria-label="Region" onChange={(event) => setSetupBrand(event.target.value as "feishu" | "lark")} value={setupBrand}><option value="feishu">Feishu</option><option value="lark">Lark</option></select></label>
                {setupAppRef && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(setupAppRef) ? <p className="personal-notification-error">Profile 只能包含字母、数字、点、下划线和连字符。</p> : null}
              </>
            ) : (
              <div className="personal-lark-setup-progress">
                <span className={`personal-lark-setup-icon is-${setupSnapshot.status}`}>{setupSnapshot.status === "ready" ? <Check size={22} /> : <Loader2 className={setupSnapshot.status === "failed" ? "" : "is-spinning"} size={22} />}</span>
                <div><strong>{setupSnapshot.status === "ready" ? "App 已创建" : setupSnapshot.status === "failed" ? "创建失败" : "等待飞书完成创建"}</strong><p>{setupSnapshot.status === "waiting_for_feishu" ? "请在新窗口中完成飞书授权，完成后会自动回到这里。" : setupSnapshot.status === "starting" ? "正在生成飞书官方创建链接…" : setupSnapshot.error}</p></div>
                {setupSnapshot.verification_url ? <a href={setupSnapshot.verification_url} rel="noreferrer" target="_blank"><ExternalLink size={15} />重新打开飞书</a> : null}
              </div>
            )}
            {setupError ? <p className="personal-notification-error">{setupError}</p> : null}
            <footer><button className="personal-secondary-action" onClick={() => void closeSetup()} type="button">Cancel</button>{!setupSnapshot ? <button className="personal-primary-action" disabled={setupStarting || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(setupAppRef)} onClick={() => void startSetup()} type="button">{setupStarting ? <Loader2 className="is-spinning" size={15} /> : <ExternalLink size={15} />}Continue in Feishu</button> : null}</footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}
