import { ChevronDown, Copy, Plus, RotateCw, Server, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { StatusSource } from "../../data/status-source-catalog";
import {
  configuredSshTunnelDraft,
  fetchConfiguredSshHosts,
  type ConfiguredSshHost,
} from "../../data/ssh-host-catalog";

export type StatusSourceConnectionState = "connected" | "error" | "loading";

export type StatusSourceControl = {
  activeSource: StatusSource;
  connectionState: StatusSourceConnectionState;
  errorMessage?: string | null;
  onAdd: (input: { label: string; statusUrl: string }) => { error?: string };
  onRemove: (sourceId: string) => void;
  onSelect: (sourceId: string) => void;
  sources: StatusSource[];
};

export function StatusSourceSwitcher({
  activeSource,
  connectionState,
  errorMessage,
  onAdd,
  onRemove,
  onSelect,
  sources,
}: StatusSourceControl) {
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addMode, setAddMode] = useState<"configured" | "manual">("configured");
  const [configuredHosts, setConfiguredHosts] = useState<ConfiguredSshHost[]>([]);
  const [configuredHostsError, setConfiguredHostsError] = useState<string | null>(null);
  const [configuredHostsLoading, setConfiguredHostsLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [hostAlias, setHostAlias] = useState("");
  const [label, setLabel] = useState("");
  const [localPort, setLocalPort] = useState("8876");
  const [statusUrl, setStatusUrl] = useState("");
  const configuredDraft = useMemo(() => {
    if (!configuredHosts.some((host) => host.alias === hostAlias)) {
      return { error: "请选择已配置的 SSH Host。" } as const;
    }
    return configuredSshTunnelDraft(hostAlias, localPort);
  }, [configuredHosts, hostAlias, localPort]);

  async function loadConfiguredHosts() {
    setConfiguredHostsLoading(true);
    setConfiguredHostsError(null);
    try {
      const catalog = await fetchConfiguredSshHosts();
      setConfiguredHosts(catalog.hosts);
      setHostAlias((current) => current || catalog.hosts[0]?.alias || "");
      if (!catalog.hosts.length) setConfiguredHostsError("~/.ssh/config 中没有可直接选择的显式 Host。");
    } catch (caught) {
      setConfiguredHostsError(caught instanceof Error ? caught.message : "无法读取本机 SSH Host。");
    } finally {
      setConfiguredHostsLoading(false);
    }
  }

  function openForm() {
    setAdding(true);
    setAddMode("configured");
    setError(null);
    void loadConfiguredHosts();
  }

  function closeForm() {
    setAdding(false);
    setAddMode("configured");
    setConfiguredHostsError(null);
    setCopied(false);
    setHostAlias("");
    setError(null);
    setLabel("");
    setLocalPort("8876");
    setStatusUrl("");
  }

  function submitManual() {
    const result = onAdd({ label, statusUrl });
    if (result.error) {
      setError(result.error);
      return;
    }
    closeForm();
  }

  function submitConfigured() {
    if ("error" in configuredDraft) {
      setError(configuredDraft.error ?? "SSH 来源参数无效。");
      return;
    }
    const result = onAdd({ label: configuredDraft.label, statusUrl: configuredDraft.statusUrl });
    if (result.error) {
      setError(result.error);
      return;
    }
    closeForm();
  }

  async function copyTunnelCommand() {
    if ("error" in configuredDraft) {
      setError(configuredDraft.error ?? "SSH 来源参数无效。");
      return;
    }
    try {
      await navigator.clipboard.writeText(configuredDraft.command);
      setCopied(true);
      setError(null);
    } catch {
      setError("无法复制命令，请手动复制下方命令。");
    }
  }

  return (
    <section aria-label="控制面来源" className="personal-status-source">
      <header>
        <span>Control plane</span>
        <button aria-label="添加 SSH 隧道来源" onClick={openForm} title="添加来源" type="button"><Plus size={14} /></button>
      </header>
      <label className="personal-status-source-select">
        <Server size={15} />
        <select aria-label="选择控制面来源" onChange={(event) => onSelect(event.target.value)} value={activeSource.id}>
          {sources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
        </select>
        <ChevronDown aria-hidden size={13} />
      </label>
      <div className="personal-status-source-meta">
        <span className={`is-${connectionState}`}><i />{connectionState === "loading" ? "连接中" : connectionState === "error" ? "不可用" : "已连接"}</span>
        <small>{activeSource.readOnly ? "SSH 隧道 · 只读" : "本机交互"}</small>
        {activeSource.kind === "ssh_tunnel" ? (
          <button aria-label={`移除来源 ${activeSource.label}`} onClick={() => onRemove(activeSource.id)} title="移除当前来源" type="button"><Trash2 size={12} /></button>
        ) : null}
      </div>
      {errorMessage ? <p className="personal-status-source-error" role="alert">{errorMessage}</p> : null}
      {adding ? (
        <div className="personal-status-source-form">
          <header><strong>添加 SSH 来源</strong><button aria-label="关闭来源表单" onClick={closeForm} type="button"><X size={13} /></button></header>
          <div aria-label="来源添加方式" className="personal-status-source-modes" role="tablist">
            <button aria-selected={addMode === "configured"} onClick={() => { setAddMode("configured"); setError(null); }} role="tab" type="button">已配置 SSH</button>
            <button aria-selected={addMode === "manual"} onClick={() => { setAddMode("manual"); setError(null); }} role="tab" type="button">手动 URL</button>
          </div>
          {addMode === "configured" ? (
            <>
              <label>
                <span>本机 SSH Host · {configuredHosts.length} 个</span>
                <span className="personal-status-source-field-row">
                  <input aria-label="本机 SSH Host" disabled={configuredHostsLoading || !configuredHosts.length} list="loopx-configured-ssh-hosts" onChange={(event) => { setHostAlias(event.target.value); setCopied(false); }} placeholder={configuredHostsLoading ? "正在读取…" : "输入或搜索 Host"} value={hostAlias} />
                  <datalist id="loopx-configured-ssh-hosts">{configuredHosts.map((host) => <option key={host.alias} value={host.alias} />)}</datalist>
                  <button aria-label="重新读取 SSH Host" disabled={configuredHostsLoading} onClick={() => void loadConfiguredHosts()} title="重新读取" type="button"><RotateCw size={13} /></button>
                </span>
              </label>
              <label><span>本地端口</span><input aria-label="SSH 隧道本地端口" inputMode="numeric" onChange={(event) => { setLocalPort(event.target.value); setCopied(false); }} value={localPort} /></label>
              <div className="personal-status-source-command">
                <code>{"error" in configuredDraft ? "选择 Host 后生成隧道命令" : configuredDraft.command}</code>
                <button aria-label="复制 SSH 隧道命令" disabled={"error" in configuredDraft} onClick={() => void copyTunnelCommand()} type="button"><Copy size={12} />{copied ? "已复制" : "复制"}</button>
              </div>
              {configuredHostsError ? <p className="is-error">{configuredHostsError}</p> : null}
              <p>已读取全部显式 Host（含 Include）；通配规则不会作为具体来源。先运行命令，LoopX 不读取密钥或配置细节。</p>
              <button className="personal-status-source-add" disabled={"error" in configuredDraft} onClick={submitConfigured} type="button">添加只读来源</button>
            </>
          ) : (
            <>
              <label><span>名称</span><input autoFocus maxLength={48} onChange={(event) => setLabel(event.target.value)} placeholder="远程开发机" value={label} /></label>
              <label><span>本地转发 URL</span><input onChange={(event) => setStatusUrl(event.target.value)} placeholder="http://127.0.0.1:8876/status.json" value={statusUrl} /></label>
              <p><code>ssh -N -L 8876:127.0.0.1:8766 &lt;host&gt;</code></p>
              <p>远端来源始终按只读投影处理，不继承本机写权限。</p>
              <button className="personal-status-source-add" onClick={submitManual} type="button">添加只读来源</button>
            </>
          )}
          {error ? <p className="is-error" role="alert">{error}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
