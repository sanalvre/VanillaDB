/**
 * Vault store — manages vault paths, initialization state, and sidecar connection.
 *
 * This is the root store that determines whether to show onboarding or the main app.
 * It also manages file watcher lifecycle.
 */

import { create } from "zustand";
import { getVaultStructure } from "@/api/sidecar";

interface VaultState {
  cleanVaultPath: string | null;
  wikiVaultPath: string | null;
  initialized: boolean;
  loading: boolean;
  sidecarPort: number;
  sidecarConnected: boolean;
  vaultWarnings: string[];
  checkInitialization: () => Promise<void>;
  setVaultPaths: (clean: string, wiki: string) => void;
  setSidecarPort: (port: number) => void;
  setSidecarConnected: (connected: boolean) => void;
}

export const useVaultStore = create<VaultState>((set) => ({
  cleanVaultPath: null,
  wikiVaultPath: null,
  initialized: false,
  loading: true,
  sidecarPort: 8000, // Default; overridden by Tauri on sidecar spawn
  sidecarConnected: false,
  vaultWarnings: [],

  checkInitialization: async () => {
    try {
      const data = await getVaultStructure();
      set({
        initialized: data.initialized,
        cleanVaultPath: data.clean_vault_path,
        wikiVaultPath: data.wiki_vault_path,
        vaultWarnings: data.warnings || [],
        loading: false,
        sidecarConnected: true,
      });
    } catch {
      // Sidecar not running yet
      set({ loading: false, initialized: false, sidecarConnected: false });
    }
  },

  setVaultPaths: (clean: string, wiki: string) => {
    set({
      cleanVaultPath: clean,
      wikiVaultPath: wiki,
      initialized: true,
    });
  },

  setSidecarPort: (port: number) => {
    set({ sidecarPort: port });
  },

  setSidecarConnected: (connected: boolean) => {
    set({ sidecarConnected: connected });
  },
}));
