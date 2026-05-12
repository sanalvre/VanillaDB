/**
 * UrlBar — inline URL paste input for web page ingestion.
 *
 * Appears in the top bar. User pastes a URL and presses Enter
 * to ingest the page as markdown.
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { ingestUrl } from "@/api/ingest";

interface UrlBarProps {
  onIngestStarted?: (jobId: string, url: string) => void;
  onError?: (error: string) => void;
}

export function UrlBar({ onIngestStarted, onError }: UrlBarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = url.trim();
      if (!trimmed || loading) return;

      try {
        new URL(trimmed);
      } catch {
        onError?.("Invalid URL");
        return;
      }

      setLoading(true);
      try {
        const result = await ingestUrl(trimmed);
        onIngestStarted?.(result.job_id, trimmed);
        setUrl("");
        setIsOpen(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        onError?.(msg);
      } finally {
        setLoading(false);
      }
    },
    [url, loading, onIngestStarted, onError],
  );

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setIsOpen(false);
      setUrl("");
    }
  }, []);

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="flex items-center gap-1 rounded px-2 py-1 text-xs text-stone-500
                   hover:bg-stone-100 hover:text-stone-700 transition-colors
                   dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
        title="Paste a URL to ingest"
      >
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
          <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2" />
          <line x1="6" y1="3" x2="6" y2="9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          <line x1="3" y1="6" x2="9" y2="6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        URL
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-1.5">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Paste URL and press Enter..."
          className="w-64 rounded border border-stone-200 bg-white px-2.5 py-1 text-xs
                     text-stone-800 placeholder:text-stone-400 transition-colors
                     focus:border-stone-400 focus:outline-none disabled:opacity-60
                     dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                     dark:placeholder:text-zinc-600 dark:focus:border-zinc-500"
          disabled={loading}
        />
        {/* Inline spinner */}
        {loading && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2">
            <div className="h-3 w-3 animate-spin rounded-full border border-stone-300 border-t-stone-600" />
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => { setIsOpen(false); setUrl(""); }}
        className="text-stone-400 hover:text-stone-600 transition-colors"
        aria-label="Cancel"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <line x1="2" y1="2" x2="10" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="10" y1="2" x2="2" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
    </form>
  );
}
