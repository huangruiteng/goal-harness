import { useEffect, useId, useMemo, useState } from "react";
import { Check, RotateCcw, ServerCog, ShieldCheck } from "lucide-react";

import {
  applyMachineConfiguration,
  applyMachineConfigurationRollback,
  fetchMachineConfiguration,
  periodicReportMachineConfigurationSchema,
  previewMachineConfiguration,
  previewMachineConfigurationRollback,
  type MachineConfigurationInspection,
  type MachineConfigurationPreview,
  type MachineConfigurationRollbackPlan,
  type MachineConfigurationTransaction,
} from "../../data/chat";
import { useWorkspaceI18n } from "./i18n";

type PeriodicReportDraft = {
  enabled: boolean;
  profilePreset: string;
  routeRef: string;
  timezone: string;
};

const periodicReportNamespace = "periodic_report";

function localTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function emptyPeriodicReportDraft(): PeriodicReportDraft {
  return {
    enabled: false,
    profilePreset: "weekly-progress",
    routeRef: "",
    timezone: localTimezone(),
  };
}

function draftFromInspection(inspection: MachineConfigurationInspection): PeriodicReportDraft {
  const candidate = inspection.machine_configuration?.namespaces[periodicReportNamespace];
  const parsed = periodicReportMachineConfigurationSchema.safeParse(candidate);
  if (!parsed.success) return emptyPeriodicReportDraft();
  return {
    enabled: parsed.data.enabled,
    profilePreset: parsed.data.profile_preset ?? "weekly-progress",
    routeRef: parsed.data.route_ref ?? "",
    timezone: parsed.data.timezone,
  };
}

function configurationFromDraft(draft: PeriodicReportDraft): Record<string, unknown> {
  return {
    schema_version: "periodic_report_machine_defaults_v0",
    enabled: draft.enabled,
    inheritance: "materialize_on_goal_connect",
    profile_preset: draft.profilePreset.trim(),
    route_ref: draft.routeRef.trim(),
    timezone: draft.timezone.trim(),
  };
}

function shortRevision(value: string | undefined) {
  if (!value) return "—";
  if (value === "absent") return value;
  return value.replace(/^sha256:/, "").slice(0, 12);
}

export function MachineConfigurationSettings() {
  const { t } = useWorkspaceI18n();
  const enabledId = useId();
  const profileId = useId();
  const routeId = useId();
  const timezoneId = useId();
  const [inspection, setInspection] = useState<MachineConfigurationInspection | null>(null);
  const [draft, setDraft] = useState<PeriodicReportDraft>(emptyPeriodicReportDraft);
  const [selectedNamespace, setSelectedNamespace] = useState(periodicReportNamespace);
  const [preview, setPreview] = useState<MachineConfigurationPreview | null>(null);
  const [transaction, setTransaction] = useState<MachineConfigurationTransaction | null>(null);
  const [rollbackPlan, setRollbackPlan] = useState<MachineConfigurationRollbackPlan | null>(null);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | "rollback-preview" | "rollback" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function reload() {
    const next = await fetchMachineConfiguration();
    setInspection(next);
    setDraft(draftFromInspection(next));
    setSelectedNamespace((current) => next.available_namespaces.includes(current)
      ? current
      : next.available_namespaces[0] ?? periodicReportNamespace);
  }

  useEffect(() => {
    let active = true;
    fetchMachineConfiguration()
      .then((next) => {
        if (!active) return;
        setInspection(next);
        setDraft(draftFromInspection(next));
        setSelectedNamespace(next.available_namespaces[0] ?? periodicReportNamespace);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : t("machine.loadError"));
      })
      .finally(() => {
        if (active) setBusy(null);
      });
    return () => { active = false; };
  }, [t]);

  const draftValid = Boolean(
    draft.timezone.trim()
    && (!draft.enabled || (draft.profilePreset.trim() && draft.routeRef.trim())),
  );
  const namespaces = inspection?.available_namespaces ?? [periodicReportNamespace];
  const configuredNamespaces = useMemo(
    () => new Set(Object.keys(inspection?.machine_configuration?.namespaces ?? {})),
    [inspection],
  );

  function updateDraft(patch: Partial<PeriodicReportDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
    setPreview(null);
    setRollbackPlan(null);
    setError(null);
    setNotice(null);
  }

  async function createPreview() {
    if (!draftValid || busy) return;
    setBusy("preview");
    setError(null);
    setNotice(null);
    try {
      setPreview(await previewMachineConfiguration(
        periodicReportNamespace,
        configurationFromDraft(draft),
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("machine.previewError"));
    } finally {
      setBusy(null);
    }
  }

  async function applyPreview() {
    if (!preview || busy) return;
    setBusy("apply");
    setError(null);
    try {
      const result = await applyMachineConfiguration(
        periodicReportNamespace,
        configurationFromDraft(draft),
        preview.plan_revision,
      );
      setTransaction(result);
      setPreview(null);
      setRollbackPlan(null);
      await reload();
      setNotice(result.status === "applied" ? t("machine.applied") : t("machine.unchanged"));
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof Error ? cause.message : t("machine.applyError"));
    } finally {
      setBusy(null);
    }
  }

  async function previewRollback() {
    if (!transaction?.transaction_id || busy) return;
    setBusy("rollback-preview");
    setError(null);
    try {
      setRollbackPlan(await previewMachineConfigurationRollback(transaction.transaction_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("machine.rollbackError"));
    } finally {
      setBusy(null);
    }
  }

  async function applyRollback() {
    if (!transaction?.transaction_id || !rollbackPlan || busy) return;
    setBusy("rollback");
    setError(null);
    try {
      await applyMachineConfigurationRollback(
        transaction.transaction_id,
        rollbackPlan.plan_revision,
      );
      setTransaction(null);
      setRollbackPlan(null);
      setPreview(null);
      await reload();
      setNotice(t("machine.rolledBack"));
    } catch (cause) {
      setRollbackPlan(null);
      setError(cause instanceof Error ? cause.message : t("machine.rollbackError"));
    } finally {
      setBusy(null);
    }
  }

  if (busy === "load") {
    return <div className="personal-machine-loading" role="status">{t("common.loading")}</div>;
  }

  return (
    <div className="personal-machine-layout">
      <aside aria-label={t("machine.namespaces")} className="personal-machine-namespaces">
        <div>
          <small>{t("machine.registry")}</small>
          <strong>{t("machine.namespaces")}</strong>
        </div>
        <nav>
          {namespaces.map((namespace) => (
            <button
              aria-current={selectedNamespace === namespace ? "page" : undefined}
              key={namespace}
              onClick={() => setSelectedNamespace(namespace)}
              type="button"
            >
              <span>{namespace === periodicReportNamespace ? t("machine.periodicReport") : namespace}</span>
              <small>{configuredNamespaces.has(namespace) ? t("machine.configured") : t("machine.absent")}</small>
            </button>
          ))}
        </nav>
      </aside>

      <section className="personal-machine-content">
        <div className="personal-machine-summary">
          <div>
            <span className="personal-settings-icon"><ServerCog aria-hidden size={18} /></span>
            <span>
              <small>{t("machine.machinePolicy")}</small>
              <strong>{inspection?.status === "configured" ? t("machine.configured") : t("machine.absent")}</strong>
            </span>
          </div>
          <dl>
            <div><dt>{t("machine.revision")}</dt><dd title={inspection?.revision}>{shortRevision(inspection?.revision)}</dd></div>
            <div><dt>{t("machine.namespaceCount")}</dt><dd>{namespaces.length}</dd></div>
          </dl>
        </div>

        {selectedNamespace === periodicReportNamespace ? (
          <form className="personal-machine-editor" onSubmit={(event) => { event.preventDefault(); void createPreview(); }}>
            <header>
              <div>
                <small>{periodicReportNamespace}</small>
                <h2>{t("machine.periodicReport")}</h2>
                <p>{t("machine.periodicReportDescription")}</p>
              </div>
              <label className="personal-machine-switch" htmlFor={enabledId}>
                <span>{draft.enabled ? t("common.on") : t("common.off")}</span>
                <input
                  checked={draft.enabled}
                  id={enabledId}
                  onChange={(event) => updateDraft({ enabled: event.target.checked })}
                  type="checkbox"
                />
              </label>
            </header>

            <div className="personal-machine-scope-note">
              <ShieldCheck aria-hidden size={18} />
              <div>
                <strong>{t("machine.futureGoalsOnly")}</strong>
                <p>{t("machine.futureGoalsOnlyDescription")}</p>
              </div>
            </div>

            <fieldset disabled={!draft.enabled || Boolean(busy)}>
              <label htmlFor={profileId}>
                <span>{t("machine.profilePreset")}</span>
                <input
                  id={profileId}
                  onChange={(event) => updateDraft({ profilePreset: event.target.value })}
                  placeholder="weekly-progress"
                  value={draft.profilePreset}
                />
                <small>{t("machine.profilePresetHelp")}</small>
              </label>
              <label htmlFor={routeId}>
                <span>{t("machine.routeRef")}</span>
                <input
                  id={routeId}
                  onChange={(event) => updateDraft({ routeRef: event.target.value })}
                  placeholder="loopx-manager"
                  value={draft.routeRef}
                />
                <small>{t("machine.routeRefHelp")}</small>
              </label>
              <label htmlFor={timezoneId}>
                <span>{t("machine.timezone")}</span>
                <input
                  id={timezoneId}
                  onChange={(event) => updateDraft({ timezone: event.target.value })}
                  placeholder="Asia/Shanghai"
                  value={draft.timezone}
                />
                <small>{t("machine.timezoneHelp")}</small>
              </label>
            </fieldset>

            {!draftValid ? <p className="personal-machine-validation" role="alert">{t("machine.requiredFields")}</p> : null}
            {error ? <p className="personal-machine-error" role="alert">{error}</p> : null}
            {notice ? <p className="personal-machine-notice" role="status"><Check aria-hidden size={16} />{notice}</p> : null}

            {preview ? (
              <section aria-label={t("machine.preview")} className="personal-machine-preview">
                <header><strong>{t("machine.preview")}</strong><span>{t(`machine.action.${preview.action}`)}</span></header>
                <dl>
                  <div><dt>{t("machine.currentRevision")}</dt><dd title={preview.current_revision}>{shortRevision(preview.current_revision)}</dd></div>
                  <div><dt>{t("machine.desiredRevision")}</dt><dd title={preview.desired_revision}>{shortRevision(preview.desired_revision)}</dd></div>
                  <div><dt>{t("machine.changedNamespaces")}</dt><dd>{preview.changed_namespaces.join(", ") || t("common.none")}</dd></div>
                </dl>
                <p>{t("machine.previewLocked")}</p>
              </section>
            ) : null}

            {transaction?.rollback_available && transaction.transaction_id ? (
              <section className="personal-machine-rollback">
                <div>
                  <strong>{t("machine.rollbackAvailable")}</strong>
                  <p>{rollbackPlan ? t("machine.rollbackPreviewDescription") : t("machine.rollbackDescription")}</p>
                </div>
                <button
                  className="personal-secondary-action"
                  disabled={Boolean(busy) || Boolean(rollbackPlan && !rollbackPlan.rollback_allowed)}
                  onClick={() => void (rollbackPlan ? applyRollback() : previewRollback())}
                  type="button"
                >
                  <RotateCcw aria-hidden size={15} />
                  {busy === "rollback" || busy === "rollback-preview"
                    ? t("common.loading")
                    : rollbackPlan ? t("machine.confirmRollback") : t("machine.previewRollback")}
                </button>
              </section>
            ) : null}

            <footer>
              <button
                className="personal-secondary-action"
                disabled={Boolean(busy) || !draftValid}
                type="submit"
              >
                {busy === "preview" ? t("common.loading") : t("machine.previewChanges")}
              </button>
              <button
                className="personal-primary-action"
                disabled={Boolean(busy) || !preview}
                onClick={() => void applyPreview()}
                type="button"
              >
                {busy === "apply" ? t("common.loading") : t("machine.applyPreview")}
              </button>
            </footer>
          </form>
        ) : (
          <div className="personal-machine-unavailable">
            <ServerCog aria-hidden size={20} />
            <strong>{t("machine.editorUnavailable")}</strong>
            <p>{t("machine.editorUnavailableDescription")}</p>
          </div>
        )}
      </section>
    </div>
  );
}
