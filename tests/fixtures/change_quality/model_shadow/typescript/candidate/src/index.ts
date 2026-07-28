class CountFormatter {
  format(count: number | null): string {
    return count === null ? "unknown" : String(count);
  }
}

export function displayCount(count: number | null): string {
  return new CountFormatter().format(count);
}
