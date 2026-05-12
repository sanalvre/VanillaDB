/**
 * CommandPalette — cmdk-powered quick action overlay.
 * Opens with Cmd+K / Ctrl+K.
 */

import { useEffect, useState, useCallback } from "react";
import { Command } from "cmdk";
import { useEditorStore } from "@/stores/editorStore";
import { useStatusStore } from "@/stores/statusStore";
import { runAgentNow, search } from "@/api/sidecar";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<
    Array<{ path: string; title: string; vault: string }>
  >([]);

  const openFile = useEditorStore((s) => s.openFile);
  const toggleGraph = useEditorStore((s) => s.toggleGraph);
  const pendingProposals = useStatusStore((s) => s.pendingProposals);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
        setQuery("");
        setSearchResults([]);
      }
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (!open || query.length < 2) { setSearchResults([]); return; }
    const timeout = setTimeout(async () => {
      try {
        const data = await search(query, "all", 8);
        setSearchResults(
          data.results.map((r) => ({
            path: r.path,
            title: r.title || r.path.split("/").pop() || r.path,
            vault: r.vault,
          })),
        );
      } catch { /* ignore */ }
    }, 150);
    return () => clearTimeout(timeout);
  }, [query, open]);

  const handleSelect = useCallback(
    (value: string) => {
      setOpen(false);
      if (value === "toggle-graph") toggleGraph();
      else if (value === "run-agent") runAgentNow();
      else if (value.startsWith("file:")) openFile(value.slice(5));
    },
    [toggleGraph, openFile],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/20 dark:bg-black/50"
        onClick={() => setOpen(false)}
      />

      {/* Palette */}
      <Command
        className="relative w-full max-w-lg rounded-xl border border-stone-200 bg-white shadow-2xl
                   dark:border-zinc-700 dark:bg-zinc-900 dark:shadow-black/60"
        onValueChange={() => {}}
      >
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search files, run commands..."
          className="w-full border-b border-stone-100 bg-transparent px-4 py-3 text-sm outline-none
                     placeholder:text-stone-400 text-stone-800
                     dark:border-zinc-800 dark:text-zinc-200 dark:placeholder:text-zinc-600"
        />
        <Command.List className="max-h-72 overflow-y-auto p-2">
          <Command.Empty className="px-4 py-6 text-center text-sm text-stone-400 dark:text-zinc-600">
            No results
          </Command.Empty>

          {searchResults.length > 0 && (
            <Command.Group heading="Files" className="mb-2">
              {searchResults.map((r) => (
                <Command.Item
                  key={r.path}
                  value={`file:${r.path}`}
                  onSelect={handleSelect}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm
                             text-stone-700 data-[selected=true]:bg-stone-100
                             dark:text-zinc-300 dark:data-[selected=true]:bg-zinc-800"
                >
                  <span className="flex-1 truncate">{r.title}</span>
                  <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-stone-500
                                  dark:bg-zinc-800 dark:text-zinc-500">
                    {r.vault}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          )}

          <Command.Group heading="Commands" className="mb-1">
            <Command.Item
              value="toggle-graph"
              onSelect={handleSelect}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm
                         text-stone-700 data-[selected=true]:bg-stone-100
                         dark:text-zinc-300 dark:data-[selected=true]:bg-zinc-800"
            >
              <span className="text-stone-400 dark:text-zinc-600">G</span>
              <span>Toggle knowledge graph</span>
            </Command.Item>

            <Command.Item
              value="run-agent"
              onSelect={handleSelect}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm
                         text-stone-700 data-[selected=true]:bg-stone-100
                         dark:text-zinc-300 dark:data-[selected=true]:bg-zinc-800"
            >
              <span className="text-stone-400 dark:text-zinc-600">R</span>
              <span>Run agent now</span>
            </Command.Item>

            {pendingProposals > 0 && (
              <Command.Item
                value="review-proposals"
                onSelect={() => {
                  setOpen(false);
                  window.dispatchEvent(new CustomEvent("vanilla:open-proposals"));
                }}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm
                           text-stone-700 data-[selected=true]:bg-stone-100
                           dark:text-zinc-300 dark:data-[selected=true]:bg-zinc-800"
              >
                <span className="text-stone-400 dark:text-zinc-600">P</span>
                <span>
                  Review proposals{" "}
                  <span className="text-amber-600 dark:text-amber-400">({pendingProposals})</span>
                </span>
              </Command.Item>
            )}
          </Command.Group>
        </Command.List>

        {/* Footer hint */}
        <div className="border-t border-stone-100 px-4 py-2 text-[11px] text-stone-400
                       dark:border-zinc-800 dark:text-zinc-600">
          <kbd className="rounded border border-stone-200 px-1 dark:border-zinc-700 dark:text-zinc-500">esc</kbd> to close
        </div>
      </Command>
    </div>
  );
}
