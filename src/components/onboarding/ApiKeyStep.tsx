import { useState } from "react";
import { validateLLM } from "@/api/onboarding";

const PROVIDERS = ["openai", "anthropic", "openrouter", "ollama"] as const;
type Provider = (typeof PROVIDERS)[number];

const DEFAULT_MODELS: Record<Provider, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-5",
  openrouter: "anthropic/claude-sonnet-4.5",
  ollama: "llama3",
};

const PROVIDER_LABELS: Record<Provider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
};

export interface LLMConfig {
  provider: Provider;
  apiKey: string;
  model: string;
  baseUrl?: string;
}

interface ApiKeyStepProps {
  initial?: LLMConfig;
  onNext: (config: LLMConfig) => void;
}

export function ApiKeyStep({ initial, onNext }: ApiKeyStepProps) {
  const [provider, setProvider] = useState<Provider>(initial?.provider ?? "openai");
  const [apiKey, setApiKey] = useState(initial?.apiKey ?? "");
  const [model, setModel] = useState(initial?.model ?? DEFAULT_MODELS.openai);
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? "http://localhost:11434");
  const [testing, setTesting] = useState(false);
  const [validated, setValidated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isOllama = provider === "ollama";

  function handleProviderChange(p: Provider) {
    setProvider(p);
    setModel(DEFAULT_MODELS[p]);
    setValidated(false);
    setError(null);
  }

  async function testConnection() {
    setTesting(true);
    setError(null);
    setValidated(false);
    try {
      const result = await validateLLM(
        provider,
        apiKey,
        isOllama ? baseUrl : undefined,
        model,
      );
      if (result.valid) {
        setValidated(true);
      } else {
        setError(result.error ?? "Connection test failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setTesting(false);
    }
  }

  function handleContinue() {
    onNext({
      provider,
      apiKey,
      model,
      baseUrl: isOllama ? baseUrl : undefined,
    });
  }

  const canTest = isOllama ? !!model : !!apiKey && !!model;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-stone-800">Connect your LLM</h2>
        <p className="mt-1 text-sm text-stone-500">
          Vanilla needs an LLM to generate and maintain your knowledge wiki.
        </p>
      </div>

      {/* Provider */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-stone-700">
          Provider
        </label>
        <select
          value={provider}
          onChange={(e) => handleProviderChange(e.target.value as Provider)}
          className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-800 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABELS[p]}
            </option>
          ))}
        </select>
      </div>

      {/* API Key (not for Ollama) */}
      {!isOllama && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-stone-700">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setValidated(false);
            }}
            placeholder={`Enter your ${PROVIDER_LABELS[provider]} API key`}
            className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
          />
        </div>
      )}

      {/* Base URL (Ollama only) */}
      {isOllama && (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-stone-700">
            Base URL
          </label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              setValidated(false);
            }}
            placeholder="http://localhost:11434"
            className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
          />
        </div>
      )}

      {/* Model */}
      <div>
        <label className="mb-1.5 block text-sm font-medium text-stone-700">
          Model
        </label>
        <input
          type="text"
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            setValidated(false);
          }}
          placeholder="Model name"
          className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
        />
      </div>

      {/* Test Connection */}
      <div className="flex items-center gap-3">
        <button
          onClick={testConnection}
          disabled={!canTest || testing}
          className="rounded-md bg-stone-800 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {testing ? "Testing..." : "Test Connection"}
        </button>
        {validated && (
          <span className="text-sm font-medium text-green-600">
            Connection successful
          </span>
        )}
        {error && (
          <span className="text-sm font-medium text-red-600">{error}</span>
        )}
      </div>

      {/* Continue */}
      <div className="pt-2">
        <button
          onClick={handleContinue}
          disabled={!validated}
          className="w-full rounded-md bg-amber-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
