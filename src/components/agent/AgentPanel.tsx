/**
 * AgentPanel — sidebar panel for giving natural-language instructions to the knowledge base agent.
 *
 * The agent can:
 *   • Edit the currently open file
 *   • Create new concept articles
 *   • Add/remove wikilinks between concepts
 *   • Bulk restructure concepts (rename, merge)
 *   • Answer questions about the graph (search — no changes)
 *
 * All file-modifying operations create a staging proposal that appears in ProposalPanel
 * for user approval before anything is written to the wiki vault.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useEditorStore } from "@/stores/editorStore";
import { useGraphStore } from "@/stores/graphStore";
import { useGraphSettingsStore, type GraphSettings } from "@/stores/graphSettingsStore";
import { instructAgent, getAgentHistory, type AgentHistoryEntry } from "@/api/agent";
import { AgentVoiceButton } from "./AgentVoiceButton";

const STATUS_COLORS: Record<string, string> = {
  pending:    "text-amber-500 dark:text-amber-400",
  processing: "text-blue-500 dark:text-blue-400",
  approved:   "text-green-600 dark:text-green-400",
  rejected:   "text-stone-400 dark:text-zinc-500",
};

const STATUS_DOTS: Record<string, string> = {
  pending:    "bg-amber-400",
  processing: "bg-blue-400",
  approved:   "bg-green-500",
  rejected:   "bg-stone-300 dark:bg-zinc-600",
};

export function AgentPanel() {
  const activeFilePath = useEditorStore((s) => s.activeFilePath);
  const nodes = useGraphStore((s) => s.nodes);
  const edges = useGraphStore((s) => s.edges);
  const setGraphSetting = useGraphSettingsStore((s) => s.set);

  const [instruction, setInstruction] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<{ text: string; sources: string[] } | null>(null);
  const [settingsConfirm, setSettingsConfirm] = useState<string | null>(null);
  const [history, setHistory] = useState<AgentHistoryEntry[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Derive the active file's graph node (if any)
  const activeNode = activeFilePath
    ? nodes.find((n) => n.path === activeFilePath || activeFilePath.endsWith(n.path))
    : null;

  // Derive nearby concept labels (1 hop from active node)
  const nearbyLabels: string[] = activeNode
    ? edges
        .filter((e) => e.source === activeNode.id || e.target === activeNode.id)
        .map((e) => {
          const neighborId = e.source === activeNode.id ? e.target : e.source;
          return nodes.find((n) => n.id === neighborId)?.label ?? "";
        })
        .filter(Boolean)
        .slice(0, 6)
    : [];

  const loadHistory = useCallback(async () => {
    const h = await getAgentHistory();
    setHistory(h);
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleSubmit = useCallback(async () => {
    if (!instruction.trim() || isLoading) return;

    setIsLoading(true);
    setError(null);
    setAnswer(null);

    try {
      const result = await instructAgent(
        instruction.trim(),
        activeFilePath ?? null,
        nearbyLabels,
      );

      if (result.operation_type === "graph_settings" && result.settings) {
        // Apply settings delta directly to the store — no proposal needed
        const delta = result.settings as Partial<GraphSettings>;
        for (const [key, value] of Object.entries(delta)) {
          setGraphSetting(key as keyof GraphSettings, value as GraphSettings[keyof GraphSettings]);
        }
        setSettingsConfirm(result.summary ?? "Graph settings updated.");
        setInstruction("");
      } else if (result.answer !== undefined) {
        // Search or fallback — show inline answer
        setAnswer({ text: result.answer, sources: result.sources ?? [] });
      } else {
        // File-modifying operation (edit, create, multi_edit, restructure) — ProposalPanel will auto-open
        setInstruction("");
        window.dispatchEvent(new CustomEvent("vanilla:proposals-refresh"));
      }

      await loadHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent instruction failed.");
    } finally {
      setIsLoading(false);
    }
  }, [instruction, isLoading, activeFilePath, nearbyLabels, loadHistory]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleTranscript = useCallback((text: string) => {
    setInstruction((prev) => prev ? `${prev} ${text}` : text);
    textareaRef.current?.focus();
  }, []);

  const activeFileName = activeFilePath
    ? activeFilePath.split(/[/\\]/).pop()
    : null;

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-3 py-2">
        <div className="flex items-center gap-1.5">
          {/* Bot icon */}
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="text-stone-500 dark:text-zinc-400">
            <rect x="2" y="5" width="12" height="9" rx="2" stroke="currentColor" strokeWidth="1.3" />
            <circle cx="5.5" cy="9.5" r="1" fill="currentColor" />
            <circle cx="10.5" cy="9.5" r="1" fill="currentColor" />
            <path d="M8 2v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            <circle cx="8" cy="1.5" r="0.8" fill="currentColor" />
          </svg>
          <span className="text-xs font-semibold text-stone-700 dark:text-zinc-200">Agent</span>
        </div>
      </div>

      <div className="flex flex-col gap-2.5 overflow-y-auto p-3">
        {/* Context chips */}
        <div className="space-y-1">
          {activeFileName ? (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[10px] text-stone-400 dark:text-zinc-500">Context:</span>
              <span className="inline-flex items-center gap-1 rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-600 dark:bg-zinc-800 dark:text-zinc-300">
                <svg width="9" height="9" viewBox="0 0 12 12" fill="none" className="shrink-0 opacity-60">
                  <path d="M7 1H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V5L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
                  <path d="M7 1v4h4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                {activeFileName}
              </span>
            </div>
          ) : (
            <p className="text-[10px] text-stone-400 dark:text-zinc-500">
              Open a file to edit it, or describe a concept to create.
            </p>
          )}

          {nearbyLabels.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {nearbyLabels.map((label) => (
                <span
                  key={label}
                  className="inline-block rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-950/30 dark:text-amber-400"
                >
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Instruction input */}
        <div className="space-y-1.5">
          <textarea
            ref={textareaRef}
            value={instruction}
            onChange={(e) => { setInstruction(e.target.value); setError(null); setAnswer(null); }}
            onKeyDown={handleKeyDown}
            placeholder="What should the agent do?&#10;e.g. Add a TL;DR to all AI concepts&#10;e.g. Color the graph by cluster&#10;e.g. Create a new concept about X"
            rows={4}
            className="w-full resize-none rounded-lg border border-stone-200 bg-stone-50 px-3 py-2
                       text-xs text-stone-800 placeholder:text-stone-400
                       focus:border-stone-400 focus:bg-white focus:outline-none transition-colors
                       dark:border-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-200
                       dark:placeholder:text-zinc-600 dark:focus:border-zinc-500 dark:focus:bg-zinc-800"
          />

          {/* Action row */}
          <div className="flex items-start justify-between gap-2">
            <AgentVoiceButton onTranscript={handleTranscript} disabled={isLoading} />

            <button
              onClick={handleSubmit}
              disabled={!instruction.trim() || isLoading}
              className="flex items-center gap-1.5 rounded-lg bg-stone-800 px-3 py-1.5
                         text-xs font-medium text-white transition-colors
                         hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50
                         dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100"
            >
              {isLoading ? (
                <>
                  <div className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white dark:border-zinc-600/30 dark:border-t-zinc-900" />
                  Working...
                </>
              ) : (
                <>
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                    <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Send
                  <span className="text-[9px] opacity-60">⌘↵</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Graph settings confirmation */}
        {settingsConfirm && (
          <div className="flex items-start justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-400">
            <span>{settingsConfirm}</span>
            <button
              onClick={() => setSettingsConfirm(null)}
              className="shrink-0 text-emerald-400 hover:text-emerald-600 dark:text-emerald-600 dark:hover:text-emerald-400"
            >
              ✕
            </button>
          </div>
        )}

        {/* Search answer */}
        {answer && (
          <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-3 dark:border-zinc-700 dark:bg-zinc-800/40">
            <p className="text-[11px] leading-relaxed text-stone-700 dark:text-zinc-300 whitespace-pre-wrap">
              {answer.text}
            </p>
            {answer.sources.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[10px] text-stone-400 dark:text-zinc-500">Referenced:</span>
                {answer.sources.map((s) => (
                  <span key={s} className="text-[10px] font-medium text-stone-600 dark:text-zinc-400">
                    {s}
                  </span>
                ))}
              </div>
            )}
            <button
              onClick={() => setAnswer(null)}
              className="text-[10px] text-stone-400 hover:text-stone-600 dark:text-zinc-500 dark:hover:text-zinc-300"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Usage hint */}
        <div className="rounded-lg bg-stone-50 px-3 py-2 text-[10px] leading-relaxed text-stone-400 dark:bg-zinc-800/40 dark:text-zinc-500 space-y-0.5">
          <p>File edits go through <strong className="text-stone-500 dark:text-zinc-400">Proposals → Approve</strong> before writing to your vault.</p>
          <p>Graph settings apply <strong className="text-stone-500 dark:text-zinc-400">instantly</strong> — no approval needed.</p>
        </div>

        {/* Recent history */}
        {history.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-zinc-500">
              Recent
            </p>
            <div className="space-y-1">
              {history.map((entry) => (
                <div
                  key={entry.batch_id}
                  className="flex items-start gap-1.5 rounded px-1.5 py-1 hover:bg-stone-50 dark:hover:bg-zinc-800/50"
                >
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOTS[entry.status] ?? "bg-stone-300 dark:bg-zinc-600"}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11px] text-stone-600 dark:text-zinc-400">
                      {entry.summary}
                    </p>
                    <p className={`text-[10px] ${STATUS_COLORS[entry.status] ?? ""}`}>
                      {entry.status}
                      {entry.article_count > 0 && ` · ${entry.article_count} article${entry.article_count !== 1 ? "s" : ""}`}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
