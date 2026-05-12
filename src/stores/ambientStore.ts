/**
 * Ambient store — handles out-of-window actions like clipboard clipping.
 *
 * Triggered by Tauri events (tray menu, global hotkeys) that fire even
 * when the main window is not focused.
 */

import { useVaultStore } from "./vaultStore";

function baseUrl(): string {
  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) return `http://127.0.0.1:${stored}`;
  return `http://127.0.0.1:${useVaultStore.getState().sidecarPort}`;
}

/**
 * Clip arbitrary text to clean-vault/raw/clips/{timestamp}.md.
 * The sidecar writes the file and immediately triggers the pipeline.
 */
export async function clipToVault(text: string, title?: string): Promise<string> {
  const res = await fetch(`${baseUrl()}/ingest/clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Clip failed: ${res.status}`);
  }
  const data = await res.json();
  return data.job_id as string;
}
