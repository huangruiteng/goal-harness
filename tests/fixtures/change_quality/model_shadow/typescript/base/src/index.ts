export function displayCount(count: number | null): string {
  return count === null ? "unknown" : String(count);
}
