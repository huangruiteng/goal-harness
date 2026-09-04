import { useId } from "react";

import type { CapabilityConfigurationEditor } from "../../data/chat";

type FieldCopy = Record<string, { description?: string; label?: string }>;

export function CapabilityConfigurationFields({
  copy = {},
  disabled = false,
  editor,
  omitKeys = [],
  onChange,
  value,
}: {
  copy?: FieldCopy;
  disabled?: boolean;
  editor: CapabilityConfigurationEditor;
  omitKeys?: readonly string[];
  onChange?: (key: string, value: boolean | number | string | string[]) => void;
  value: Record<string, unknown>;
}) {
  const idPrefix = useId();
  const omitted = new Set(omitKeys);
  const readOnly = !onChange;

  return (
    <fieldset className="personal-capability-fields" disabled={disabled}>
      {editor.fields.filter((field) => !omitted.has(field.key)).map((field) => {
        const id = `${idPrefix}-${field.key.replace(/[^a-z0-9_-]/gi, "-")}`;
        const label = copy[field.key]?.label ?? field.label;
        const description = copy[field.key]?.description ?? field.description;
        const current = value[field.key];
        if (field.input_kind === "boolean") {
          return (
            <label className="is-boolean" htmlFor={id} key={field.key}>
              <span>{label}</span>
              <input
                checked={current === true}
                id={id}
                onChange={onChange ? (event) => onChange(field.key, event.target.checked) : undefined}
                readOnly={readOnly}
                type="checkbox"
              />
              {description ? <small>{description}</small> : null}
            </label>
          );
        }
        if (field.input_kind === "select") {
          return (
            <label htmlFor={id} key={field.key}>
              <span>{label}</span>
              <select
                id={id}
                onChange={onChange ? (event) => onChange(field.key, event.target.value) : undefined}
                value={typeof current === "string" ? current : ""}
              >
                <option value="" />
                {(field.options ?? []).map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
              {description ? <small>{description}</small> : null}
            </label>
          );
        }
        if (field.input_kind === "string_list") {
          return (
            <label htmlFor={id} key={field.key}>
              <span>{label}</span>
              <textarea
                id={id}
                onChange={onChange ? (event) => onChange(field.key, event.target.value.split(/\r?\n/u).filter(Boolean)) : undefined}
                readOnly={readOnly}
                rows={4}
                value={Array.isArray(current) ? current.join("\n") : ""}
              />
              {description ? <small>{description}</small> : null}
            </label>
          );
        }
        return (
          <label htmlFor={id} key={field.key}>
            <span>{label}</span>
            <input
              id={id}
              max={field.maximum}
              min={field.minimum}
              onChange={onChange ? (event) => onChange(
                field.key,
                field.input_kind === "number" ? Number(event.target.value) : event.target.value,
              ) : undefined}
              readOnly={readOnly}
              required={field.required}
              type={field.input_kind === "number" ? "number" : "text"}
              value={typeof current === "number" || typeof current === "string" ? current : ""}
            />
            {description ? <small>{description}</small> : null}
          </label>
        );
      })}
    </fieldset>
  );
}
