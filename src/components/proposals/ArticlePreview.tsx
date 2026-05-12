/**
 * ArticlePreview — shows the raw markdown of a staged article.
 *
 * Supports an inline edit mode: clicking "Edit" switches the read-only <pre>
 * to a textarea. "Save" PUTs the changes back to the staging file via the
 * backend. The parent receives the updated content via onContentChange so the
 * preview stays in sync without a fresh fetch.
 *
 * Parses review_issues from YAML frontmatter and renders them as amber chips.
 */

import { useState, useEffect } from "react";
import { saveProposalArticle } from "@/api/sidecar";

interface ReviewIssue {
  type: string;
  description: string;
  related_concept?: string;
}

interface ArticlePreviewProps {
  batchId: string;
  filename: string;
  content: string;
  onClose: () => void;
  onContentChange?: (newContent: string) => void;
}

function parseReviewIssues(content: string): ReviewIssue[] {
  const fmMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!fmMatch) return [];

  const fm = fmMatch[1];
  const issues: ReviewIssue[] = [];
  const lines = fm.split("\n");
  let inIssues = false;
  let current: Partial<ReviewIssue> | null = null;

  for (const line of lines) {
    if (line.trim() === "review_issues:") { inIssues = true; continue; }
    if (inIssues) {
      if (line.match(/^[a-z]/)) {
        if (current?.type) issues.push(current as ReviewIssue);
        inIssues = false; current = null; continue;
      }
      const itemMatch = line.match(/^\s{2}-\s+type:\s*(.+)/);
      if (itemMatch) { if (current?.type) issues.push(current as ReviewIssue); current = { type: itemMatch[1].trim() }; continue; }
      const descMatch = line.match(/^\s{4}description:\s*"?(.+?)"?\s*$/);
      if (descMatch && current) { current.description = descMatch[1]; continue; }
      const relMatch = line.match(/^\s{4}related_concept:\s*"?(.+?)"?\s*$/);
      if (relMatch && current) { current.related_concept = relMatch[1]; }
    }
  }
  if (current?.type) issues.push(current as ReviewIssue);
  return issues;
}

export function ArticlePreview({
  batchId,
  filename,
  content,
  onClose,
  onContentChange,
}: ArticlePreviewProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Keep draft in sync if parent refreshes content externally
  useEffect(() => {
    if (!editing) setDraft(content);
  }, [content, editing]);

  const reviewIssues = parseReviewIssues(editing ? draft : content);

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      await saveProposalArticle(batchId, filename, draft);
      onContentChange?.(draft);
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function handleCancelEdit() {
    setDraft(content);
    setEditing(false);
    setSaveError(null);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-stone-200 px-4 py-2 dark:border-zinc-700">
        <span className="text-sm font-medium text-stone-700 dark:text-zinc-200">
          {filename}
        </span>
        <div className="flex items-center gap-1">
          {editing ? (
            <>
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded px-2 py-1 text-xs font-medium bg-stone-800 text-white hover:bg-stone-700 disabled:opacity-50 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-zinc-100 transition-colors"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                onClick={handleCancelEdit}
                disabled={saving}
                className="rounded px-2 py-1 text-xs text-stone-500 hover:bg-stone-100 hover:text-stone-700 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-700 dark:hover:text-zinc-200 transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="rounded px-2 py-1 text-xs text-stone-500 hover:bg-stone-100 hover:text-stone-700 dark:text-zinc-400 dark:hover:bg-zinc-700 dark:hover:text-zinc-200 transition-colors"
            >
              Edit
            </button>
          )}
          <button
            onClick={onClose}
            className="ml-1 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600 dark:text-zinc-500 dark:hover:bg-zinc-700 dark:hover:text-zinc-200"
            aria-label="Close preview"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Review issues */}
      {reviewIssues.length > 0 && (
        <div className="space-y-1 border-b border-amber-100 bg-amber-50 px-4 py-2 dark:border-amber-900/40 dark:bg-amber-950/30">
          <p className="text-xs font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400">
            Review issues ({reviewIssues.length})
          </p>
          {reviewIssues.map((issue, i) => (
            <div
              key={i}
              className="flex gap-2 rounded border border-amber-200 bg-white p-2 text-sm dark:border-amber-800/50 dark:bg-zinc-800"
            >
              <span className="shrink-0 font-mono text-xs font-semibold uppercase text-amber-500 dark:text-amber-400">
                {issue.type}
              </span>
              <span className="text-amber-800 dark:text-amber-200">{issue.description}</span>
            </div>
          ))}
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <p className="border-b border-red-100 bg-red-50 px-4 py-1.5 text-xs text-red-600 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400">
          {saveError}
        </p>
      )}

      {/* Content — read-only or editable */}
      <div className="flex-1 overflow-y-auto">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
            className="h-full min-h-[200px] w-full resize-none bg-white px-4 py-3 font-mono text-xs
                       leading-relaxed text-stone-800 focus:outline-none
                       dark:bg-zinc-900 dark:text-zinc-200"
          />
        ) : (
          <pre className="whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-relaxed text-stone-700 dark:text-zinc-300">
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}
