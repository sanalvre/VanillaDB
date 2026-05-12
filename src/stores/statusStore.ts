/**
 * Status store — polls the sidecar for agent pipeline status.
 *
 * Polls every 5 seconds when the app is active.
 * Used by the bottom bar and proposal tray badge.
 */

import { create } from "zustand";
import { getStatus } from "@/api/sidecar";

interface StatusState {
  agentStatus: "idle" | "running" | "error";
  currentPhase: string | null;
  lastRun: {
    id: string;
    completedAt: number;
    tokensUsed: number;
  } | null;
  pendingProposals: number;
  lastRunWarnings: Array<{ code: string; detail?: string; path?: string }>;
  polling: boolean;
  startPolling: () => void;
  stopPolling: () => void;
  refresh: () => Promise<void>;
}

let pollInterval: ReturnType<typeof setInterval> | null = null;

export const useStatusStore = create<StatusState>((set) => ({
  agentStatus: "idle",
  currentPhase: null,
  lastRun: null,
  pendingProposals: 0,
  lastRunWarnings: [],
  polling: false,

  refresh: async () => {
    try {
      const data = await getStatus();
      set({
        agentStatus: data.agent_status as "idle" | "running" | "error",
        currentPhase: data.current_phase,
        lastRun: data.last_run
          ? {
              id: data.last_run.id,
              completedAt: data.last_run.completed_at,
              tokensUsed: data.last_run.tokens_used,
            }
          : null,
        pendingProposals: data.pending_proposals,
        lastRunWarnings: Array.isArray(data.last_run_warnings) ? data.last_run_warnings : [],
      });
    } catch {
      // Sidecar may be temporarily unavailable
    }
  },

  startPolling: () => {
    if (pollInterval) return; // Already polling
    set({ polling: true });

    // Initial fetch
    useStatusStore.getState().refresh();

    // Poll every 5 seconds
    pollInterval = setInterval(() => {
      useStatusStore.getState().refresh();
    }, 5000);
  },

  stopPolling: () => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    set({ polling: false });
  },
}));
