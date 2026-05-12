import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) return `http://127.0.0.1:${stored}`;
  return `http://127.0.0.1:${useVaultStore.getState().sidecarPort}`;
}

export interface VoiceModel {
  size: "tiny" | "base" | "small" | "medium";
  downloaded: boolean;
}

/** Start capturing audio immediately (for hold-to-talk or button-toggle). */
export async function startRecording(modelSize = "base"): Promise<void> {
  const res = await fetch(`${baseUrl()}/voice/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_size: modelSize }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Voice start failed: ${res.status}`);
  }
}

/** Stop the active recording and return the transcript. */
export async function stopRecording(): Promise<{ transcript: string; durationMs: number }> {
  const res = await fetch(`${baseUrl()}/voice/stop`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Voice stop failed: ${res.status}`);
  }
  const data = await res.json();
  return { transcript: data.transcript, durationMs: data.duration_ms };
}

export async function recordAndTranscribe(
  durationS: number,
  modelSize = "base",
): Promise<{ transcript: string; durationMs: number }> {
  const res = await fetch(`${baseUrl()}/voice/record`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_s: durationS, model_size: modelSize }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Voice record failed: ${res.status}`);
  }
  return res.json();
}

export async function getVoiceModels(): Promise<VoiceModel[]> {
  const res = await fetch(`${baseUrl()}/voice/models`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Voice models failed: ${res.status}`);
  }
  const data = await res.json();
  return data.models as VoiceModel[];
}
