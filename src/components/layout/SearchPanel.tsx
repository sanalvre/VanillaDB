/**
 * SearchPanel — full-text search integrated into the left sidebar.
 */

import { useState, useCallback, useRef, memo } from "react";
import { search } from "@/api/sidecar";
import { useEditorStore } from "@/stores/editorStore";

type VaultFilter = "all" | "clean" | "wiki";

interface SearchResult {
  path: string;
  vault: string;
  title: string;
  snippet: string;
  score: number;
}

function Snippet({ html }: { html: string }) {
  const clean = html.replace(/^\.\.\./, "").replace(/\.\.\.$/, "").trim();
  return (
    <p
      className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-stone-400 dark:text-zinc-600"
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}

const ResultRow = memo(function ResultRow({
  result,
  onSelect,
}: {
  result: SearchResult;
  onSelect: (path: string) => void;
}) {
  const isWiki = result.vault === "wiki" || result.path.startsWith("wiki-vault/");
  return (
    <button
      onClick={() => onSelect(result.path)}
      className="group w-full rounded-lg px-2 py-2 text-left transition-colors
                 hover:bg-stone-100 dark:hover:bg-zinc-800"
    >
      <div className="flex items-center gap-1.5">
        <span className="flex-1 truncate text-xs font-medium text-stone-700 group-hover:text-stone-900
                        dark:text-zinc-300 dark:group-hover:text-zinc-100">
          {result.title || result.path.split("/").pop()}
        </span>
        <span
          className={`shrink-0 rounded px-1 py-px text-[9px] font-semibold uppercase tracking-wide ${
            isWiki
              ? "bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400"
              : "bg-stone-100 text-stone-500 dark:bg-zinc-800 dark:text-zinc-500"
          }`}
        >
          {isWiki ? "wiki" : "vault"}
        </span>
      </div>
      {result.snippet && <Snippet html={result.snippet} />}
    </button>
  );
});

export const SearchPanel = memo(function SearchPanel({
  onClose,
}: {
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VaultFilter>("all");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openFile = useEditorStore((s) => s.openFile);

  const handleQuery = useCallback(
    (q: string) => {
      setQuery(q);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (!q.trim()) { setResults([]); return; }
      debounceRef.current = setTimeout(async () => {
        setLoading(true);
        setHasError(false);
        try {
          const data = await search(q, filter, 25);
          setResults(data.results);
        } catch {
          setResults([]);
          setHasError(true);
        } finally {
          setLoading(false);
        }
      }, 180);
    },
    [filter],
  );

  const handleSelect = useCallback(
    (path: string) => { openFile(path); onClose(); },
    [openFile, onClose],
  );

  const handleFilterChange = useCallback(
    (f: VaultFilter) => {
      setFilter(f);
      if (query.trim()) {
        setLoading(true);
        setHasError(false);
        search(query, f, 25)
          .then((d) => setResults(d.results))
          .catch(() => { setResults([]); setHasError(true); })
          .finally(() => setLoading(false));
      }
    },
    [query],
  );

  const FILTERS: { label: string; value: VaultFilter }[] = [
    { label: "All", value: "all" },
    { label: "Vault", value: "clean" },
    { label: "Wiki", value: "wiki" },
  ];

  return (
    <div className="flex flex-col overflow-hidden">
      {/* Search input */}
      <div className="relative px-2 pb-2 pt-1">
        <input
          autoFocus
          type="text"
          value={query}
          onChange={(e) => handleQuery(e.target.value)}
          placeholder="Search..."
          className="w-full rounded-md border border-stone-200 bg-white px-3 py-1.5 text-sm
                     text-stone-800 placeholder:text-stone-400 focus:border-stone-400 focus:outline-none
                     dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200
                     dark:placeholder:text-zinc-600 dark:focus:border-zinc-500"
        />
        {loading && (
          <div className="absolute right-4 top-1/2 -translate-y-1/2">
            <div className="h-3 w-3 animate-spin rounded-full border border-stone-300 border-t-stone-600
                           dark:border-zinc-700 dark:border-t-zinc-300" />
          </div>
        )}
      </div>

      {/* Vault filter tabs */}
      <div className="flex gap-1 px-2 pb-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => handleFilterChange(f.value)}
            className={`rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
              filter === f.value
                ? "bg-stone-800 text-white dark:bg-zinc-200 dark:text-zinc-900"
                : "text-stone-600 hover:bg-stone-100 hover:text-stone-800 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            }`}
          >
            {f.label}
          </button>
        ))}
        <button
          onClick={onClose}
          aria-label="Close search"
          className="ml-auto flex h-5 w-5 items-center justify-center rounded text-stone-400
                     transition-colors hover:bg-stone-200 hover:text-stone-700
                     dark:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <line x1="1.5" y1="1.5" x2="8.5" y2="8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <line x1="8.5" y1="1.5" x2="1.5" y2="8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto px-1">
        {!query.trim() && (
          <p className="px-2 py-3 text-[11px] text-stone-400 dark:text-zinc-600">
            Type to search across all files
          </p>
        )}
        {query.trim() && !loading && hasError && (
          <p className="px-2 py-3 text-[11px] text-red-400 dark:text-red-500">
            Search unavailable — is the sidecar running?
          </p>
        )}
        {query.trim() && !loading && !hasError && results.length === 0 && (
          <p className="px-2 py-3 text-[11px] text-stone-400 dark:text-zinc-600">
            No results for "{query}"
          </p>
        )}
        {results.map((r) => (
          <ResultRow key={r.path} result={r} onSelect={handleSelect} />
        ))}
      </div>
    </div>
  );
});
