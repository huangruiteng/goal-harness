export type CapabilityConfigurationFieldDescriptor = {
  key: string;
};

export type CapabilityConfigurationEditorDescriptor = {
  fields: readonly CapabilityConfigurationFieldDescriptor[];
};

function configurationObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

/**
 * Project a public capability value onto the editor-owned write surface.
 *
 * Capability read models deliberately contain provenance and derived fields.
 * Those fields are useful to operators but are not write authority.  Keeping
 * this projection next to the transport contract prevents invisible read-only
 * values from being submitted by any form consumer.
 */
export function projectEditableCapabilityConfiguration(
  editor: CapabilityConfigurationEditorDescriptor,
  value: unknown,
  fallback?: unknown,
): Record<string, unknown> {
  const primary = configurationObject(value);
  const defaults = configurationObject(fallback);
  return Object.fromEntries(editor.fields.flatMap(({ key }) => {
    if (Object.hasOwn(primary, key)) return [[key, primary[key]]];
    if (Object.hasOwn(defaults, key)) return [[key, defaults[key]]];
    return [];
  }));
}
