/**
 * SettingsPanel — LLM + Sync configuration.
 *
 * Slide-in panel with two tabs: LLM provider setup and git-based sync.
 */

import { useState, useEffect, useCallback } from "react";
import { getLLMConfig, validateLLM, type LLMConfig } from "@/api/sidecar";
import { SyncPanel } from "./SyncPanel";
import { invoke } from "@tauri-apps/api/core";

type Tab = "llm" | "sync" | "updates";

interface UpdateInfo {
  available: boolean;
  version?: string;
  current_version?: string;
  notes?: string;
}

function UpdatesPanel() {
  const [checkState, setCheckState] = useState<"idle" | "checking" | "done" | "error">("idle");
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [installing, setInstalling] = useState(false);

  const checkForUpdates = useCallback(async () => {
    setCheckState("checking");
    setErrorMsg("");
    setUpdate(null);
    try {
      const result = await invoke<UpdateInfo>("check_for_update");
      setUpdate(result);
      setCheckState("done");
    } catch (e) {
      setErrorMsg(String(e));
      setCheckState("error");
    }
  }, []);

  const doInstall = useCallback(async () => {
    setInstalling(true);
    try {
      await invoke("install_update");
      // App will relaunch — show a message in case relaunch is delayed
    } catch (e) {
      setErrorMsg(String(e));
      setInstalling(false);
    }
  }, []);

  return (
    <div className="space-y-5">
      {/* Current version */}
      <div className="flex items-center justify-between rounded-lg border border-stone-100 bg-stone-50 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-800/50">
        <span className="text-xs text-stone-500 dark:text-zinc-400">Current version</span>
        <span className="font-mono text-xs font-medium text-stone-700 dark:text-zinc-200">0.1.0</span>
      </div>

      {/* Check button */}
      <button
        onClick={checkForUpdates}
        disabled={checkState === "checking" || installing}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-stone-800
                   px-4 py-2.5 text-xs font-medium text-white transition-colors
                   hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-60
                   dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
      >
        {checkState === "checking" ? (
          <>
            <div className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white dark:border-zinc-600/30 dark:border-t-zinc-900" />
            Checking...
          </>
        ) : (
          "Check for Updates"
        )}
      </button>

      {/* Result: up to date */}
      {checkState === "done" && update && !update.available && (
        <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2.5 text-xs text-green-700 dark:bg-green-950/30 dark:text-green-400">
          <div className="h-1.5 w-1.5 rounded-full bg-green-500" />
          You're on the latest version
        </div>
      )}

      {/* Result: update available */}
      {checkState === "done" && update?.available && (
        <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800/50 dark:bg-amber-950/20">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-amber-800 dark:text-amber-300">
              Update available
            </span>
            <span className="font-mono text-xs text-amber-700 dark:text-amber-400">
              v{update.version}
            </span>
          </div>
          {update.notes && (
            <p className="text-[11px] leading-relaxed text-amber-700 dark:text-amber-400 whitespace-pre-wrap">
              {update.notes}
            </p>
          )}
          <button
            onClick={doInstall}
            disabled={installing}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-600
                       px-4 py-2 text-xs font-medium text-white transition-colors
                       hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {installing ? (
              <>
                <div className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white" />
                Downloading & installing...
              </>
            ) : (
              "Download & Install"
            )}
          </button>
          {installing && (
            <p className="text-center text-[11px] text-amber-600 dark:text-amber-400">
              The app will restart automatically after installation.
            </p>
          )}
        </div>
      )}

      {/* Error */}
      {checkState === "error" && (
        <div className="rounded-lg bg-red-50 px-3 py-2.5 dark:bg-red-950/20">
          <p className="text-[11px] text-red-600 dark:text-red-400">
            {errorMsg.includes("PLACEHOLDER") || errorMsg.includes("pubkey")
              ? "Updater not configured — see setup instructions below."
              : errorMsg}
          </p>
        </div>
      )}

      {/* Setup instructions */}
      <div className="space-y-2 rounded-lg border border-stone-100 bg-stone-50 px-3 py-3 dark:border-zinc-800 dark:bg-zinc-800/30">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-stone-400 dark:text-zinc-500">
          First-time setup
        </p>
        <ol className="space-y-1.5 text-[11px] leading-relaxed text-stone-500 dark:text-zinc-500">
          <li>1. Generate a signing keypair:<br />
            <code className="mt-0.5 block rounded bg-stone-100 px-2 py-0.5 font-mono text-[10px] dark:bg-zinc-700">
              npm run tauri -- signer generate -w ~/.tauri/vanilla.key
            </code>
          </li>
          <li>2. Copy the printed public key into <code className="font-mono">src-tauri/tauri.conf.json</code> → <code className="font-mono">plugins.updater.pubkey</code></li>
          <li>3. Add <code className="font-mono">TAURI_SIGNING_PRIVATE_KEY</code> + <code className="font-mono">TAURI_SIGNING_PRIVATE_KEY_PASSWORD</code> to your GitHub repo secrets</li>
          <li>4. Push a version tag (<code className="font-mono">git tag v0.2.0 && git push --tags</code>) to trigger a signed release</li>
        </ol>
      </div>
    </div>
  );
}

const PROVIDERS = [
  {
    id: "openrouter",
    label: "OpenRouter",
    badge: "100+ models",
    models: [
      "openai/gpt-4o",
      "openai/gpt-4o-mini",
      "anthropic/claude-sonnet-4-5",
      "meta-llama/llama-3.1-70b-instruct",
      "google/gemini-flash-1.5",
      "mistralai/mistral-7b-instruct",
    ],
    keyPlaceholder: "sk-or-...",
    docsUrl: "https://openrouter.ai/keys",
  },
  {
    id: "openai",
    label: "OpenAI",
    badge: null,
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    keyPlaceholder: "sk-...",
    docsUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    badge: null,
    models: ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    keyPlaceholder: "sk-ant-...",
    docsUrl: "https://console.anthropic.com/keys",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    badge: "no key",
    models: ["llama3.2", "mistral", "gemma2", "phi3"],
    keyPlaceholder: "No key needed",
    docsUrl: "https://ollama.com",
  },
];

interface SettingsPanelProps {
  onClose: () => void;
}

type Status = "idle" | "validating" | "success" | "error";

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [tab, setTab] = useState<Tab>("llm");
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [loading, setLoading] = useState(true);

  // Form state
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("gpt-4o-mini");
  const [showKey, setShowKey] = useState(false);
  const [transcriptionKey, setTranscriptionKey] = useState("");
  const [showTranscriptionKey, setShowTranscriptionKey] = useState(false);
  const [groqTranscriptionKey, setGroqTranscriptionKey] = useState("");
  const [showGroqKey, setShowGroqKey] = useState(false);

  // Validation state
  const [status, setStatus] = useState<Status>("idle");
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    getLLMConfig()
      .then((c) => {
        setConfig(c);
        setProvider(c.provider);
        setBaseUrl(c.base_url ?? "");
        // Pre-fill model from config
        const m = c.models?.["analysis"] || "gpt-4o-mini";
        setModel(m);
        setTranscriptionKey((c as any).transcription_api_key ?? "");
        setGroqTranscriptionKey((c as any).groq_transcription_key ?? "");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const selectedProvider = PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[0];
  const isOllama = provider === "ollama";

  const handleValidate = useCallback(async () => {
    if (!isOllama && !apiKey.trim()) {
      setStatus("error");
      setStatusMsg("Enter your API key first");
      return;
    }

    setStatus("validating");
    setStatusMsg("");

    try {
      const result = await validateLLM({
        provider,
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || undefined,
        model,
        transcription_api_key: transcriptionKey.trim() || undefined,
        groq_transcription_key: groqTranscriptionKey.trim() || undefined,
      });

      if (result.valid) {
        setStatus("success");
        setStatusMsg("Connected — settings saved");
        // Refresh displayed config
        getLLMConfig().then(setConfig).catch(() => {});
      } else {
        setStatus("error");
        setStatusMsg(result.error ?? "Validation failed");
      }
    } catch {
      setStatus("error");
      setStatusMsg("Could not reach sidecar");
    }
  }, [provider, apiKey, baseUrl, model, isOllama]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/10"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <aside className="fixed right-0 top-0 z-50 flex h-full w-80 flex-col border-l border-stone-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900 dark:shadow-black/40">
        {/* Header */}
        <div className="border-b border-stone-100 px-4 pt-3 dark:border-zinc-800">
          <div className="flex items-center justify-between pb-2">
            <h2 className="text-sm font-semibold text-stone-800 dark:text-zinc-100">Settings</h2>
            <button
              onClick={onClose}
              className="rounded p-1 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              aria-label="Close settings"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <line x1="2" y1="2" x2="12" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                <line x1="12" y1="2" x2="2" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          {/* Tab bar */}
          <div className="flex gap-0">
            {(["llm", "sync", "updates"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`border-b-2 px-3 pb-2 text-xs font-medium capitalize transition-colors ${
                  tab === t
                    ? "border-stone-800 text-stone-800 dark:border-zinc-300 dark:text-zinc-100"
                    : "border-transparent text-stone-400 hover:text-stone-600 dark:text-zinc-500 dark:hover:text-zinc-300"
                }`}
              >
                {t === "llm" ? "LLM" : t === "updates" ? "Updates" : "Sync"}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
          {/* ── Updates tab ──────────────────────────── */}
          {tab === "updates" && <UpdatesPanel />}

          {/* ── Sync tab ─────────────────────────────── */}
          {tab === "sync" && <SyncPanel />}

          {/* ── LLM tab ──────────────────────────────── */}
          {tab === "llm" && <>
          {/* Current status banner */}
          {!loading && config && (
            <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
              config.api_key_set
                ? "bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                : "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400"
            }`}>
              <div className={`h-1.5 w-1.5 rounded-full ${
                config.api_key_set ? "bg-green-500" : "bg-amber-500"
              }`} />
              {config.api_key_set
                ? `Connected · ${config.provider} · ${config.api_key_masked}`
                : "No API key set — agent pipeline will not run"
              }
            </div>
          )}

          {/* Provider selection */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
              Provider
            </label>
            <div className="grid grid-cols-2 gap-1.5">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    setProvider(p.id);
                    setStatus("idle");
                    setStatusMsg("");
                    setModel(p.models[0]);
                  }}
                  className={`relative rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    provider === p.id
                      ? "border-stone-800 bg-stone-800 text-white dark:border-zinc-300 dark:bg-zinc-200 dark:text-zinc-900"
                      : "border-stone-200 text-stone-600 hover:border-stone-300 hover:bg-stone-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-600 dark:hover:bg-zinc-800"
                  }`}
                >
                  <span className="block font-medium">{p.label}</span>
                  {p.badge && (
                    <span className={`mt-0.5 block text-[10px] leading-tight ${
                      provider === p.id ? "text-stone-300 dark:text-zinc-600" : "text-stone-400 dark:text-zinc-600"
                    }`}>
                      {p.badge}
                    </span>
                  )}
                </button>
              ))}
            </div>
            {/* OpenRouter callout */}
            {provider !== "openrouter" && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-400">
                <span className="font-medium">Tip:</span> OpenRouter gives you access to 100+ models
                (GPT-4o, Claude, Llama, Gemini) with a single API key.{" "}
                <button
                  onClick={() => { setProvider("openrouter"); setModel("openai/gpt-4o"); setStatus("idle"); setStatusMsg(""); }}
                  className="font-medium underline underline-offset-2 hover:text-amber-900"
                >
                  Switch to OpenRouter ↗
                </button>
              </div>
            )}
          </div>

          {/* API key */}
          {!isOllama && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                  API Key
                </label>
                <a
                  href={selectedProvider.docsUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-stone-400 underline-offset-2 hover:text-stone-600 hover:underline dark:text-zinc-600 dark:hover:text-zinc-300"
                >
                  Get key ↗
                </a>
              </div>
              <div className="relative">
                <input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => { setApiKey(e.target.value); setStatus("idle"); }}
                  placeholder={selectedProvider.keyPlaceholder}
                  className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 pr-9
                             text-xs text-stone-800 placeholder:text-stone-400
                             focus:border-stone-400 focus:bg-white focus:outline-none transition-colors
                             dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                             dark:placeholder:text-zinc-600 dark:focus:border-zinc-500 dark:focus:bg-zinc-800"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((s) => !s)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
                  aria-label={showKey ? "Hide key" : "Show key"}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    {showKey ? (
                      <>
                        <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                        <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                      </>
                    ) : (
                      <>
                        <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                      </>
                    )}
                  </svg>
                </button>
              </div>
            </div>
          )}

          {/* Transcription API Key — for voice input when not using OpenAI as LLM */}
          {!isOllama && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                Voice Transcription Key
              </label>
              {provider === "openai" ? (
                <p className="text-[11px] text-stone-400 dark:text-zinc-600">
                  Uses your LLM key above — no separate key needed.
                </p>
              ) : (
                <>
                  <div className="relative">
                    <input
                      type={showTranscriptionKey ? "text" : "password"}
                      value={transcriptionKey}
                      onChange={(e) => { setTranscriptionKey(e.target.value); setStatus("idle"); }}
                      placeholder="sk-... (OpenAI key, optional)"
                      className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 pr-9
                                 text-xs text-stone-800 placeholder:text-stone-400
                                 focus:border-stone-400 focus:bg-white focus:outline-none transition-colors
                                 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                                 dark:placeholder:text-zinc-600 dark:focus:border-zinc-500 dark:focus:bg-zinc-800"
                    />
                    <button
                      type="button"
                      onClick={() => setShowTranscriptionKey((s) => !s)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
                      aria-label={showTranscriptionKey ? "Hide key" : "Show key"}
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                        {showTranscriptionKey ? (
                          <>
                            <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                            <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                            <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                          </>
                        ) : (
                          <>
                            <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                            <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                          </>
                        )}
                      </svg>
                    </button>
                  </div>
                  <p className="text-[11px] text-stone-400 dark:text-zinc-600">
                    Optional OpenAI key for Whisper transcription (takes priority over Groq).
                  </p>
                </>
              )}
            </div>
          )}

          {/* Groq transcription key — free Whisper alternative */}
          {!isOllama && provider !== "openai" && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                  Groq Voice Key
                </label>
                <a
                  href="https://console.groq.com/keys"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] text-stone-400 underline-offset-2 hover:text-stone-600 hover:underline dark:text-zinc-600 dark:hover:text-zinc-300"
                >
                  Get key ↗
                </a>
              </div>
              <div className="relative">
                <input
                  type={showGroqKey ? "text" : "password"}
                  value={groqTranscriptionKey}
                  onChange={(e) => { setGroqTranscriptionKey(e.target.value); setStatus("idle"); }}
                  placeholder="gsk_... (Groq key, optional)"
                  className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 pr-9
                             text-xs text-stone-800 placeholder:text-stone-400
                             focus:border-stone-400 focus:bg-white focus:outline-none transition-colors
                             dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                             dark:placeholder:text-zinc-600 dark:focus:border-zinc-500 dark:focus:bg-zinc-800"
                />
                <button
                  type="button"
                  onClick={() => setShowGroqKey((s) => !s)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
                  aria-label={showGroqKey ? "Hide key" : "Show key"}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    {showGroqKey ? (
                      <>
                        <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                        <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                      </>
                    ) : (
                      <>
                        <path d="M1 8C1 8 4 3 8 3s7 5 7 5-3 5-7 5-7-5-7-5z" stroke="currentColor" strokeWidth="1.2" fill="none" />
                        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2" />
                      </>
                    )}
                  </svg>
                </button>
              </div>
              <p className="text-[11px] text-stone-400 dark:text-zinc-600">
                Free Groq Whisper (whisper-large-v3) — used when no OpenAI transcription key is set.
              </p>
            </div>
          )}

          {/* Ollama base URL */}
          {isOllama && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
                Ollama URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => { setBaseUrl(e.target.value); setStatus("idle"); }}
                placeholder="http://localhost:11434"
                className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2
                           text-xs text-stone-800 placeholder:text-stone-400
                           focus:border-stone-400 focus:bg-white focus:outline-none transition-colors
                           dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                           dark:placeholder:text-zinc-600 dark:focus:border-zinc-500"
              />
              <p className="text-[11px] text-stone-400 dark:text-zinc-600">
                Make sure Ollama is running locally
              </p>
            </div>
          )}

          {/* Model selection */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500">
              Default Model
            </label>
            <select
              value={model}
              onChange={(e) => { setModel(e.target.value); setStatus("idle"); }}
              className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2
                         text-xs text-stone-700 focus:border-stone-400 focus:outline-none
                         transition-colors dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                         dark:focus:border-zinc-500"
            >
              {selectedProvider.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <p className="text-[11px] text-stone-400 dark:text-zinc-600">
              Used for analysis and proposal generation
            </p>
          </div>

          {/* Validate & save button */}
          <div className="space-y-2">
            <button
              onClick={handleValidate}
              disabled={status === "validating"}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-stone-800
                         px-4 py-2.5 text-xs font-medium text-white transition-colors
                         hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-60
                         dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
            >
              {status === "validating" ? (
                <>
                  <div className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white" />
                  Testing connection...
                </>
              ) : (
                "Test & Save"
              )}
            </button>

            {/* Status message */}
            {statusMsg && (
              <p className={`text-center text-[11px] ${
                status === "success" ? "text-green-600" : "text-red-500"
              }`}>
                {status === "success" ? "✓ " : "✗ "}{statusMsg}
              </p>
            )}
          </div>
          </> /* end LLM tab */}
        </div>

        {/* Footer */}
        <div className="border-t border-stone-100 px-4 py-3 text-[11px] text-stone-400 dark:border-zinc-800 dark:text-zinc-600">
          {tab === "llm"
            ? "Keys are stored locally in your vault config file only."
            : tab === "sync"
            ? "Sync uses git — your vault history is preserved across all changes."
            : "Updates are signed and verified before installation."}
        </div>
      </aside>
    </>
  );
}
