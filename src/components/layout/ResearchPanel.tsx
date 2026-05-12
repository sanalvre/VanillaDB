/**
 * ResearchPanel — supervised browser research.
 * User enters a topic or URL; the sidecar uses Playwright to fetch and
 * structure content into clean-vault/raw/research/, triggering the
 * normal agent pipeline.
 */

import { useState, useCallback, memo } from "react";
import { researchTopic, researchUrl } from "@/api/research";

interface ResearchPanelProps {
  onIngestStarted?: (jobId: string, source: string) => void;
}

export const ResearchPanel = memo(function ResearchPanel({
  onIngestStarted,
}: ResearchPanelProps) {
  const [mode, setMode] = useState<"topic" | "url">("topic");
  const [topic, setTopic] = useState("");
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(5);
  const [followCitations, setFollowCitations] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = useCallback(async () => {
    const input = mode === "topic" ? topic.trim() : url.trim();
    if (!input) return;

    setLoading(true);
    setError(null);
    try {
      let jobId: string;
      if (mode === "topic") {
        jobId = await researchTopic(input, maxPages, followCitations);
        onIngestStarted?.(jobId, `Research: ${input}`);
      } else {
        jobId = await researchUrl(input);
        onIngestStarted?.(jobId, url);
      }
      setSubmitted(true);
      setTopic("");
      setUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Research failed");
    } finally {
      setLoading(false);
    }
  }, [mode, topic, url, maxPages, followCitations, onIngestStarted]);

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Header */}
      <div>
        <p className="text-xs font-semibold text-stone-700 dark:text-zinc-300">Browser Research</p>
        <p className="mt-0.5 text-[11px] text-stone-400 dark:text-zinc-600">
          Fetch and structure web content into your vault.
        </p>
      </div>

      {/* Mode toggle */}
      <div className="flex gap-1 rounded-md bg-stone-100/60 p-0.5 dark:bg-zinc-800/60">
        {(["topic", "url"] as const).map((m) => (
          <button
            key={m}
            onClick={() => { setMode(m); setSubmitted(false); setError(null); }}
            className={`flex-1 rounded px-2 py-1 text-[11px] font-medium transition-colors ${
              mode === m
                ? "bg-white text-stone-800 shadow-sm dark:bg-zinc-700 dark:text-zinc-100"
                : "text-stone-500 hover:text-stone-700 dark:text-zinc-500 dark:hover:text-zinc-300"
            }`}
          >
            {m === "topic" ? "Topic" : "URL"}
          </button>
        ))}
      </div>

      {/* Input */}
      {mode === "topic" ? (
        <div className="flex flex-col gap-2">
          <input
            type="text"
            value={topic}
            onChange={(e) => { setTopic(e.target.value); setSubmitted(false); }}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder="e.g. transformer attention mechanism"
            className="w-full rounded-md border border-stone-200/70 bg-white/60 px-2.5 py-1.5 text-xs
                       text-stone-800 placeholder:text-stone-400 focus:border-amber-400 focus:outline-none
                       dark:border-zinc-700/70 dark:bg-zinc-800/60 dark:text-zinc-200
                       dark:placeholder:text-zinc-600 dark:focus:border-amber-500"
          />
          {/* Depth options */}
          <div className="flex flex-col gap-1.5 rounded-md bg-stone-50/60 p-2 dark:bg-zinc-800/40">
            <label className="flex items-center gap-2 text-[11px] text-stone-600 dark:text-zinc-400">
              <input
                type="range"
                min={1}
                max={10}
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
                className="w-full accent-amber-500"
              />
              <span className="w-16 shrink-0 text-right">{maxPages} pages</span>
            </label>
            <label className="flex items-center gap-2 text-[11px] text-stone-600 dark:text-zinc-400 cursor-pointer">
              <input
                type="checkbox"
                checked={followCitations}
                onChange={(e) => setFollowCitations(e.target.checked)}
                className="accent-amber-500"
              />
              Follow citations
            </label>
          </div>
        </div>
      ) : (
        <input
          type="url"
          value={url}
          onChange={(e) => { setUrl(e.target.value); setSubmitted(false); }}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="https://..."
          className="w-full rounded-md border border-stone-200/70 bg-white/60 px-2.5 py-1.5 text-xs
                     text-stone-800 placeholder:text-stone-400 focus:border-amber-400 focus:outline-none
                     dark:border-zinc-700/70 dark:bg-zinc-800/60 dark:text-zinc-200
                     dark:placeholder:text-zinc-600 dark:focus:border-amber-500"
        />
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={loading || (mode === "topic" ? !topic.trim() : !url.trim())}
        className="w-full rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-white
                   transition-colors hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Researching…" : "Research"}
      </button>

      {/* Feedback */}
      {submitted && !error && (
        <p className="text-[11px] text-green-600 dark:text-green-400">
          Research queued — watch the progress bar below.
        </p>
      )}
      {error && (
        <p className="text-[11px] text-red-500 dark:text-red-400">{error}</p>
      )}

      {/* Note */}
      <p className="text-[10px] text-stone-400 dark:text-zinc-600">
        Results are written to <code className="font-mono">clean-vault/raw/research/</code> and processed by the agent pipeline.
      </p>
    </div>
  );
});
