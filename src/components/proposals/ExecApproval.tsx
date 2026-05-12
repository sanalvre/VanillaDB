/**
 * ExecApproval — review and approve agent-initiated code runs.
 *
 * Appears after a proposal batch is approved if the article contained
 * <!-- exec --> code blocks. Shows each pending run with:
 *   - Read-only code preview
 *   - Approve → runs code, shows output inline
 *   - Reject → skips without running
 */

import { useState, useEffect, useCallback } from "react";
import { useVaultStore } from "@/stores/vaultStore";

function baseUrl(): string {
  const stored = typeof window !== "undefined" ? localStorage.getItem("vanilla:sidecarPort") : null;
  if (stored) return `http://127.0.0.1:${stored}`;
  return `http://127.0.0.1:${useVaultStore.getState().sidecarPort}`;
}

interface ExecRun {
  id: string;
  article_path: string;
  code: string;
  lang: string;
  status: "pending" | "complete" | "error" | "rejected";
  stdout?: string;
  stderr?: string;
  exit_code?: number;
}

interface ExecResult {
  status: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  runtime_ms: number;
}

export function ExecApproval() {
  const [runs, setRuns] = useState<ExecRun[]>([]);
  const [results, setResults] = useState<Record<string, ExecResult>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  const fetchPending = useCallback(async () => {
    try {
      const res = await fetch(`${baseUrl()}/exec/pending`);
      if (!res.ok) return;
      const data = await res.json();
      setRuns(data.runs ?? []);
    } catch {
      // Sidecar not available
    }
  }, []);

  useEffect(() => {
    fetchPending();
    // Poll every 5s to pick up new runs created by fileback
    const id = setInterval(fetchPending, 5000);
    return () => clearInterval(id);
  }, [fetchPending]);

  const handleApprove = useCallback(async (runId: string) => {
    setLoading((l) => ({ ...l, [runId]: true }));
    try {
      const res = await fetch(`${baseUrl()}/exec/${runId}/approve`, { method: "POST" });
      const data = await res.json();
      setResults((r) => ({ ...r, [runId]: data }));
      // Remove from pending list
      setRuns((prev) => prev.filter((r) => r.id !== runId));
    } catch (e) {
      console.error("Exec approve failed:", e);
    } finally {
      setLoading((l) => ({ ...l, [runId]: false }));
    }
  }, []);

  const handleReject = useCallback(async (runId: string) => {
    setLoading((l) => ({ ...l, [runId]: true }));
    try {
      await fetch(`${baseUrl()}/exec/${runId}/reject`, { method: "POST" });
      setRuns((prev) => prev.filter((r) => r.id !== runId));
    } catch {
      // ignore
    } finally {
      setLoading((l) => ({ ...l, [runId]: false }));
    }
  }, []);

  const pendingRuns = runs.filter((r) => r.status === "pending");
  const completedIds = Object.keys(results);

  if (pendingRuns.length === 0 && completedIds.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <div>
        <p className="text-sm font-semibold text-stone-700 dark:text-zinc-300">
          Code Execution
        </p>
        <p className="text-xs text-stone-400 dark:text-zinc-500">
          Agent-proposed code blocks require your approval before running.
        </p>
      </div>

      {/* Pending runs */}
      {pendingRuns.map((run) => (
        <div
          key={run.id}
          className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 dark:border-amber-900/50 dark:bg-amber-950/30"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-medium text-amber-700 dark:text-amber-400">
              {run.lang} · {run.article_path.split("/").pop()}
            </span>
            <div className="flex gap-1.5">
              <button
                onClick={() => handleApprove(run.id)}
                disabled={loading[run.id]}
                className="rounded bg-green-600 px-2 py-0.5 text-[11px] font-medium text-white
                           transition-colors hover:bg-green-500 disabled:opacity-50"
              >
                {loading[run.id] ? "Running…" : "Approve & Run"}
              </button>
              <button
                onClick={() => handleReject(run.id)}
                disabled={loading[run.id]}
                className="rounded bg-stone-200 px-2 py-0.5 text-[11px] font-medium text-stone-700
                           transition-colors hover:bg-stone-300 dark:bg-zinc-700 dark:text-zinc-200
                           dark:hover:bg-zinc-600 disabled:opacity-50"
              >
                Skip
              </button>
            </div>
          </div>

          {/* Code preview */}
          <pre className="overflow-x-auto rounded bg-stone-900 p-2 text-[11px] text-green-300 dark:bg-zinc-950">
            <code>{run.code}</code>
          </pre>
        </div>
      ))}

      {/* Completed results */}
      {completedIds.map((runId) => {
        const result = results[runId];
        const success = result.exit_code === 0;
        return (
          <div
            key={runId}
            className={`rounded-lg border p-3 ${
              success
                ? "border-green-200 bg-green-50/60 dark:border-green-900/50 dark:bg-green-950/30"
                : "border-red-200 bg-red-50/60 dark:border-red-900/50 dark:bg-red-950/30"
            }`}
          >
            <p className="mb-1 text-[11px] font-medium text-stone-600 dark:text-zinc-400">
              {success ? "✓ Completed" : "✗ Failed"} · {result.runtime_ms}ms
            </p>
            {(result.stdout || result.stderr) && (
              <pre className="overflow-x-auto rounded bg-stone-900 p-2 text-[11px] text-zinc-300 dark:bg-zinc-950">
                <code>{result.stdout || result.stderr}</code>
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}
