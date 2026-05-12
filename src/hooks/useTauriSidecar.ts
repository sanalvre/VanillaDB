/**
 * useTauriSidecar — discovers the Python sidecar's dynamic port and wires it
 * into the vault store + localStorage.
 *
 * Two complementary strategies run in parallel to avoid the race condition
 * where the sidecar emits VANILLA_PORT before the WebView has mounted:
 *
 *  1. Pull (on mount): invoke("get_sidecar_port") queries Tauri's managed
 *     state immediately — if the sidecar already started, we get the port
 *     right away without waiting for an event.
 *
 *  2. Push (event listener): listen("sidecar-ready") handles the normal
 *     case where the sidecar starts after the frontend is ready, and also
 *     acts as the signal for any polling loop to stop.
 *
 * Only activates when running inside a Tauri window.
 * In browser dev mode the port comes from ?port=<n> in the URL instead.
 */

import { useEffect } from "react";
import { useVaultStore } from "@/stores/vaultStore";

/** True when running inside the Tauri desktop shell. */
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function useTauriSidecar() {
  const setSidecarPort = useVaultStore((s) => s.setSidecarPort);
  const setSidecarConnected = useVaultStore((s) => s.setSidecarConnected);

  useEffect(() => {
    if (!isTauri()) return;

    let unlisten: (() => void) | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let cancelled = false;

    function applyPort(port: number) {
      if (cancelled) return;
      localStorage.setItem("vanilla:sidecarPort", String(port));
      setSidecarPort(port);
      setSidecarConnected(true);
      // Stop polling once we have a port
      if (pollTimer !== undefined) {
        clearInterval(pollTimer);
        pollTimer = undefined;
      }
    }

    async function init() {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const { listen } = await import("@tauri-apps/api/event");

        // Strategy 1 — Push: listen for the event (handles the normal path
        // and the case where the sidecar starts after the frontend mounts).
        unlisten = await listen<number>("sidecar-ready", (event) => {
          applyPort(event.payload);
        });

        // Strategy 2 — Pull: query managed state immediately in case the
        // sidecar already started before the event listener was registered.
        const port = await invoke<number | null>("get_sidecar_port");
        if (port) {
          applyPort(port);
          return; // Already have it — no need to poll
        }

        // Strategy 3 — Poll: if the sidecar is still starting, keep asking
        // every 500 ms until we get a port (or the component unmounts).
        pollTimer = setInterval(async () => {
          try {
            const p = await invoke<number | null>("get_sidecar_port");
            if (p) applyPort(p);
          } catch {
            // Ignore invoke errors during startup
          }
        }, 500);

      } catch (err) {
        console.warn("[Tauri] Could not initialise sidecar port discovery:", err);
      }
    }

    init();

    return () => {
      cancelled = true;
      unlisten?.();
      if (pollTimer !== undefined) clearInterval(pollTimer);
    };
  }, [setSidecarPort, setSidecarConnected]);
}
