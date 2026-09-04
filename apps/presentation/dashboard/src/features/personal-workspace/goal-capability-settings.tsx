import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";

import {
  applyGoalConfiguration,
  fetchGoalConfiguration,
  previewGoalConfiguration,
  type CapabilityConfigurationCatalog,
  type GoalConfigurationInspection,
  type GoalConfigurationPreview,
} from "../../data/chat";
import { useWorkspaceI18n } from "./i18n";
import { CapabilityConfigurationFields } from "./capability-configuration-fields";

function formattedValue(value: Record<string, unknown> | undefined) {
  return value ? JSON.stringify(value, null, 2) : "—";
}

function editableValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : {};
}

function CapabilityCatalog({ catalog, goalId, onApplied }: {
  catalog: CapabilityConfigurationCatalog;
  goalId: string;
  onApplied: () => void;
}) {
  const { t } = useWorkspaceI18n();
  const [selectedCapabilityId, setSelectedCapabilityId] = useState(
    catalog.capabilities[0]?.capability_id ?? "",
  );
  const selected = useMemo(
    () => catalog.capabilities.find((capability) => capability.capability_id === selectedCapabilityId)
      ?? catalog.capabilities[0],
    [catalog.capabilities, selectedCapabilityId],
  );
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [preview, setPreview] = useState<GoalConfigurationPreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(editableValue(
      selected?.current
      ?? selected?.effective_configuration?.configuration
      ?? selected?.default,
    ));
    setPreview(null);
    setMutationError(null);
  }, [selected]);

  if (!selected) {
    return <p className="personal-capability-empty">{t("capabilities.empty")}</p>;
  }

  const supportsGoal = selected.available_scopes.includes("goal");
  const editorAvailable = supportsGoal
    && selected.configuration_editor.editable
    && selected.configuration_editor.writable_scopes.includes("goal");
  const readOnlyReason = selected.configuration_editor.read_only_reason
    ?? (!supportsGoal ? t("capabilities.machineOnly") : t("capabilities.previewOnly"));

  async function createPreview() {
    if (!editorAvailable || busy) return;
    setBusy("preview");
    setMutationError(null);
    try {
      setPreview(await previewGoalConfiguration(goalId, selected.capability_id, draft));
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason.message : t("capabilities.previewFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function createClearPreview() {
    if (!editorAvailable || busy) return;
    setBusy("preview");
    setMutationError(null);
    try {
      setPreview(await previewGoalConfiguration(goalId, selected.capability_id, null));
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason.message : t("capabilities.previewFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function applyPreview() {
    if (!preview || busy) return;
    setBusy("apply");
    setMutationError(null);
    try {
      await applyGoalConfiguration(
        goalId,
        selected.capability_id,
        preview.action === "delete" ? null : draft,
        preview.plan_revision,
      );
      setPreview(null);
      onApplied();
    } catch (reason) {
      setPreview(null);
      setMutationError(reason instanceof Error ? reason.message : t("capabilities.applyFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="personal-capability-layout">
      <nav aria-label={t("capabilities.catalog")} className="personal-capability-list">
        {catalog.capabilities.map((capability) => (
          <button
            aria-current={selected.capability_id === capability.capability_id ? "page" : undefined}
            key={capability.capability_id}
            onClick={() => setSelectedCapabilityId(capability.capability_id)}
            type="button"
          >
            <span>
              <strong>{capability.display_name}</strong>
              <small>{capability.capability_id}</small>
            </span>
            <em>{capability.available_scopes.includes("goal") ? t("capabilities.goalScope") : t("capabilities.machineScope")}</em>
          </button>
        ))}
      </nav>

      <article className="personal-capability-detail">
        <header>
          <span className="personal-settings-icon"><SlidersHorizontal aria-hidden size={18} /></span>
          <div>
            <small>{selected.capability_id}</small>
            <h2>{selected.display_name}</h2>
            <p>{selected.description}</p>
          </div>
        </header>

        <div className="personal-capability-value-grid">
          <section>
            <strong>{t("capabilities.goalValue")}</strong>
            <pre>{formattedValue(selected.current)}</pre>
          </section>
          <section>
            <strong>{selected.machine_current ? t("capabilities.machineValue") : t("capabilities.defaultValue")}</strong>
            <pre>{formattedValue(selected.machine_current ?? selected.default)}</pre>
          </section>
        </div>

        {selected.effective_configuration ? (
          <p className="personal-capability-effective-source">
            <ShieldCheck aria-hidden size={15} />
            <span><strong>{t("capabilities.effectiveSource")}</strong>{t(`capabilities.source.${selected.effective_configuration.source}`)}</span>
          </p>
        ) : null}

        <section className={`personal-capability-editor-status ${editorAvailable ? "is-preview" : "is-read-only"}`}>
          {editorAvailable ? <ShieldCheck aria-hidden size={18} /> : <AlertTriangle aria-hidden size={18} />}
          <div>
            <strong>{editorAvailable ? t("capabilities.editorPrepared") : t("capabilities.readOnly")}</strong>
            <p>{editorAvailable ? t("capabilities.revisionLockedReady") : readOnlyReason}</p>
          </div>
        </section>

        {editorAvailable ? (
          <section className="personal-capability-field-summary">
            <strong>{t("capabilities.fields")}</strong>
            <CapabilityConfigurationFields
              disabled={Boolean(busy)}
              editor={selected.configuration_editor}
              onChange={(key, value) => {
                setDraft((current) => ({ ...current, [key]: value }));
                setPreview(null);
                setMutationError(null);
              }}
              value={draft}
            />
          </section>
        ) : null}
        {mutationError ? <p className="personal-machine-error" role="alert">{mutationError}</p> : null}
        {preview ? (
          <section className="personal-capability-preview" aria-label={t("capabilities.preview") }>
            <strong>{t("capabilities.preview")}</strong>
            <span>{t(`machine.action.${preview.action}`)}</span>
            <small>{t("capabilities.previewLocked")}</small>
          </section>
        ) : null}
        {editorAvailable ? (
          <footer className="personal-capability-actions">
            {selected.current && selected.available_scopes.includes("machine") ? (
              <button disabled={Boolean(busy)} onClick={() => void createClearPreview()} type="button">
                {t("capabilities.restoreInheritance")}
              </button>
            ) : null}
            <button disabled={Boolean(busy)} onClick={() => void createPreview()} type="button">
              {busy === "preview" ? t("common.loading") : t("capabilities.previewChanges")}
            </button>
            <button className="is-primary" disabled={Boolean(busy) || !preview} onClick={() => void applyPreview()} type="button">
              {busy === "apply" ? t("common.loading") : t("capabilities.applyPreview")}
            </button>
          </footer>
        ) : null}
      </article>
    </div>
  );
}

export function GoalCapabilitySettings({ goalId }: { goalId?: string | null }) {
  const { t } = useWorkspaceI18n();
  const [inspection, setInspection] = useState<GoalConfigurationInspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    if (!goalId) return;
    setLoading(true);
    setError(null);
    void fetchGoalConfiguration(goalId)
      .then(setInspection)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : t("capabilities.loadFailed")))
      .finally(() => setLoading(false));
  }

  useEffect(load, [goalId]);

  if (!goalId) {
    return <p className="personal-capability-empty">{t("capabilities.chooseGoal")}</p>;
  }
  if (loading && !inspection) {
    return <p className="personal-capability-empty" role="status"><LoaderCircle className="personal-spin" size={18} />{t("capabilities.loading")}</p>;
  }
  if (error) {
    return (
      <section className="personal-capability-error" role="alert">
        <AlertTriangle aria-hidden size={18} />
        <span><strong>{t("capabilities.loadFailed")}</strong><small>{error}</small></span>
        <button onClick={load} type="button"><RefreshCw aria-hidden size={15} />{t("capabilities.retry")}</button>
      </section>
    );
  }
  if (!inspection) return null;

  return (
    <section className="personal-capability-settings" data-revision={inspection.revision}>
      <div className="personal-capability-scope-note">
        <ShieldCheck aria-hidden size={17} />
        <p><strong>{t("capabilities.atomicOverride")}</strong>{t("capabilities.atomicOverrideDescription")}</p>
      </div>
      <CapabilityCatalog catalog={inspection.capability_catalog} goalId={goalId} onApplied={load} />
    </section>
  );
}
