import {AuthorityStoreProtocolError} from "./authority_store_codec.ts";

export function normalizeTodoAgent(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new AuthorityStoreProtocolError(`${label} must be a public-safe agent id`);
  }
  const candidate = value.trim().toLowerCase().replaceAll(" ", "-");
  if (!/^[a-z][a-z0-9_.:@-]{0,79}$/u.test(candidate)) {
    throw new AuthorityStoreProtocolError(`${label} must be a public-safe agent id`);
  }
  return candidate;
}

export function normalizeRegisteredTodoAgents(value: readonly string[]): string[] {
  if (!Array.isArray(value)) {
    throw new AuthorityStoreProtocolError("registered_agents must be an array");
  }
  const normalized = value.map((agent, index) =>
    normalizeTodoAgent(agent, `registered_agents[${index}]`)
  );
  if (new Set(normalized).size !== normalized.length) {
    throw new AuthorityStoreProtocolError(
      "registered_agents must contain unique public-safe agent ids",
    );
  }
  return normalized;
}
