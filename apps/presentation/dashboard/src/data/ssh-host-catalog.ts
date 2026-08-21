export const defaultConfiguredSshHostsUrl = "http://127.0.0.1:8766/ssh-hosts";

export type ConfiguredSshHost = {
  alias: string;
};

export type ConfiguredSshHostCatalog = {
  hosts: ConfiguredSshHost[];
  schemaVersion: "ssh_host_catalog_v0";
};

const safeAliasPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/;

export function parseConfiguredSshHostCatalog(value: unknown): ConfiguredSshHostCatalog {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("SSH Host 列表响应无效。");
  }
  const payload = value as Record<string, unknown>;
  if (payload.ok !== true || payload.schema_version !== "ssh_host_catalog_v0" || !Array.isArray(payload.hosts)) {
    throw new Error("SSH Host 列表协议不兼容，请更新本机 LoopX 服务。");
  }
  const seen = new Set<string>();
  const hosts = payload.hosts.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const alias = String((value as Record<string, unknown>).alias ?? "").trim();
    if (!safeAliasPattern.test(alias) || seen.has(alias)) return [];
    seen.add(alias);
    return [{ alias }];
  });
  return { hosts, schemaVersion: "ssh_host_catalog_v0" };
}

export async function fetchConfiguredSshHosts(
  fetcher: typeof fetch = fetch,
  url = defaultConfiguredSshHostsUrl,
): Promise<ConfiguredSshHostCatalog> {
  const response = await fetcher(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`无法读取本机 SSH Host（HTTP ${response.status}）。`);
  return parseConfiguredSshHostCatalog(await response.json());
}

export function configuredSshTunnelDraft(hostAlias: string, localPortValue: string) {
  const alias = hostAlias.trim();
  if (!safeAliasPattern.test(alias)) return { error: "请选择有效的 SSH Host。" } as const;
  const localPort = Number(localPortValue);
  if (!Number.isInteger(localPort) || localPort < 1024 || localPort > 65535) {
    return { error: "本地端口必须是 1024–65535 之间的整数。" } as const;
  }
  return {
    command: `ssh -N -L ${localPort}:127.0.0.1:8766 ${alias}`,
    label: alias,
    statusUrl: `http://127.0.0.1:${localPort}/status.json`,
  } as const;
}
