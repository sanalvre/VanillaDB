import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) return `http://127.0.0.1:${stored}`;
  return `http://127.0.0.1:${useVaultStore.getState().sidecarPort}`;
}

export async function researchTopic(
  topic: string,
  maxPages = 5,
  followCitations = true,
): Promise<string> {
  const res = await fetch(`${baseUrl()}/research/topic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, max_pages: maxPages, follow_citations: followCitations }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Research failed: ${res.status}`);
  }
  const data = await res.json();
  return data.job_id as string;
}

export async function researchUrl(url: string): Promise<string> {
  const res = await fetch(`${baseUrl()}/research/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Research failed: ${res.status}`);
  }
  const data = await res.json();
  return data.job_id as string;
}
