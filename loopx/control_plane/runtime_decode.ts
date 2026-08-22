import type { JsonObject } from "./effect_program.ts";

export function jsonObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

export function requireJsonObject(value: unknown, label: string): JsonObject {
  const result = jsonObject(value);
  if (!result) throw new Error(`${label} must be an object`);
  return result;
}

export function requireBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

export function requireInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${label} must be an integer`);
  }
  return value;
}

export function requireNonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

export function optionalNonEmptyString(
  value: unknown,
  label: string,
): string | null {
  if (value === null || value === undefined || value === "") return null;
  return requireNonEmptyString(value, label);
}

export function requireStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} must be an array of strings`);
  }
  return [...value];
}

export function isStringLiteral<const Values extends readonly string[]>(
  value: string,
  allowed: Values,
): value is Values[number] {
  return allowed.some((candidate) => candidate === value);
}

export function requireStringLiteral<const Values extends readonly string[]>(
  value: unknown,
  allowed: Values,
  label: string,
  unsupportedMessage = `${label} is unsupported`,
): Values[number] {
  const candidate = requireNonEmptyString(value, label);
  if (!isStringLiteral(candidate, allowed)) {
    throw new Error(unsupportedMessage);
  }
  return candidate;
}

export function assertNever(value: never, message: string): never {
  throw new Error(`${message}: ${String(value)}`);
}
