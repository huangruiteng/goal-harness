import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";

export const DELIVERY_OUTCOMES = [
  "surface_only",
  "outcome_gap",
  "outcome_progress",
  "primary_goal_outcome",
] as const;

export const MATERIAL_DELIVERY_OUTCOMES = [
  "outcome_gap",
  "outcome_progress",
  "primary_goal_outcome",
] as const;

export type DeliveryOutcome = (typeof DELIVERY_OUTCOMES)[number];
export type MaterialDeliveryOutcome =
  (typeof MATERIAL_DELIVERY_OUTCOMES)[number];

export function decodeOptionalDeliveryOutcome(
  value: unknown,
  label = "delivery_outcome",
): DeliveryOutcome | null {
  if (value === null || value === undefined || value === "") return null;
  if (DELIVERY_OUTCOMES.some((candidate) => candidate === value)) {
    return value as DeliveryOutcome;
  }
  throw new EffectRuntimeRequestError(`${label} is unsupported`);
}

export function decodeOptionalMaterialDeliveryOutcome(
  value: unknown,
  label = "delivery_outcome",
): MaterialDeliveryOutcome | null {
  const outcome = decodeOptionalDeliveryOutcome(value, label);
  if (
    outcome === null ||
    MATERIAL_DELIVERY_OUTCOMES.some((candidate) => candidate === outcome)
  ) {
    return outcome as MaterialDeliveryOutcome | null;
  }
  throw new EffectRuntimeRequestError(`${label} is not a material delivery outcome`);
}

export function isMaterialDeliveryOutcome(
  value: DeliveryOutcome | null,
): value is MaterialDeliveryOutcome {
  return MATERIAL_DELIVERY_OUTCOMES.some((candidate) => candidate === value);
}
