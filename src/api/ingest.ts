/**
 * Ingestion API client — file uploads and URL ingestion.
 */

import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const port = useVaultStore.getState().sidecarPort;
  return `http://127.0.0.1:${port}`;
}

export async function ingestFile(filePath: string): Promise<{ job_id: string }> {
  const res = await fetch(`${baseUrl()}/ingest/file?file_path=${encodeURIComponent(filePath)}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Ingest failed");
  }
  return res.json();
}

export async function ingestUrl(url: string): Promise<{ job_id: string }> {
  const res = await fetch(`${baseUrl()}/ingest/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "URL ingest failed");
  }
  return res.json();
}

export async function getIngestStatus(jobId: string): Promise<{
  job_id: string;
  status: "pending" | "processing" | "complete" | "error";
  progress: number;
  output_path: string | null;
  error: string | null;
  source_type: string;
}> {
  const res = await fetch(`${baseUrl()}/ingest/status/${jobId}`);
  return res.json();
}

export async function getActiveIngests(): Promise<{
  jobs: Array<{
    job_id: string;
    status: string;
    progress: number;
    source_type: string;
  }>;
}> {
  const res = await fetch(`${baseUrl()}/ingest/active`);
  return res.json();
}

export async function getCapabilities(): Promise<{
  gpu: boolean;
  gpu_type: "cuda" | "mps" | "none";
  python_version: string;
}> {
  const res = await fetch(`${baseUrl()}/system/capabilities`);
  return res.json();
}
