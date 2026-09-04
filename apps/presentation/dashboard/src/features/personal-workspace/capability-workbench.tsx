import { SlidersHorizontal } from "lucide-react";

import type { CapabilityConfigurationCatalog } from "../../data/chat";
import type { WorkspaceLocale, WorkspaceTranslate } from "./i18n";
import { localizeCapability } from "./capability-localization";

type CapabilityDescriptor = CapabilityConfigurationCatalog["capabilities"][number];

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
      {capabilities.map((rawCapability) => {
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
