/**
 * Sidecar API client — all HTTP calls to the Python FastAPI backend.
 *
 * Every function here maps to an endpoint defined in docs/wiki/api-reference.md.
 * The base URL is dynamically set from the sidecar port.
 */

import { useVaultStore } from "@/stores/vaultStore";
import { normalizePath } from "./paths";

function baseUrl(): string {
  // Check for override in query params or localStorage (for dev/testing)
  const params = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  const portOverride = params.get("port");
  if (portOverride) {
    localStorage.setItem("vanilla:sidecarPort", portOverride);
  }

  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) {
    return `http://127.0.0.1:${stored}`;
  }

  const port = useVaultStore.getState().sidecarPort;
  return `http://127.0.0.1:${port}`;
}

// ─── System ────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ status: string }> {
  const res = await fetch(`${baseUrl()}/health`);
  return res.json();
}

export async function getStatus(): Promise<{
  agent_status: string;
  current_phase: string | null;
  last_run: { id: string; completed_at: number; tokens_used: number } | null;
  pending_proposals: number;
  last_run_warnings: Array<{ code: string; detail?: string; path?: string }>;
}> {
  const res = await fetch(`${baseUrl()}/status`);
  return res.json();
}

// ─── Vault ─────────────────────────────────────────────────────────

export async function getVaultStructure(): Promise<{
  initialized: boolean;
  clean_vault_path: string | null;
  wiki_vault_path: string | null;
  warnings: string[];
}> {
  const res = await fetch(`${baseUrl()}/vault/structure`);
  return res.json();
}

export async function createVault(
  basePath: string,
  ontologyContent?: string,
  agentsContent?: string,
): Promise<{
  success: boolean;
  clean_vault_path: string;
  wiki_vault_path: string;
}> {
  const res = await fetch(`${baseUrl()}/vault/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_path: basePath,
      ontology_content: ontologyContent,
      agents_content: agentsContent,
    }),
  });
  if (!res.ok) throw new Error(`Vault creation failed: ${res.statusText}`);
  return res.json();
}

// ─── File Events ───────────────────────────────────────────────────

export async function sendFileEvent(
  path: string,
  eventType: "create" | "modify" | "delete",
): Promise<{ queued: boolean; pending_count: number }> {
  const res = await fetch(`${baseUrl()}/internal/file-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: normalizePath(path),
      event_type: eventType,
      timestamp: Math.floor(Date.now() / 1000),
    }),
  });
  return res.json();
}

export async function runAgentNow(): Promise<{ dispatched: number }> {
  const res = await fetch(`${baseUrl()}/agent/run-now`, { method: "POST" });
  return res.json();
}

// ─── Graph ─────────────────────────────────────────────────────────

export async function getGraph(): Promise<{
  nodes: Array<{
    id: string;
    label: string;
    path: string;
    category: string;
    last_batch: string;   // snake_case — matches SQLite column name from backend
  }>;
  edges: Array<{ source: string; target: string; type: string }>;
  source_map: Record<string, string[]>;
}> {
  const res = await fetch(`${baseUrl()}/wiki/graph`);
  return res.json();
}

export async function getStaleArticles(): Promise<{
  stale_articles: Array<{
    article_path: string;
    source_path: string;
    flagged_at: number;
  }>;
}> {
  const res = await fetch(`${baseUrl()}/wiki/stale`);
  return res.json();
}

// ─── Proposals ─────────────────────────────────────────────────────

export async function getProposals(): Promise<{
  batches: Array<{
    batch_id: string;
    summary: string;
    status: string;
    batch_path: string;
    articles: Array<{
      filename: string;
      title: string;
      action: string;
      status: string;
    }>;
    created_at: number;
  }>;
}> {
  const res = await fetch(`${baseUrl()}/proposals`);
  return res.json();
}

export async function approveProposal(
  batchId: string,
): Promise<{ batch_id: string; status: string; articles_written: number; errors: string[] }> {
  const res = await fetch(`${baseUrl()}/proposals/${batchId}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Approve failed: ${res.statusText}`);
  return res.json();
}

export async function rejectProposal(
  batchId: string,
  reason?: string,
): Promise<{ batch_id: string; status: string }> {
  const res = await fetch(`${baseUrl()}/proposals/${batchId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error(`Reject failed: ${res.statusText}`);
  return res.json();
}

export async function getProposalArticle(
  batchId: string,
  filename: string,
): Promise<{ filename: string; content: string }> {
  const res = await fetch(
    `${baseUrl()}/proposals/${batchId}/article/${encodeURIComponent(filename)}`,
  );
  if (!res.ok) throw new Error(`Could not load article: ${res.statusText}`);
  return res.json();
}

export async function saveProposalArticle(
  batchId: string,
  filename: string,
  content: string,
): Promise<{ success: boolean; filename: string }> {
  const res = await fetch(
    `${baseUrl()}/proposals/${batchId}/article/${encodeURIComponent(filename)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  );
  if (!res.ok) throw new Error(`Could not save article: ${res.statusText}`);
  return res.json();
}

// ─── Search ────────────────────────────────────────────────────────

export async function search(
  query: string,
  vault: "all" | "clean" | "wiki" = "all",
  limit: number = 20,
): Promise<{
  results: Array<{
    path: string;
    vault: string;
    title: string;
    snippet: string;
    score: number;
  }>;
}> {
  const params = new URLSearchParams({ q: query, vault, limit: String(limit) });
  const res = await fetch(`${baseUrl()}/search?${params}`);
  return res.json();
}

// ─── Files ────────────────────────────────────────────────────────

export interface FileTreeNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children: FileTreeNode[];
}

export async function getVaultFiles(): Promise<{ tree: FileTreeNode[]; tree_hash?: string }> {
  const res = await fetch(`${baseUrl()}/vault/files`);
  return res.json();
}

export async function getFileContent(path: string): Promise<{ path: string; content: string }> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${baseUrl()}/vault/file?${params}`);
  if (!res.ok) throw new Error(`Failed to load file: ${res.statusText}`);
  return res.json();
}

export async function deleteVaultFile(
  path: string,
): Promise<{ success: boolean; trash_path: string }> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${baseUrl()}/vault/file?${params}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

export async function renameVaultFile(
  path: string,
  newName: string,
): Promise<{ success: boolean; new_path: string }> {
  const res = await fetch(`${baseUrl()}/vault/file/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, new_name: newName }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

export async function createVaultFile(
  path: string,
  content = "",
): Promise<{ success: boolean; path: string }> {
  const res = await fetch(`${baseUrl()}/vault/file/new`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

export async function revealInExplorer(
  path: string,
): Promise<{ success: boolean }> {
  const params = new URLSearchParams({ path });
  const res = await fetch(`${baseUrl()}/vault/reveal?${params}`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

export async function saveFileContent(
  path: string,
  content: string,
): Promise<{ success: boolean; path: string }> {
  const res = await fetch(`${baseUrl()}/vault/file`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  if (!res.ok) throw new Error(`Failed to save file: ${res.statusText}`);
  return res.json();
}

// ─── LLM Config ────────────────────────────────────────────────────

export interface LLMConfig {
  provider: string;
  api_key_set: boolean;
  api_key_masked: string;
  base_url: string | null;
  models: Record<string, string>;
  max_tokens_per_run: number;
  transcription_api_key_set?: boolean;
  transcription_api_key_masked?: string;
  groq_transcription_key_set?: boolean;
  groq_transcription_key_masked?: string;
}

export async function getLLMConfig(): Promise<LLMConfig> {
  const res = await fetch(`${baseUrl()}/llm/config`);
  return res.json();
}

export async function validateLLM(payload: {
  provider: string;
  api_key: string;
  base_url?: string;
  model?: string;
  transcription_api_key?: string;
  groq_transcription_key?: string;
}): Promise<{ valid: boolean; error: string | null }> {
  const res = await fetch(`${baseUrl()}/llm/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// ─── Sync ──────────────────────────────────────────────────────────

export interface SyncStatus {
  is_repo: boolean;
  has_remote: boolean;
  remote_url: string | null;
  last_commit_hash: string | null;
  last_commit_message: string | null;
  last_commit_time: number | null;
  dirty_files: number;
  ahead: number;
  behind: number;
  branch: string | null;
  error: string | null;
}

export interface SyncActionResult {
  success: boolean;
  committed: boolean;
  pushed: boolean;
  files_changed: number;
  error: string | null;
}

export async function getSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(`${baseUrl()}/sync/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function configureSyncRemote(remoteUrl: string): Promise<{ success: boolean; remote_url: string }> {
  const res = await fetch(`${baseUrl()}/sync/configure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ remote_url: remoteUrl }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function syncPush(message?: string): Promise<SyncActionResult> {
  const params = message ? `?message=${encodeURIComponent(message)}` : "";
  const res = await fetch(`${baseUrl()}/sync/push${params}`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function syncPull(): Promise<SyncActionResult> {
  const res = await fetch(`${baseUrl()}/sync/pull`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Graph Clustering ──────────────────────────────────────────────

export interface ClusterEntry {
  cluster_id: number;
  label: string;
  member_count: number;
}

export interface GraphClustersResponse {
  method: "topology" | "semantic";
  clusters: ClusterEntry[];
  assignments: Record<string, number>;  // node_id → cluster_id
  computed_at: number;
}

export async function getGraphClusters(
  method: "topology" | "semantic" = "topology",
  recompute = false,
): Promise<GraphClustersResponse> {
  const params = new URLSearchParams({ method });
  if (recompute) params.set("recompute", "true");
  const res = await fetch(`${baseUrl()}/wiki/graph/clusters?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Cluster request failed (${res.status})`);
  }
  return res.json();
}

export async function refreshNodeEmbeddings(): Promise<{ queued: boolean }> {
  const res = await fetch(`${baseUrl()}/wiki/graph/embeddings/refresh`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Embedding refresh failed: ${res.statusText}`);
  return res.json();
}

// ─── Runs ──────────────────────────────────────────────────────────

export async function getRuns(
  limit: number = 20,
  offset: number = 0,
): Promise<{
  runs: Array<{
    run_id: string;
    trigger_path: string | null;
    status: string;
    started_at: number;
    completed_at: number | null;
    tokens_used: number;
  }>;
}> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(`${baseUrl()}/runs?${params}`);
  return res.json();
}
