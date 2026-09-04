export const workspaceThemeStorageKey = "loopx-pw-theme";

export type WorkspaceTheme = "loopx" | "paper" | "brutal";

export const defaultWorkspaceTheme: WorkspaceTheme = "loopx";

export function readWorkspaceTheme(): WorkspaceTheme {
  try {
    const stored = window.localStorage.getItem(workspaceThemeStorageKey);
    return stored === "loopx" || stored === "paper" || stored === "brutal"
      ? stored
      : defaultWorkspaceTheme;
  } catch {
    return defaultWorkspaceTheme;
  }
}

export function writeWorkspaceTheme(theme: WorkspaceTheme): void {
  try {
    window.localStorage.setItem(workspaceThemeStorageKey, theme);
  } catch {
    // Storage may be unavailable; the in-memory preference still applies.
  }
}
