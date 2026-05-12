/**
 * ProposalBatch — renders a single proposal batch with its article list.
 *
 * Shows the summary, article titles (with action badge), preview button,
 * and approve/reject controls. One batch at a time has a loading state.
 */

import { useState } from "react";
import {
  approveProposal,
  rejectProposal,
  getProposalArticle,
} from "@/api/sidecar";
import { useGraphStore } from "@/stores/graphStore";
import { ArticlePreview } from "./ArticlePreview";

interface Article {
  filename: string;
  title: string;
  action: string;
  status: string;
}

interface Batch {
  batch_id: string;
  summary: string;
  status: string;
  batch_path: string;
  articles: Article[];
  created_at: number;
}

interface ProposalBatchProps {
  batch: Batch;
  onResolved: () => void;
}

const ACTION_COLORS: Record<string, string> = {
  create: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  update: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
};

export function ProposalBatch({ batch, onResolved }: ProposalBatchProps) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    filename: string;
    content: string;
  } | null>(null);

  function handlePreviewContentChange(newContent: string) {
    if (preview) setPreview({ ...preview, content: newContent });
  }
  const [loadingPreview, setLoadingPreview] = useState<string | null>(null);

  const date = new Date(batch.created_at * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  async function handleApprove() {
    setBusy("approve");
    setError(null);
    try {
      await approveProposal(batch.batch_id);
      useGraphStore.getState().fetchGraph();
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleReject() {
    setBusy("reject");
    setError(null);
    try {
      await rejectProposal(batch.batch_id);
      useGraphStore.getState().fetchGraph();
      onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusy(null);
    }
  }

  async function handlePreview(filename: string) {
    if (loadingPreview === filename) return;
    setLoadingPreview(filename);
    try {
      const data = await getProposalArticle(batch.batch_id, filename);
      setPreview(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load article");
    } finally {
      setLoadingPreview(null);
    }
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-zinc-700 dark:bg-zinc-800/60">
      {/* Batch header */}
      <div className="flex items-start justify-between border-b border-stone-100 px-4 py-3 dark:border-zinc-700">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-stone-800 dark:text-zinc-100">
            {batch.summary}
          </p>
          <p className="mt-0.5 text-xs text-stone-400 dark:text-zinc-500">{date}</p>
        </div>
        <span className="ml-3 flex-shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
          {batch.articles.length} article{batch.articles.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Article list */}
      <ul className="divide-y divide-stone-50 px-2 py-1 dark:divide-zinc-700">
        {batch.articles.map((article) => (
          <li
            key={article.filename}
            className="flex items-center justify-between gap-3 px-2 py-2"
          >
            <div className="flex min-w-0 items-center gap-2">
              <span
                className={`flex-shrink-0 rounded px-1.5 py-0.5 text-xs font-medium capitalize ${ACTION_COLORS[article.action] ?? "bg-stone-100 text-stone-600 dark:bg-zinc-700 dark:text-zinc-300"}`}
              >
                {article.action}
              </span>
              <span className="truncate text-sm text-stone-700 dark:text-zinc-200">
                {article.title}
              </span>
            </div>
            <button
              onClick={() => handlePreview(article.filename)}
              disabled={loadingPreview === article.filename}
              className="flex-shrink-0 rounded px-2 py-1 text-xs text-stone-500 transition hover:bg-stone-100 hover:text-stone-700 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-700 dark:hover:text-zinc-200"
            >
              {loadingPreview === article.filename ? "Loading…" : "Preview"}
            </button>
          </li>
        ))}
      </ul>

      {/* Preview pane */}
      {preview && (
        <div className="border-t border-stone-100 bg-stone-50 dark:border-zinc-700 dark:bg-zinc-900/60" style={{ maxHeight: 380, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <ArticlePreview
            batchId={batch.batch_id}
            filename={preview.filename}
            content={preview.content}
            onClose={() => setPreview(null)}
            onContentChange={handlePreviewContentChange}
          />
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="border-t border-red-100 bg-red-50 px-4 py-2 text-xs text-red-600 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400">
          {error}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 border-t border-stone-100 px-4 py-3 dark:border-zinc-700">
        <button
          onClick={handleApprove}
          disabled={!!busy}
          className="flex-1 rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === "approve" ? "Approving…" : "Approve all"}
        </button>
        <button
          onClick={handleReject}
          disabled={!!busy}
          className="rounded-md border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-600 transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-700"
        >
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </div>
  );
}
