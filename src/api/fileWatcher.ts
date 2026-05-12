/**
 * File watcher — watches vault directories via Tauri's fs plugin
 * and forwards events to the Python sidecar.
 *
 * This bridges Tauri's native file watching (Rust notify) with the
 * Python sidecar's debounce queue.
 */

import { watch } from "@tauri-apps/plugin-fs";
import { sendFileEvent } from "./sidecar";
import { toRelative } from "./paths";

type UnwatchFn = () => void;

let cleanVaultUnwatch: UnwatchFn | null = null;
let wikiStagingUnwatch: UnwatchFn | null = null;

// Suppressed paths: path → expiry timestamp (ms). Events for suppressed paths
// are dropped once to absorb the echo from an editor save.
const suppressedPaths = new Map<string, number>();

/**
 * Suppress the next watcher event for a vault-relative path for durationMs.
 * Call this after saving a file from the editor to prevent a pipeline re-trigger.
 */
export function suppressWatcherPath(relativePath: string, durationMs = 2000): void {
  suppressedPaths.set(relativePath, Date.now() + durationMs);
}

/**
 * Start watching the clean vault and wiki-vault/staging for file changes.
 * Events are forwarded to the sidecar via POST /internal/file-event.
 *
 * @param cleanVaultPath Absolute path to the clean-vault directory
 * @param wikiVaultPath Absolute path to the wiki-vault directory
 * @param vaultRoot Parent directory of both vaults (for relative path computation)
 */
export async function startVaultWatcher(
  cleanVaultPath: string,
  wikiVaultPath: string,
  vaultRoot: string,
): Promise<void> {
  // Stop any existing watchers
  await stopVaultWatcher();

  // Watch clean-vault (recursive) — agent needs to know about new/changed source files
  cleanVaultUnwatch = await watch(
    cleanVaultPath,
    (event) => {
      handleWatchEvent(event, vaultRoot);
    },
    { recursive: true },
  );

  // Watch wiki-vault/staging (recursive) — agent writes proposals here
  const stagingPath = `${wikiVaultPath}/staging`;
  try {
    wikiStagingUnwatch = await watch(
      stagingPath,
      (event) => {
        handleWatchEvent(event, vaultRoot);
      },
      { recursive: true },
    );
  } catch {
    // staging/ may not exist yet on first run — that's fine
    console.warn("Could not watch staging directory (may not exist yet)");
  }

}

/**
 * Stop all file watchers.
 */
export async function stopVaultWatcher(): Promise<void> {
  if (cleanVaultUnwatch) {
    cleanVaultUnwatch();
    cleanVaultUnwatch = null;
  }
  if (wikiStagingUnwatch) {
    wikiStagingUnwatch();
    wikiStagingUnwatch = null;
  }
}

/**
 * Handle a raw Tauri watch event and forward to the sidecar.
 */
function handleWatchEvent(event: unknown, vaultRoot: string): void {
  // Tauri fs watch events have different shapes depending on the event type
  // We normalize them into our FileEvent format
  const fsEvent = event as {
    type?: { create?: unknown; modify?: unknown; remove?: unknown };
    paths?: string[];
  };

  if (!fsEvent.paths || fsEvent.paths.length === 0) return;

  let eventType: "create" | "modify" | "delete" = "modify";
  if (fsEvent.type) {
    if ("create" in fsEvent.type) eventType = "create";
    else if ("remove" in fsEvent.type) eventType = "delete";
    else eventType = "modify";
  }

  for (const absPath of fsEvent.paths) {
    // Skip hidden files, .DS_Store, etc.
    const filename = absPath.split(/[/\\]/).pop() ?? "";
    if (filename.startsWith(".") && filename !== ".meta") continue;

    const relativePath = toRelative(absPath, vaultRoot);

    // Drop this event if the path is suppressed (editor just saved it)
    const expiry = suppressedPaths.get(relativePath);
    if (expiry !== undefined) {
      suppressedPaths.delete(relativePath);
      if (Date.now() < expiry) continue;
    }

    // Fire and forget — don't block the watcher
    sendFileEvent(relativePath, eventType).catch((err) => {
      console.error("[FileWatcher] Failed to send event:", err);
    });
  }
}
