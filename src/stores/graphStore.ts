/**
 * Graph store — manages knowledge graph data independently from the editor.
 *
 * Isolated to prevent cross-renders between editor and graph components.
 * Polls every 30 seconds while active.
 *
 * Also manages cluster assignments fetched from /wiki/graph/clusters.
 */

import { create } from "zustand";
import { getGraph, getGraphClusters } from "@/api/sidecar";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  path: string;
  category: string;
  lastBatch: string;
  citationCount?: number;  // number of source docs citing this concept
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface ClusterLabel {
  cluster_id: number;
  label: string;
  member_count: number;
}

export type ClusterStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; clusterCount: number }
  | { state: "error"; message: string };

interface GraphState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  latestBatchId: string | null;
  isLoading: boolean;
  polling: boolean;

  // Cluster data — keyed by method for independent caching
  topologyClusters: Record<string, number>;   // node_id → cluster_id
  semanticClusters: Record<string, number>;
  clusterLabels: Record<number, string>;       // cluster_id → human label
  clusterStatus: ClusterStatus;

  fetchGraph: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  fetchClusters: (method: "topology" | "semantic") => Promise<void>;
}

// ─── Module-level poll handle (outside store to avoid triggering re-renders) ─

let pollInterval: ReturnType<typeof setInterval> | null = null;

// ─── Store ───────────────────────────────────────────────────────────────────

export const useGraphStore = create<GraphState>((set) => ({
  nodes: [],
  edges: [],
  latestBatchId: null,
  isLoading: false,
  polling: false,

  topologyClusters: {},
  semanticClusters: {},
  clusterLabels: {},
  clusterStatus: { state: "idle" },

  // ── Graph data ────────────────────────────────────────────────────────────

  fetchGraph: async () => {
    set({ isLoading: true });
    try {
      const data = await getGraph();

      // Build citation count map from source_map
      const citationCount: Record<string, number> = {};
      for (const articles of Object.values(data.source_map ?? {})) {
        for (const art of articles) {
          // Match by article path suffix against node paths
          citationCount[art] = (citationCount[art] ?? 0) + 1;
        }
      }

      const nodes: GraphNode[] = data.nodes.map((n) => ({
        id: n.id,
        label: n.label,
        path: n.path,
        category: n.category,
        lastBatch: n.last_batch,   // API returns snake_case from SQLite
        citationCount: citationCount[n.path] ?? 0,
      }));

      const edges: GraphEdge[] = data.edges.map((e) => ({
        source: e.source,
        target: e.target,
        type: e.type,
      }));

      // Derive latest batch id — lexicographic max across all node lastBatch values
      let latestBatchId: string | null = null;
      for (const node of nodes) {
        if (node.lastBatch && (!latestBatchId || node.lastBatch > latestBatchId)) {
          latestBatchId = node.lastBatch;
        }
      }

      set({ nodes, edges, latestBatchId, isLoading: false });
    } catch {
      set({ isLoading: false });
    }
  },

  startPolling: () => {
    if (pollInterval) return;
    set({ polling: true });
    useGraphStore.getState().fetchGraph();
    pollInterval = setInterval(() => {
      useGraphStore.getState().fetchGraph();
    }, 30_000);
  },

  stopPolling: () => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    set({ polling: false });
  },

  // ── Cluster data ──────────────────────────────────────────────────────────

  fetchClusters: async (method) => {
    set({ clusterStatus: { state: "loading" } });
    try {
      const data = await getGraphClusters(method);

      // Build cluster_id → label map from the clusters array
      const clusterLabels: Record<number, string> = {};
      for (const c of data.clusters) {
        clusterLabels[c.cluster_id] = c.label;
      }

      if (method === "topology") {
        set({
          topologyClusters: data.assignments,
          clusterLabels,
          clusterStatus: {
            state: "ready",
            clusterCount: data.clusters.length,
          },
        });
      } else {
        set({
          semanticClusters: data.assignments,
          clusterLabels,
          clusterStatus: {
            state: "ready",
            clusterCount: data.clusters.length,
          },
        });
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Clustering failed";
      set({ clusterStatus: { state: "error", message: msg } });
    }
  },
}));
