/**
 * Onboarding API client — LLM validation and ontology generation.
 */

import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const port = useVaultStore.getState().sidecarPort;
  return `http://127.0.0.1:${port}`;
}

export interface ValidateLLMResponse {
  valid: boolean;
  error?: string;
}

export interface GenerateOntologyResponse {
  ontology_md: string;
  agents_md: string;
  suggested_categories: string[];
}

export async function validateLLM(
  provider: string,
  apiKey: string,
  baseUrlOverride?: string,
  model?: string,
): Promise<ValidateLLMResponse> {
  const res = await fetch(`${baseUrl()}/llm/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider,
      api_key: apiKey,
      base_url: baseUrlOverride,
      model,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    return { valid: false, error: err.detail || "Validation request failed" };
  }
  return res.json();
}

export async function generateOntology(
  description: string,
  provider: string,
  model: string,
  apiKey: string,
  baseUrlOverride?: string,
): Promise<GenerateOntologyResponse> {
  const res = await fetch(`${baseUrl()}/onboarding/generate-ontology`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      description,
      provider,
      model,
      api_key: apiKey,
      base_url: baseUrlOverride,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Ontology generation failed");
  }
  return res.json();
}
