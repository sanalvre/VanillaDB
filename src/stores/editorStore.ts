/**
 * Editor store — manages the active file, editor state, graph visibility, and split position.
 *
 * Keeps state flat for zustand selector efficiency.
 * Read-only files (wiki vault) cannot be saved from the editor.
 */

import { create } from "zustand";
import { getFileContent, saveFileContent } from "@/api/sidecar";
import { isWikiVaultPath } from "@/api/paths";
import { suppressWatcherPath } from "@/api/fileWatcher";

function readLocalBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === "true";
  } catch {
    return fallback;
  }
}

function readLocalNumber(key: string, fallback: number): number {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const n = Number(raw);
    return Number.isFinite(n) ? n : fallback;
  } catch {
    return fallback;
  }
}

interface EditorState {
  activeFilePath: string | null;
  fileContent: string | null;
  isDirty: boolean;
  isLoading: boolean;
  isReadOnly: boolean;
  openError: string | null;   // last file-open failure message
  graphVisible: boolean;
  graphSplitPercent: number; // 0-100

  openFile: (path: string) => Promise<void>;
  updateContent: (content: string) => void;
  saveFile: () => Promise<void>;
  closeFile: () => void;
  toggleGraph: () => void;
  setGraphVisible: (visible: boolean) => void;
  setSplitPercent: (pct: number) => void;
  reset: () => void;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  activeFilePath: null,
  fileContent: null,
  isDirty: false,
  isLoading: false,
  isReadOnly: false,
  openError: null,
  graphVisible: readLocalBool("vanilla:graphVisible", true),
  graphSplitPercent: Math.min(80, Math.max(20, readLocalNumber("vanilla:graphSplit", 50))),

  openFile: async (path: string) => {
    const state = get();

    // Auto-save current file if dirty
    if (state.isDirty && state.activeFilePath && !state.isReadOnly) {
      await get().saveFile();
    }

    set({ isLoading: true, openError: null });

    try {
      const data = await getFileContent(path);
      set({
        activeFilePath: data.path,
        fileContent: data.content,
        isDirty: false,
        isLoading: false,
        isReadOnly: isWikiVaultPath(path),
        openError: null,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[editor] Failed to open file:", path, msg);
      set({ isLoading: false, openError: `Could not open ${path.split("/").pop()}: ${msg}` });
    }
  },

  updateContent: (content: string) => {
    set({ fileContent: content, isDirty: true });
  },

  saveFile: async () => {
    const { isDirty, isReadOnly, activeFilePath, fileContent } = get();
    if (!isDirty || isReadOnly || !activeFilePath || fileContent === null) return;

    await saveFileContent(activeFilePath, fileContent);
    suppressWatcherPath(activeFilePath);
    set({ isDirty: false });
  },

  closeFile: async () => {
    const state = get();

    // Auto-save if dirty before closing
    if (state.isDirty && state.activeFilePath && !state.isReadOnly) {
      await get().saveFile();
    }

    set({
      activeFilePath: null,
      fileContent: null,
      isDirty: false,
      isReadOnly: false,
    });
  },

  toggleGraph: () => {
    const next = !get().graphVisible;
    localStorage.setItem("vanilla:graphVisible", String(next));
    set({ graphVisible: next });
  },

  setGraphVisible: (visible: boolean) => {
    localStorage.setItem("vanilla:graphVisible", String(visible));
    set({ graphVisible: visible });
  },

  setSplitPercent: (pct: number) => {
    const clamped = Math.min(80, Math.max(20, pct));
    localStorage.setItem("vanilla:graphSplit", String(clamped));
    set({ graphSplitPercent: clamped });
  },

  reset: () => {
    set({
      activeFilePath: null,
      fileContent: null,
      isDirty: false,
      isLoading: false,
      isReadOnly: false,
      openError: null,
    });
  },
}));
