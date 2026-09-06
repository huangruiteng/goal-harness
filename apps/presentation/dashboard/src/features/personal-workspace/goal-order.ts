// Presentation preference only: never changes Goal priority or lifecycle.
export const goalOrderStorageKey = (source: string) => `loopx-sidebar-goal-order-v1:${encodeURIComponent(source)}`;

export function decodeGoalOrder(raw: string | null): string[] {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    return Array.isArray(value) && value.every((id) => typeof id === "string")
      ? [...new Set(value)] : [];
  } catch { return []; }
}

export function orderedGoals<T extends { goalId: string }>(goals: T[], order: string[]): T[] {
  const ranks = new Map(order.map((id, index) => [id, index]));
  return [...goals].sort((a, b) => (ranks.get(a.goalId) ?? Infinity) - (ranks.get(b.goalId) ?? Infinity));
}

export function moveGoal(order: string[], visible: string[], from: string, to: string, after: boolean): string[] {
  if (from === to || !visible.includes(from) || !visible.includes(to)) return order;
  // Retain absent/stopped IDs: partial status packets must not erase their position.
  const result = [...new Set([...order, ...visible])].filter((id) => id !== from);
  result.splice(result.indexOf(to) + Number(after), 0, from);
  return result;
}
