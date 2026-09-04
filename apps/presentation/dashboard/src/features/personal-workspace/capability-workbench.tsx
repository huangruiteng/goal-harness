import { SlidersHorizontal } from "lucide-react";

import type { CapabilityConfigurationCatalog } from "../../data/chat";
import type { WorkspaceLocale, WorkspaceTranslate } from "./i18n";
import { localizeCapability } from "./capability-localization";

type CapabilityDescriptor = CapabilityConfigurationCatalog["capabilities"][number];

function capabilityPresentationTier(capability: CapabilityDescriptor) {
  if (capability.availability?.includes("experimental")) return 4;
  if (capability.capability_id === "multi_subagent") return 3;
  if (capability.configuration_editor.writable_scopes.length === 0) return 2;
  if (capability.availability === "supported_explicit_opt_in") return 2;
  if (capability.availability === "supported_explicit_override") return 0;
  return 1;
}

export function orderCapabilitiesForPresentation(
  capabilities: CapabilityDescriptor[],
  locale: WorkspaceLocale,
) {
  return [...capabilities].sort((left, right) => {
    const tierDifference = capabilityPresentationTier(left) - capabilityPresentationTier(right);
    if (tierDifference !== 0) return tierDifference;
    const localizedLeft = localizeCapability(left, locale);
    const localizedRight = localizeCapability(right, locale);
    return localizedLeft.display_name.localeCompare(localizedRight.display_name, locale)
      || left.capability_id.localeCompare(right.capability_id);
  });
}

export function CapabilityCatalogNavigation({
  capabilities,
  locale,
  onSelect,
  scope,
  selectedCapabilityId,
  t,
}: Readonly<{
  capabilities: CapabilityDescriptor[];
  locale: WorkspaceLocale;
  onSelect: (capabilityId: string) => void;
  scope: "goal" | "machine";
  selectedCapabilityId: string;
  t: WorkspaceTranslate;
}>) {
  return (
    <nav aria-label={t(scope === "goal" ? "capabilities.catalog" : "machine.capabilityCatalog")} className="personal-capability-list">
      {orderCapabilitiesForPresentation(capabilities, locale).map((rawCapability) => {
        const capability = localizeCapability(rawCapability, locale);
        return (
          <button
            aria-current={selectedCapabilityId === capability.capability_id ? "page" : undefined}
            key={capability.capability_id}
            onClick={() => onSelect(capability.capability_id)}
            type="button"
          >
            <span>
              <strong>{capability.display_name}</strong>
              <small>{capability.capability_id}</small>
            </span>
            <em>{t(scope === "goal" ? "capabilities.goalScope" : "capabilities.machineScope")}</em>
          </button>
        );
      })}
    </nav>
  );
}

export function CapabilityDetailHeader({ capability, locale }: Readonly<{
  capability: CapabilityDescriptor;
  locale: WorkspaceLocale;
}>) {
  const localized = localizeCapability(capability, locale);
  return (
    <header>
      <span className="personal-settings-icon"><SlidersHorizontal aria-hidden size={18} /></span>
      <div>
        <small>{localized.capability_id}</small>
        <h2>{localized.display_name}</h2>
        <p>{localized.description}</p>
      </div>
    </header>
  );
}
