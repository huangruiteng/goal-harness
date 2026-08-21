declare module '*.module.css' {
  const classes: Readonly<Record<string, string>>
  /** Reinstall the cached module's owned style after a normal plugin reload. */
  export function ensurePluginStyle(): void
  export default classes
}
