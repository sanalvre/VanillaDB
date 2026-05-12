/**
 * Graph settings store — persisted user preferences for the graph panel.
 *
 * All settings survive page reloads via localStorage under the key
 * "vanilla:graphSettings". Defaults are chosen to give a rich out-of-the-box
 * experience while still being individually togglable.
 */

import { create } from "zustand";

// ─── Types ───────────────────────────────────────────────────────────────────

export type ColorMode =
  | "category"          // default — color by concept category
  | "cluster-topology"  // color by wikilink-community cluster
  | "cluster-semantic"  // color by embedding-similarity cluster
  | "uniform";          // all nodes same neutral color

export type NodeSizeMode =
  | "degree"    // default — larger = more connections
  | "citations" // larger = more source documents cite this concept
  | "uniform";  // all nodes same size

export interface GraphSettings {
  colorMode: ColorMode;
  nodeSizeMode: NodeSizeMode;
  showEdgeParticles: boolean;
  showEdgeTypeColors: boolean;   // color edges by relationship type
  showEdgeLabels: boolean;       // show type label as canvas tooltip
  showHulls: boolean;            // convex hull overlay per cluster
  forceGrouping: boolean;        // soft forceX/Y to drift clusters apart
  clusterMode: "none" | "topology" | "semantic";
  labelZoomThreshold: number;    // scale at which hub labels appear (0.4–2.0)
  dimUnhoveredNodes: boolean;    // darken non-neighbor nodes on hover
}

const STORAGE_KEY = "vanilla:graphSettings";

const DEFAULTS: GraphSettings = {
  colorMode: "category",
  nodeSizeMode: "degree",
  showEdgeParticles: true,
  showEdgeTypeColors: true,
  showEdgeLabels: true,
  showHulls: true,
  forceGrouping: false,
  clusterMode: "none",
  labelZoomThreshold: 0.8,
  dimUnhoveredNodes: true,
};

// ─── Persistence helpers ─────────────────────────────────────────────────────

function loadFromStorage(): GraphSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<GraphSettings>;
    // Merge with defaults so newly added settings don't come up undefined
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveToStorage(settings: GraphSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Storage quota exceeded or private browsing — silently ignore
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

interface GraphSettingsState extends GraphSettings {
  set: <K extends keyof GraphSettings>(key: K, value: GraphSettings[K]) => void;
  reset: () => void;
}

export const useGraphSettingsStore = create<GraphSettingsState>((set) => ({
  ...loadFromStorage(),

  set: (key, value) => {
    set((state) => {
      const next = { ...state, [key]: value };
      saveToStorage(next as GraphSettings);
      return { [key]: value };
    });
  },

  reset: () => {
    saveToStorage(DEFAULTS);
    set({ ...DEFAULTS });
  },
}));
