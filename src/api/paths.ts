/**
 * Path normalization utilities — TypeScript side.
 *
 * Must match behavior of sidecar/services/paths.py exactly.
 * All paths stored in the app use forward slashes regardless of OS.
 */

/**
 * Normalize a file path to use forward slashes.
 * Used on every path before sending to sidecar or displaying in UI.
 */
export function normalizePath(path: string): string {
  return path.replace(/\\/g, "/");
}

/**
 * Convert an absolute path to a vault-relative path with forward slashes.
 */
export function toRelative(absolutePath: string, vaultRoot: string): string {
  const normalizedAbs = normalizePath(absolutePath);
  const normalizedRoot = normalizePath(vaultRoot);

  if (normalizedAbs.startsWith(normalizedRoot)) {
    let relative = normalizedAbs.slice(normalizedRoot.length);
    if (relative.startsWith("/")) {
      relative = relative.slice(1);
    }
    return relative;
  }

  return normalizedAbs;
}

/**
 * Check if a relative path belongs to the clean vault.
 */
export function isCleanVaultPath(relativePath: string): boolean {
  return normalizePath(relativePath).startsWith("clean-vault/");
}

/**
 * Check if a relative path belongs to the wiki vault.
 */
export function isWikiVaultPath(relativePath: string): boolean {
  return normalizePath(relativePath).startsWith("wiki-vault/");
}
