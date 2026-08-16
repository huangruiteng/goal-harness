import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (name) => readFileSync(new URL(name, import.meta.url), "utf8");
const model = source("./personal-workspace-model.ts");
const drawer = source("./context-drawer.tsx");
const header = source("./channel-header.tsx");
const sidebar = source("./goal-sidebar.tsx");
const page = source("./personal-workspace-page.tsx");
const router = source("./personal-workspace-router.ts");
const shell = source("./workspace-shell.tsx");
const timeline = source("./channel-timeline.tsx");
const runRow = source("./cards/run-row.tsx");
const larkSettings = source("./lark-settings-page.tsx");
const styles = source("./personal-workspace.css");
const dashboard = source("../../views/dashboard-page.tsx");
const tasks = source("./goal-tasks-view.tsx");
const status = source("../../data/status.ts");

assert.match(model, /kind: "todo"/, "Todo has its own drawer selection");
for (const field of ["dependencies", "nextTransition", "ownerLabel", "todoId", "taskClass"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Todo exposes ${field}`);
}
assert.match(drawer, /actionKind: "todo\.update"/, "Todo mutations use typed previews");
for (const operation of ["reassign", "block", "defer"]) {
  assert.match(drawer, new RegExp(`operation:\\s*"${operation}"`), `Todo supports ${operation}`);
}
assert.match(drawer, /previewTodoTransition\(selection\.item, "complete"/, "Todo complete is the primary drawer action");
assert.match(drawer, /actionKind: "todo\.create"/, "Todo successor uses the canonical create action");

for (const field of ["evidence", "explanation"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Decision exposes ${field}`);
}
for (const decision of ["reject", "defer"]) {
  assert.match(drawer, new RegExp(`resolution:\\s*"${decision}"`), `Decision previews ${decision}`);
}
assert.match(drawer, /previewDecision\(selection\.item, "approve"/, "Decision approval uses a typed preview");

for (const callback of ["onRetryResumeRun", "onStartNewRunSession", "onCloseRunSession"]) {
  assert.match(model, new RegExp(`${callback}\\??:`), `Run exposes ${callback}`);
  assert.match(drawer, new RegExp(`callbacks\\.${callback}`), `Run menu calls ${callback}`);
}
assert.match(drawer, /resume_failed/, "Run recovery presents resume failure explicitly");
assert.match(drawer, /personal-run-more/, "Run secondary actions live in a compact menu");
assert.match(page, /item\.run\.runId === selection\.item\.runId/, "Run drawer refresh keeps the selected run identity");
assert.match(model, /todoId\??:/, "An execution Run keeps its Task identity");
assert.match(tasks, /查看执行过程/, "A running Task exposes a plain-language execution entry");
assert.match(runRow, /查看执行过程与结果/, "Run rows expose one explicit entry for both progress and returned results");
assert.match(drawer, /Execution Session[\s\S]*查看最近执行过程[\s\S]*尚未启动执行 Session/, "Every Goal detail exposes a stable execution entry or explicit empty state");
assert.doesNotMatch(drawer, /agentLabel\} · \{selection\.item\.status\}/, "Run details do not expose raw status codes in the heading");
assert.match(page, /activeSessionRun/, "Opening a Session preserves the selected run in Goal state");
assert.match(page, /personal-session-record/, "Goal chat visibly identifies the loaded Session record");
assert.match(header, /personal-goal-tabs/, "Goal Chat, Tasks, and Files stay one click away in the header");
for (const view of ["Chat", "Tasks", "Files"]) {
  assert.match(header, new RegExp(`\"${view.toLowerCase()}\"|>${view}<`), `Goal header exposes ${view}`);
}
assert.match(model, /onOpenGoalView\??:/, "Goal detail can switch the center workspace view");
for (const label of ["执行中", "已安排", "等待条件", "可继续"]) {
  assert.match(model + drawer + page, new RegExp(label), `Session and Run status language includes ${label}`);
}
assert.match(dashboard, /actionKind:\s*"run\.correct"/, "Run correction uses the scoped typed action");
assert.doesNotMatch(
  dashboard,
  /onCorrectRun:[\s\S]{0,240}sendManagerQuestion/,
  "Run correction does not fall back to the read-only manager Chat",
);
assert.match(page, /routeWorkspaceInput\(message,/, "Every free-text send enters the unified Router contract");
assert.match(router, /route: "projection" \| "typed_action" \| "agent_chat" \| "clarify"/, "Router exposes the constrained route contract");
assert.match(router, /function executionIntent/, "Execution intent stays inside the Router implementation");
assert.match(router, /function negates/, "Router can honor explicit negation");
for (const legacyClassifier of ["hasHeartbeatIntent", "hasMonitorIntent", "hasTodoCreationIntent", "isExecutionIntent"]) {
  assert.doesNotMatch(page, new RegExp(`function ${legacyClassifier}`), `${legacyClassifier} no longer bypasses the Router contract`);
}
assert.match(dashboard, /Agent 已返回结果/, "A completed task Session advertises its result instead of looking stalled");
assert.match(dashboard, /sessionStatus: hasResult \? "completed"/, "A returned answer outranks a stale transport label in the visible Session status");
assert.match(dashboard, /function visibleAgentMessage[\s\S]*GOAL_\(STATUS\|PROGRESS\)/, "Internal Session protocol markers stay out of the user-facing result");
assert.match(dashboard, /GOAL_EVIDENCE[\s\S]*验证依据：/, "Session evidence uses a readable heading instead of an internal protocol marker");
assert.match(dashboard, /NEXT_ACTION[\s\S]*下一步：/, "Session next actions use a readable heading instead of an internal protocol marker");
assert.match(tasks, /查看结果/, "Tasks expose a direct result entry when a Session has answered");
assert.match(tasks, /待执行 \/ 进行中/, "Tasks do not imply that every uncompleted Todo already has an active Run");
assert.match(tasks, /最近对话与 Task 状态/, "Tasks surface the latest Goal conversation without forcing a tab switch");
assert.match(tasks, /本次对话没有直接修改 Tasks/, "Tasks explain that ordinary Chat does not silently mutate Todo state");
assert.match(tasks, /转为 Task/, "Tasks offer an explicit preview-first bridge from a reply to task management");
assert.match(page, /function todoTextFromMessage[\s\S]*标题[\s\S]*内容/, "Todo parsing preserves structured title and content fields");
assert.match(page, /个 Task/, "Home cards expose durable activity when a new Goal has Todos but no run timestamp yet");
assert.match(page, /创建 Goal 并开始首轮/, "Goal creation names the immediate first-turn effect");
assert.match(router, /const asksForMutation/, "Execution routing remains explicit inside the Router contract");
assert.match(timeline, /待你确认/, "Historical gated proposals are grouped into a compact summary");
assert.match(timeline, /gatedItems\.length/, "The compact Gate summary exposes the pending count");
assert.match(page, /Boolean\(item\.run\.sessionId\)/, "Running count requires a discovered execution Session");
assert.match(page, /Boolean\(item\.run\.canInterrupt\)/, "Running count requires an active interruptible turn");
assert.match(page, /accept="image\/png,image\/jpeg,image\/webp,image\/gif"/, "Composer accepts bounded image types");
assert.match(page, /imageInputRef\.current\?\.click\(\)/, "Attachment button explicitly opens the native file chooser");
assert.match(page, /onDrop=\{\(event\)/, "Composer accepts dragged image files");
assert.match(page, /onPaste=\{[^}]*handleComposerPaste/s, "Composer accepts pasted clipboard images");
assert.match(page, /clipboardData\.items/, "Pasted images use the browser clipboard file payload");
assert.match(page, /maxImageAttachmentCount = 4/, "Composer limits image count");
assert.match(page, /maxImageAttachmentBytes = 5 \* 1024 \* 1024/, "Composer limits image size");
assert.match(timeline, /personal-message-images/, "Sent images remain visible in the conversation");
assert.match(dashboard, /attachments: route\?\.attachments/, "Image attachments enter the selected Agent Session");
assert.match(page, /sendMessage\("请给我一份当前 Goal 的进度报告/, "Progress report shortcut sends a scoped read-only request immediately");
assert.match(page, />向 Agent 获取进度报告</, "Progress report shortcut makes its immediate-send behavior explicit");
assert.match(page, /aria-label="将“我现在该做什么”填入编辑框"[\s\S]*title="填入编辑框，确认后再发送"/, "Advice shortcut explains that it only prepares a draft");
assert.match(page, /aria-label="配置定时检查"[\s\S]*title="先填写检查内容、频率和停止条件，不会立即创建"/, "Monitor shortcut explains its editable-draft boundary");
assert.match(page, /goalDraftActive[\s\S]*Goal 草稿[\s\S]*检查并创建 Goal/, "Create Goal mode is visibly distinct from a normal chat draft");
assert.match(page, /setComposerDraft\(`manager:\$\{selectedAgentId\}`,[\s\S]*我想创建一个长期 Goal/, "Create Goal writes the template to the manager draft even when invoked from a Goal");
assert.match(page, /personal-action-feedback/, "Typed actions surface a persistent visible receipt");
assert.match(page, /visibleTimelineItems[\s\S]*item\.run\.runId === activeSessionRun\.runId/, "Session record mode filters unrelated Goal activity");
assert.match(page, /if \(tab === "chat"\) setActiveSessionRun\(null\)/, "The top Chat view exits the nested Session record filter");
assert.match(header, /刷新中[\s\S]*刚刚更新[\s\S]*刷新失败/, "Refresh exposes loading, success, and failure feedback");
assert.match(drawer, /确认后，LoopX 会执行这项变更并显示写入结果/, "Preview explains what confirmation will do");
assert.match(drawer, /应用失败，没有写入任何变更/, "Failed preview communicates its no-write result clearly");
assert.match(drawer, /onClick=\{onClose\} type="button">关闭/, "Closing a proposal is a pure UI action with zero state transition");
assert.match(drawer, /已复制仓库标识[\s\S]*已复制，可粘贴到其他工具/, "Repository copy action exposes a visible receipt");
assert.doesNotMatch(drawer, />打开 Goal</, "Goal details do not repeat navigation to the already-open Goal");
assert.match(page, /function prepareScheduleDraft[\s\S]*Goal：[\s\S]*检查内容：[\s\S]*频率：每 2 小时[\s\S]*停止条件：Goal 完成/, "Manager monitor action opens a complete editable configuration draft");
assert.match(page, /function prepareScheduleDraft[\s\S]*频率：每天[\s\S]*通知：仅在需要我时/, "Goal heartbeat action opens an editable configuration draft before preview");
assert.match(page, /function structuredGoalIntentFromMessage/, "Goal creation parses the visible form as structured fields");
assert.match(page, /执行边界（可选）：/, "Goal creation asks for an explicit execution boundary");
assert.match(page, /不支持精确到星期或时刻的日历计划/, "Unsupported calendar schedules fail closed before preview");
assert.match(page, /function monitorTargetFromMessage/, "Monitor creation preserves the user's requested check target");
assert.match(page, /onOpenGoal: async \(goalId\)[\s\S]*await callbacks\.onRefresh\?\.\(\);[\s\S]*selectGoal\(goalId\)/, "A created Goal refreshes before navigation");
assert.match(page, /activityTimeLabel\(item\.output\.createdAt\)/, "Files render human-readable output timestamps");
assert.match(drawer, /selection\.kind === "run" \|\| selection\.kind === "proposal" \|\| selection\.kind === "schedule"/, "Advanced diagnostics only appears on objects with actionable runtime details");

for (const field of ["agentId", "todoId", "runId", "safePreview"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Output exposes ${field}`);
}
assert.match(model, /onExportOutput\??:/, "Output exposes export callback");
assert.match(drawer, /personal-safe-preview/, "Output drawer renders a safe preview");

for (const field of ["timezone", "nextRunAt", "previousRunAt", "notificationRule", "stopCondition", "executionHistory"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Schedule exposes ${field}`);
}
assert.match(drawer, /personal-execution-history/, "Schedule drawer renders execution history");
assert.match(page, /const heartbeat = schedule\.scheduleKind === "heartbeat"/, "Schedule distinguishes heartbeat lifecycle type");
assert.match(page, /actionKind: heartbeat \? "heartbeat\.bind" : "monitor\.update"/, "Schedule previews preserve heartbeat lifecycle type");

assert.match(drawer, /event\.key === "Tab"/, "Drawer traps keyboard focus");
assert.match(shell, /event\.key !== "Tab"/, "Mobile Goal navigation traps keyboard focus");
assert.match(shell, /restoreFocusRef\.current\?\.focus\(\)/, "Mobile Goal navigation restores focus on close");
assert.match(shell, /aria-modal=\{mobileSidebarOpen \? true : undefined\}/, "Mobile Goal navigation exposes modal semantics");
assert.match(shell, /inert=\{mobileSidebarOpen \|\| undefined\}/, "Mobile Goal navigation removes background content from keyboard navigation");
assert.doesNotMatch(timeline, /<div aria-live="polite" className="personal-channel-timeline">/, "The full timeline is not a live region");
assert.match(timeline, /className="personal-live-region"/, "Timeline has a dedicated live region");
assert.match(drawer, /aria-label=\{`输入纠偏信息：Goal/, "Correction label includes its scoped context");
assert.match(styles, /env\(safe-area-inset-bottom\)/, "Mobile composers respect the safe area");
assert.match(styles, /\.personal-mobile-back/, "Mobile drawer exposes a context back affordance");

assert.match(model, /repository\??:\s*WorkspaceRepositoryContext/, "Goal exposes one repository context");
assert.match(drawer, /Repository/, "Goal settings display the repository");
assert.match(drawer, /Read only/, "Repository is visibly read-only");
assert.doesNotMatch(drawer, /Add repository/, "Goal settings do not imply repository binding controls");

for (const lane of ["needs_you", "running", "observing", "scheduled", "history"]) {
  assert.match(model, new RegExp(`"${lane}"`), `Manager home models the ${lane} lane`);
}
assert.match(model, /function workspaceHomeLaneForGoal/, "Manager lane projection is centralized and testable");
assert.match(model, /goal\.state === "推进中" \|\| goal\.state === "需修复"/, "Agent-owned repair work stays in the running lane");
for (const label of ["需要你", "执行中", "观察中", "已安排", "历史"]) {
  assert.match(page, new RegExp(label), `Manager home renders ${label}`);
}
assert.match(page, /personal-home-board/, "Manager home uses the four-lane workspace board");
assert.doesNotMatch(page, /personal-worker-strip/, "Manager home omits the redundant Agent worker strip");
assert.match(header, /切换到野兽主题[\s\S]*切换到默认主题/, "Header exposes an explicit theme switch");
assert.match(page, /loopx-pw-theme/, "Theme preference persists across reloads");
assert.match(dashboard, /function isManagerProjectionQuestion[\s\S]*我现在该做什么[\s\S]*哪些 Goal 在等我[\s\S]*Agent 在做什么/, "Manager projection questions use stable intent phrases instead of exact button copy");
assert.match(dashboard, /targetContextId === "manager" && isManagerProjectionQuestion\(question\)/, "Manager projection questions remain on the cross-Goal manager route when the user adds a read-only boundary");
assert.match(dashboard, /const asksForNextAction[\s\S]*if \(asksForNextAction\)[\s\S]*personalManagerMatches\(question, \["状态"/, "A next-step question outranks a read-only boundary that mentions state");
assert.match(dashboard, /先处理「\$\{personalGoalTitle\(nextTodo\.goalId\)\}」：\$\{nextTodo\.text\}/, "The compact manager answer names the Goal and concrete blocking action");
assert.match(drawer, /查看影响并决定/, "Blocked items preview their decision boundary before any write");
assert.match(drawer, /const hasProjectedRunActivity = selection\.kind === "run"[\s\S]*selection\.item\.completedSteps > 0/, "Session empty-state copy distinguishes projected progress from a truly idle run");
assert.match(drawer, /当前没有可展示的逐步运行记录/, "A projected run does not claim that the Agent never started");
assert.match(drawer, /还没有运行记录。Agent 尚未开始这次执行/, "A truly empty Session still explains why there is no timeline yet");
assert.match(page, /function ManagerConversationTray/, "Manager home has a dedicated conversation tray instead of burying replies in the board timeline");
assert.match(page, /managerMessages/, "Manager conversation is derived from the active manager message context");
assert.match(page, /managerConversationReceiptVisible/, "Manager conversation is a send-triggered receipt instead of permanent history chrome");
assert.match(page, /setManagerConversationReceiptVisible\(true\)/, "A new manager send reveals the temporary conversation receipt");
assert.match(page, /setManagerConversationReceiptVisible\(false\)/, "Opening or leaving the receipt clears it from the overview");
assert.match(page, /personal-manager-conversation-tray/, "Manager conversation stays anchored beside the composer");
assert.match(page, /aria-live="polite"/, "Manager conversation announces streamed replies without moving focus");
assert.match(page, />查看完整对话</, "The compact manager conversation can expand in place");
assert.match(page, /onOpenConversation/, "The compact manager conversation has a dedicated full-chat navigation action");
assert.match(page, /managerChatOpen/, "Manager full conversation uses a dedicated Chat view instead of stretching the home tray");
assert.match(page, /managerChatItems/, "Manager Chat only renders conversation and confirmation items");
assert.match(page, /sessionProposalIds\.includes\(item\.proposal\.previewId\)/, "Manager Chat only shows proposals created in the current UI session");
assert.match(page, /\["ready", "gated", "deferred", "applying"\]\.includes\(proposal\.status\)/, "Restored proposal history excludes stale and failed write cards from the active Chat");
assert.doesNotMatch(page, /proposal\.title, proposal\.status/, "Proposal dedupe does not split one action into duplicate cards by lifecycle status");
assert.match(header, /管家视图/, "Manager Chat exposes explicit overview and Chat navigation");
assert.match(header, />总览</, "Manager Chat can return to the cross-Goal overview");
assert.match(page, /scrollTo\(\{ behavior: "smooth", top: 0 \}\)/, "Returning to the manager overview restores the board's first screen");
assert.match(header, /onOpenManagerChat/, "Manager overview exposes a stable one-click Chat entry");
assert.match(header, /aria-current=\{!managerChatOpen \? "page"/, "Manager overview remains visibly selected before Chat opens");
assert.match(header, /aria-current=\{managerChatOpen \? "page"/, "Manager Chat remains visibly selected after navigation");
assert.doesNotMatch(sidebar, /personal-manager-channels/, "The sidebar does not expose manager state filters as navigation channels");
assert.doesNotMatch(sidebar, /onSelectChannel/, "The sidebar only navigates to the manager or a concrete Goal");
assert.doesNotMatch(page, /selectedChannel|selectChannel\(|__manager_channel__/, "Manager state lanes do not create hidden conversation channels");
assert.match(page, /personal-digest-stats[\s\S]*<span><b>\{digest\.done\}<\/b>完成<\/span>/, "The away digest is a non-interactive summary");
assert.match(page, /!selectedGoal && !managerChatOpen && managerConversationReceiptVisible[\s\S]*<ManagerConversationTray/, "The tray only appears on the manager overview after a send");
assert.match(page, /goal\.needsYou \?\? goal\.nextSentence/, "Needs-you cards keep the source Goal action visible");
assert.match(page, /onClick=\{\(\) => onSelectGoal\(goal\.goalId\)\}/, "Manager cards open their source Goal instead of a hidden lane channel");
assert.doesNotMatch(page, /managerConversationActive/, "Sending from the manager never replaces the overview with a separate conversation page");
assert.match(model, /export type WorkspaceSessionMessage/, "Workspace runs expose Session messages for the execution record");
assert.match(model, /sessionMessages\?: WorkspaceSessionMessage\[\]/, "Workspace runs carry Session messages into the control plane");
assert.match(drawer, /执行过程与结果/, "The Session drawer names its primary record view in user language");
assert.match(drawer, /详情与操作/, "The Session drawer separates metadata and correction controls");
assert.match(drawer, /runDrawerTab/, "The Session drawer keeps an explicit record/details tab state");
assert.match(drawer, /selection\.item\.sessionMessages/, "The Session drawer renders the selected run's real message record");
assert.match(drawer, /收到任务/, "The execution record labels the initiating user request");
assert.match(drawer, /已完成/, "The execution record labels completed Agent output");
assert.match(runRow, /查看执行过程与结果/, "Each run row exposes an explicit execution record action");
assert.match(page, /item\.output\.summary \?\? item\.output\.safePreview/, "Files surfaces explain what each output contains");
assert.match(dashboard, /executionSessionSnapshots/, "The dashboard preserves polled Session snapshots for the drawer");
assert.match(dashboard, /const sessionId = run\.sessionId;[\s\S]*setExecutionSessionSnapshots\(\(current\) => \(\{[\s\S]*?\[sessionId\]: snapshot/s, "Opening a Session promotes the fetched snapshot into the authoritative execution projection");
assert.match(dashboard, /\["agent", "assistant"\]\.includes\(role\.trim\(\)\.toLowerCase\(\)\)/, "LoopX agent-store replies and provider assistant replies both count as Session results");
assert.match(page, /latestRun[\s\S]*activeSessionRun[\s\S]*setActiveSessionRun\(latestRun\.run\)/s, "An open Session drawer follows the latest projected run instead of freezing its opening state");
assert.match(page, /<details className="personal-home-history"/, "Completed work is collapsed into history");
assert.match(page, /function activityTimeLabel/, "Manager cards format raw ISO activity time for people");
assert.doesNotMatch(page, />接下来</, "The ambiguous 接下来 lane is not rendered");
assert.match(page, /managerNeedsYouCount[\s\S]*workspaceHomeLaneForGoal\(goal\) === "needs_you"/, "Manager greeting derives attention from the same lane projection");
assert.doesNotMatch(page, /activeRunCount=\{managerRunningCount\}/, "The sidebar no longer duplicates the running lane count");
assert.match(page, /你有 \{managerNeedsYouCount\} 项需要处理/, "Manager greeting shows the projected needs-you count");
assert.match(dashboard, /targetContextId === "manager"\s*\? model\s*:\s*targetGoal/, "Manager answers use the full cross-Goal projection");
assert.match(page, /managerBlockingCount[\s\S]*goal\.needsYouBlocking \|\| goal\.state === "等你"/, "Manager blocking count includes projected user waits without a parsed Todo");
assert.match(page, /其中 \{managerBlockingCount\} 项正在阻塞 Agent/, "Manager greeting shows the projected blocking count");
assert.match(dashboard, /function personalGoalState[\s\S]*hasOpenUserTodo[\s\S]*if \(\["user_or_controller", "controller"\][\s\S]*if \(personalGoalNeedsRepair/, "User gates outrank agent-owned health repair in Goal state projection");
assert.match(dashboard, /if \(goal\.registry_member === false\)[\s\S]*return \[\]/, "Unregistered historical Goals are excluded from the interactive workspace");
assert.match(status, /runGoalSchema[\s\S]*display_name:\s*z\.string\(\)/, "Run history preserves the registered Goal display name");
assert.match(dashboard, /title:\s*personalGoalTitle\(goal\.id,\s*goal\.display_name\)/, "Personal workspace prefers the registered Goal display name");
assert.match(dashboard, /function personalGoalHasPendingOperatorGate/, "Pending operator gates have a durable state projection helper");
assert.match(dashboard, /personalGoalHasPendingOperatorGate\(row\)/, "Pending operator gates project into the needs-you state");
assert.match(dashboard, /explicitUserWait/, "Explicit user-approval language repairs incomplete gate projections");
assert.match(page, /proposal\.status === "applied"/, "Unconfirmed Heartbeat previews never project as active schedules");
assert.match(drawer, /actionKind === "goal\.create" \? "进入新 Goal" : "查看更新后的 Goal"/, "Applied actions offer scoped refreshed navigation labels");
assert.doesNotMatch(sidebar, /Agent 设置/, "The sidebar omits the read-only Agent settings dead end");
assert.doesNotMatch(sidebar, /野兽主题|默认主题/, "The sidebar keeps one owner-reviewed visual theme");
assert.match(page, /我想创建一个长期 Goal：[\s\S]*完成标准：[\s\S]*关联仓库（可选）：[\s\S]*通知方式（可选）：/, "Create Goal starts with a useful objective form instead of a host gate");
assert.match(page, /workspace_ref:\s*"current"/, "Create Goal does not leak another Goal id as its execution workspace");
assert.match(page, /当前本地工作区（未绑定 Repository）/, "Create Goal explains that its execution workspace does not bind a repository");
assert.doesNotMatch(model, /kind: "agent"/, "The drawer model omits the read-only Agent settings variant");
assert.match(dashboard, /statusRequestActive = Boolean\(activeStatusRequestUrl\) && search\.view === "ops"/, "Initial load and refresh keep the personal workspace shell visible");

assert.match(page, /notificationSettingsOpen\s*\?\s*\(/, "Notification settings replace the center workspace");
assert.match(page, /<LarkSettingsPage/, "Pure configuration mode renders the Lark management page");
assert.match(larkSettings, /Lark Apps/, "Lark management exposes reusable Apps");
assert.match(larkSettings, /Connections/, "Lark management exposes Goal Topic connections");
for (const label of ["Connect Lark App", "Group chat", "Bind to Goal", "Create Goal topic automatically", "Topic reply"]) {
  assert.match(larkSettings, new RegExp(label), `Connect flow contains ${label}`);
}
assert.match(larkSettings, /One Lark App · many Goals · one topic per Goal/, "Connection cardinality is explicit");
assert.match(larkSettings, /connectLarkGoalTopic\([^)]*execute:\s*false/s, "Connect flow previews before execution");
assert.match(larkSettings, /connectLarkGoalTopic\([^)]*execute:\s*true/s, "Connect flow performs the approved external write");
assert.match(larkSettings, /Register another Lark App/, "App chooser exposes Feishu registration");
assert.match(larkSettings, /startLarkAppSetup/, "Registration starts through the local setup API");
assert.match(larkSettings, /fetchLarkAppSetup/, "Registration polls the local setup session");
assert.match(larkSettings, /window\.open\(/, "Registration opens the provider flow from a user gesture");
assert.match(larkSettings, /window\.open\(window\.location\.href,\s*"_blank"\)/, "Registration never leaves a blank waiting tab");
assert.match(larkSettings, /setAppRef\(snapshot\.app_ref\)/, "Completed registration selects the new App");
assert.match(larkSettings, /loading \? "…" : apps\.length/, "Lark App count does not flash a false zero while loading");
assert.match(larkSettings, /openConnectionEditor\(connection\)/, "Every Lark connection settings button opens a scoped editor");
assert.match(larkSettings, /focusGoalConnection[\s\S]*openConnectionEditor\(connection\)[\s\S]*openConnect\(goals\.find/, "Goal-level Lark entry opens the scoped connection editor or create flow");

console.log("personal workspace drawer contract smoke passed");
