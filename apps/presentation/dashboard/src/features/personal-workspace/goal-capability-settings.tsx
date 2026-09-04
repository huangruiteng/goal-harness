import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";

import {
  applyGoalConfiguration,
  fetchGoalConfiguration,
  previewGoalConfiguration,
  type CapabilityConfigurationCatalog,
  type GoalConfigurationInspection,
  type GoalConfigurationPreview,
  type GoalConfigurationPartialWrite,
} from "../../data/chat";
import { projectEditableCapabilityConfiguration } from "../../data/capability-configuration";
import { useWorkspaceI18n } from "./i18n";
import { CapabilityConfigurationFields } from "./capability-configuration-fields";

function formattedValue(value: Record<string, unknown> | undefined) {
  return value ? JSON.stringify(value, null, 2) : "—";
}

type CapabilityCatalogProps = Readonly<{
  catalog: CapabilityConfigurationCatalog;
  goalId: string;
  onApplied: () => void;
}>;

type CapabilityMutationState = Readonly<{
  busy: "preview" | "apply" | null;
  draft: Record<string, unknown>;
  partialWrite: GoalConfigurationPartialWrite | null;
  preview: GoalConfigurationPreview | null;
}>;

function useCapabilityMutation({ goalId, onApplied, selected, t }: Readonly<{
  goalId: string;
  onApplied: () => void;
  selected: CapabilityConfigurationCatalog["capabilities"][number] | undefined;
  t: ReturnType<typeof useWorkspaceI18n>["t"];
}>) {
  const [mutation, setMutation] = useState<CapabilityMutationState>({
    busy: null,
    draft: {},
    partialWrite: null,
    preview: null,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMutation({
      busy: null,
      draft: projectEditableCapabilityConfiguration(
        selected?.configuration_editor ?? { fields: [] },
        selected?.current
        ?? selected?.effective_configuration?.configuration
        ?? selected?.default,
        selected?.default,
      ),
      partialWrite: null,
      preview: null,
    });
    setError(null);
  }, [selected]);

  async function preview(configuration: Record<string, unknown> | null) {
    if (!selected || mutation.busy) return;
    setMutation((current) => ({ ...current, busy: "preview", partialWrite: null }));
    setError(null);
    try {
      const nextPreview = await previewGoalConfiguration(goalId, selected.capability_id, configuration);
      setMutation((current) => ({ ...current, preview: nextPreview }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("capabilities.previewFailed"));
    } finally {
      setMutation((current) => ({ ...current, busy: null }));
    }
  }

  async function apply() {
    if (!selected || !mutation.preview || mutation.busy) return;
    setMutation((current) => ({ ...current, busy: "apply" }));
    setError(null);
    try {
      const writableDraft = projectEditableCapabilityConfiguration(
        selected.configuration_editor,
        mutation.draft,
        selected.default,
      );
      const result = await applyGoalConfiguration(
        goalId,
        selected.capability_id,
        mutation.preview.action === "delete" ? null : writableDraft,
        mutation.preview.plan_revision,
      );
      setMutation((current) => ({
        ...current,
        partialWrite: result.status === "partial_write" ? result : null,
        preview: null,
      }));
      if (result.status !== "partial_write") onApplied();
    } catch (reason) {
      setMutation((current) => ({ ...current, preview: null }));
      setError(reason instanceof Error ? reason.message : t("capabilities.applyFailed"));
    } finally {
      setMutation((current) => ({ ...current, busy: null }));
    }
  }

  function changeDraft(key: string, value: boolean | number | string | string[]) {
    setMutation((current) => ({
      ...current,
      draft: { ...current.draft, [key]: value },
      preview: null,
    }));
    setError(null);
  }

  return { apply, changeDraft, error, mutation, preview };
}

function CapabilityMutationFeedback({ mutationError, onApplied, partialWrite, preview }: Readonly<{
  mutationError: string | null;
  onApplied: () => void;
  partialWrite: GoalConfigurationPartialWrite | null;
  preview: GoalConfigurationPreview | null;
}>) {
  const { t } = useWorkspaceI18n();
  return (
    <>
      {mutationError ? <p className="personal-machine-error" role="alert">{mutationError}</p> : null}
      {partialWrite ? (
        <section aria-live="polite" className="personal-capability-recovery">
          <AlertTriangle aria-hidden size={18} />
          <div>
            <strong>{t("capabilities.partialWrite")}</strong>
            <p>{t("capabilities.partialWriteDescription")}</p>
            <small>{partialWrite.recommended_action}</small>
          </div>
          <button onClick={onApplied} type="button"><RefreshCw aria-hidden size={15} />{t("capabilities.refreshSource")}</button>
        </section>
      ) : null}
      {preview ? (
        <section className="personal-capability-preview" aria-label={t("capabilities.preview") }>
          <strong>{t("capabilities.preview")}</strong>
          <span>{t(`machine.action.${preview.action}`)}</span>
          <small>{t("capabilities.previewLocked")}</small>
        </section>
      ) : null}
    </>
  );
}

function CapabilityCatalog({ catalog, goalId, onApplied }: CapabilityCatalogProps) {
  const { t } = useWorkspaceI18n();
  const [selectedCapabilityId, setSelectedCapabilityId] = useState(
    catalog.capabilities[0]?.capability_id ?? "",
  );
  const selected = useMemo(
    () => catalog.capabilities.find((capability) => capability.capability_id === selectedCapabilityId)
      ?? catalog.capabilities[0],
    [catalog.capabilities, selectedCapabilityId],
  );
  const capabilityMutation = useCapabilityMutation({ goalId, onApplied, selected, t });
  const { apply, changeDraft, error: mutationError, mutation, preview: requestPreview } = capabilityMutation;
  const { busy, draft, partialWrite, preview } = mutation;

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
    const writableDraft = projectEditableCapabilityConfiguration(
      selected.configuration_editor,
      draft,
      selected.default,
    );
    await requestPreview(writableDraft);
  }

  async function createClearPreview() {
    if (!editorAvailable || busy) return;
    await requestPreview(null);
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
              onChange={changeDraft}
              value={draft}
            />
          </section>
        ) : null}
        <CapabilityMutationFeedback mutationError={mutationError} onApplied={onApplied} partialWrite={partialWrite} preview={preview} />
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
            <button className="is-primary" disabled={Boolean(busy) || !preview} onClick={() => void apply()} type="button">
              {busy === "apply" ? t("common.loading") : t("capabilities.applyPreview")}
            </button>
          </footer>
        ) : null}
      </article>
    </div>
  );
}

export function GoalCapabilitySettings({ goalId }: Readonly<{ goalId?: string | null }>) {
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
    return <p aria-live="polite" className="personal-capability-empty"><LoaderCircle className="personal-spin" size={18} />{t("capabilities.loading")}</p>;
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
