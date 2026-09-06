const panel = document.querySelector("main");
const status = document.querySelector("#status");
window.loopxBootFailed = (message) => {
  panel.dataset.state = "error";
  panel.setAttribute("aria-busy", "false");
  status.textContent = message;
};
window.loopxBootRetrying = () => {
  panel.dataset.state = "loading";
  panel.setAttribute("aria-busy", "true");
  status.textContent = "正在重新连接本地控制面…";
};
const update = document.querySelector("#update");
const channel = document.querySelector("#channel");
const repair = document.querySelector("#repair");
const rollback = document.querySelector("#rollback");
const updateStatus = document.querySelector("#update-status");
let nextAction = "check";
let working = false;
document.querySelector("#retry").onclick = () => location.reload();
channel.onchange = () => { nextAction = "check"; update.textContent = "检查更新 / Check for updates"; };
const labels = {
  runtime_required: "本机组件与 App 版本尚未对齐。可检查 App 更新，或点击修复安装当前匹配组件。",
  checking: "正在检查更新…",
  available: "App 与匹配运行时可一起更新。",
  up_to_date: "当前通道暂无更新。",
  downloading: "正在下载并校验签名…",
  installing_app: "正在安装 App，请保持窗口打开。",
  installing_runtime: "正在安装匹配的运行时，请稍候…",
  connecting: "正在连接更新后的服务…",
  restart_required: "请重启 App，继续完成更新。",
  ready: "更新完成，正在打开工作区。",
  error: "更新未完成。请重试检查，或修复当前版本。Goal 数据不会被删除。",
};
function render(state) {
  if (!state?.phase) return;
  working = ["checking","downloading","installing_app","installing_runtime","connecting"].includes(state.phase);
  update.disabled = working;
  repair.disabled = working || state.phase === "restart_required";
  rollback.disabled = working || state.phase === "restart_required";
  channel.disabled = working || state.phase === "restart_required";
  nextAction = state.phase === "available" ? "apply" : state.phase === "restart_required" ? "restart" : "check";
  update.textContent = nextAction === "apply" ? "更新并准备重启 / Install update" : nextAction === "restart" ? "重启完成更新 / Restart" : "检查更新 / Check for updates";
  updateStatus.textContent = labels[state.phase] || "";
}
async function run(action) {
  if (working) return;
  render({phase: action === "check" ? "checking" : action === "repair" ? "installing_runtime" : "downloading"});
  try { render(await window.__TAURI__.core.invoke("desktop_update", {action,channel:channel.value})); }
  catch { render({phase:"error"}); }
}
update.onclick = () => run(nextAction);
repair.onclick = () => run("repair");
rollback.onclick = () => run("rollback");
async function refresh() {
  if (!window.__TAURI__) return;
  try {
    const result = await window.__TAURI__.core.invoke("desktop_update_status");
    rollback.hidden = !result.rollback_available;
    render(result.state);
  } catch { /* Static recovery instructions remain usable. */ }
}
void refresh();
setInterval(refresh,1000);
