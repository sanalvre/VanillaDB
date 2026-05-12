/**
 * Agent API client — communicates with the /agent/* and /voice/transcribe endpoints.
 */

import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) return `http://127.0.0.1:${stored}`;
  return `http://127.0.0.1:${useVaultStore.getState().sidecarPort}`;
}

export interface AgentInstructResult {
  /** Present for file-modifying operations */
  batch_id?: string;
  operation_type?: string;
  summary?: string;
  /** Present for search operations */
  answer?: string;
  sources?: string[];
  /** Present for graph_settings operations — partial GraphSettings delta to apply */
  settings?: Record<string, unknown>;
}

export interface AgentHistoryEntry {
  batch_id: string;
  summary: string;
  status: "pending" | "processing" | "approved" | "rejected";
  created_at: number;
  article_count: number;
}

export interface TranscribeModeResult {
  available: boolean;
  method: "whisper" | "speech_api";
}

/** Execute an agent instruction. Returns proposal info or a search answer. */
export async function instructAgent(
  instruction: string,
  filePath: string | null,
  graphNeighbors: string[],
): Promise<AgentInstructResult> {
  const res = await fetch(`${baseUrl()}/agent/instruct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      instruction,
      file_path: filePath,
      graph_neighbors: graphNeighbors,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Agent instruction failed: ${res.status}`);
  }
  return res.json();
}

/** Fetch the last 5 agent-created proposals. */
export async function getAgentHistory(): Promise<AgentHistoryEntry[]> {
  const res = await fetch(`${baseUrl()}/agent/history`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.history ?? [];
}

/** Check whether the sidecar supports server-side Whisper transcription. */
export async function getTranscribeMode(): Promise<TranscribeModeResult> {
  try {
    const res = await fetch(`${baseUrl()}/voice/transcribe-mode`);
    if (!res.ok) return { available: false, method: "speech_api" };
    return res.json();
  } catch {
    return { available: false, method: "speech_api" };
  }
}

/** Upload an audio blob for server-side transcription. Returns transcript or null if 501. */
export async function transcribeBlob(blob: Blob): Promise<string | null> {
  const form = new FormData();
  form.append("file", blob, "audio.webm");

  const res = await fetch(`${baseUrl()}/voice/transcribe`, {
    method: "POST",
    body: form,
  });

  if (res.status === 501) return null; // Signal: use Web Speech API fallback
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Transcription failed: ${res.status}`);
  }
  const data = await res.json();
  return data.transcript as string;
}
