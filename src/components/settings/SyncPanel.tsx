/**
 * SyncPanel — git-based vault sync configuration (Phase 10).
 *
 * Configure a remote (GitHub/GitLab/Gitea), then Push or Pull
 * with a single click. Shows live sync status pulled from sidecar.
 */

import { useState, useEffect, useCallback } from "react";
import {
  getSyncStatus,
  configureSyncRemote,
  syncPush,
  syncPull,
  type SyncStatus,
} from "@/api/sidecar";

function timeAgo(unixSec: number): string {
  const diff = Math.floor(Date.now() / 1000) - unixSec;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

type SyncOp = "idle" | "pushing" | "pulling";

export function SyncPanel() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [remoteUrl, setRemoteUrl] = useState("");
  const [op, setOp] = useState<SyncOp>("idle");
  const [lastResult, setLastResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getSyncStatus();
      setStatus(s);
      if (s.remote_url) setRemoteUrl(s.remote_url);
    } catch {
      // sidecar unavailable
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSaveRemote = useCallback(async () => {
    if (!remoteUrl.trim()) return;
    setLastResult(null);
    try {
      await configureSyncRemote(remoteUrl.trim());
      setLastResult({ ok: true, msg: "Remote saved" });
      refresh();
    } catch (e) {
      setLastResult({ ok: false, msg: e instanceof Error ? e.message : "Failed" });
    }
  }, [remoteUrl, refresh]);

  const handlePush = useCallback(async () => {
    if (status && status.dirty_files > 0) {
      const ok = window.confirm(
        `You have ${status.dirty_files} unsaved change${status.dirty_files > 1 ? "s" : ""}. Push anyway?`
      );
      if (!ok) return;
    }
    setOp("pushing");
    setLastResult(null);
    try {
      const result = await syncPush();
      if (result.success) {
        setLastResult({
          ok: true,
          msg: result.committed ? "Committed & pushed" : "Already up to date — pushed",
        });
        refresh();
      } else {
        setLastResult({ ok: false, msg: result.error ?? "Push failed" });
      }
    } catch (e) {
      setLastResult({ ok: false, msg: e instanceof Error ? e.message : "Push failed" });
    } finally {
      setOp("idle");
    }
  }, [refresh]);

  const handlePull = useCallback(async () => {
    setOp("pulling");
    setLastResult(null);
    try {
      const result = await syncPull();
      if (result.success) {
        setLastResult({
          ok: true,
          msg: result.files_changed > 0
            ? `Pulled — ${result.files_changed} file(s) updated`
            : "Already up to date",
        });
        refresh();
      } else {
        setLastResult({ ok: false, msg: result.error ?? "Pull failed" });
      }
    } catch (e) {
      setLastResult({ ok: false, msg: e instanceof Error ? e.message : "Pull failed" });
    } finally {
      setOp("idle");
    }
  }, [refresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="h-4 w-4 animate-spin rounded-full border border-stone-300 border-t-stone-600" />
      </div>
    );
  }

  const isBusy = op !== "idle";

  return (
    <div className="space-y-5">
      {/* Status card */}
      <div className={`rounded-lg border px-3 py-2.5 text-xs ${
        !status?.is_repo
          ? "border-stone-200 bg-stone-50 text-stone-500"
          : status.has_remote
            ? status.ahead > 0
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-green-200 bg-green-50 text-green-700"
            : "border-stone-200 bg-stone-50 text-stone-500"
      }`}>
        {!status?.is_repo ? (
          <p>Not yet initialised — enter a remote URL and click Save to set up sync</p>
        ) : !status.has_remote ? (
          <p>Repo initialised locally — add a remote URL to enable cloud sync</p>
        ) : (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="font-medium">
                {status.ahead > 0
                  ? `${status.ahead} commit${status.ahead > 1 ? "s" : ""} to push`
                  : status.behind > 0
                    ? `${status.behind} commit${status.behind > 1 ? "s" : ""} to pull`
                    : "In sync with remote"}
              </span>
              <span className="text-[10px] opacity-70">
                {status.branch ?? "main"}
              </span>
            </div>
            {status.last_commit_hash && (
              <p className="text-[11px] opacity-70">
                {status.last_commit_hash} · {status.last_commit_message ?? ""}{" "}
                {status.last_commit_time ? `· ${timeAgo(status.last_commit_time)}` : ""}
              </p>
            )}
            {status.dirty_files > 0 && (
              <p className="text-[11px] opacity-70">
                {status.dirty_files} unsaved change{status.dirty_files > 1 ? "s" : ""}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Remote URL */}
      <div className="space-y-1.5">
        <label className="text-xs font-semibold uppercase tracking-wider text-stone-500">
          Remote URL
        </label>
        <div className="flex gap-1.5">
          <input
            type="text"
            value={remoteUrl}
            onChange={(e) => setRemoteUrl(e.target.value)}
            placeholder="https://github.com/you/vault.git"
            className="min-w-0 flex-1 rounded-lg border border-stone-200 bg-stone-50 px-3 py-1.5
                       text-xs text-stone-800 placeholder:text-stone-400
                       focus:border-stone-400 focus:bg-white focus:outline-none transition-colors"
          />
          <button
            onClick={handleSaveRemote}
            disabled={!remoteUrl.trim() || isBusy}
            className="shrink-0 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs
                       font-medium text-stone-600 transition-colors hover:bg-stone-50
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            Save
          </button>
        </div>
        <p className="text-[11px] text-stone-400">
          Any git remote: GitHub, GitLab, Gitea, Codeberg, self-hosted
        </p>
      </div>

      {/* Authentication note */}
      {status?.has_remote && (
        <div className="rounded-lg bg-stone-50 px-3 py-2 text-[11px] text-stone-500">
          <p className="font-medium text-stone-600">Authentication</p>
          <p className="mt-0.5">
            Use HTTPS with a personal access token in the URL:<br />
            <code className="text-stone-700">https://TOKEN@github.com/you/vault.git</code>
          </p>
        </div>
      )}

      {/* Push / Pull actions */}
      <div className="space-y-2">
        <label className="text-xs font-semibold uppercase tracking-wider text-stone-500">
          Sync
        </label>
        <div className="flex gap-2">
          <button
            onClick={handlePush}
            disabled={isBusy || !status?.has_remote}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg
                       bg-stone-800 px-4 py-2 text-xs font-medium text-white
                       transition-colors hover:bg-stone-700
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {op === "pushing" ? (
              <div className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white" />
            ) : (
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                <line x1="6" y1="9" x2="6" y2="2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <polyline points="3,5 6,2 9,5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              </svg>
            )}
            Push
          </button>
          <button
            onClick={handlePull}
            disabled={isBusy || !status?.has_remote}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg
                       border border-stone-200 bg-white px-4 py-2 text-xs font-medium
                       text-stone-700 transition-colors hover:bg-stone-50
                       disabled:cursor-not-allowed disabled:opacity-50"
          >
            {op === "pulling" ? (
              <div className="h-3 w-3 animate-spin rounded-full border border-stone-300 border-t-stone-600" />
            ) : (
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                <line x1="6" y1="3" x2="6" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <polyline points="3,7 6,10 9,7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
              </svg>
            )}
            Pull
          </button>
        </div>

        {/* Result feedback */}
        {lastResult && (
          <p className={`text-center text-[11px] ${lastResult.ok ? "text-green-600" : "text-red-500"}`}>
            {lastResult.ok ? "✓ " : "✗ "}{lastResult.msg}
          </p>
        )}
      </div>

      {/* What gets synced */}
      <div className="rounded-lg bg-stone-50 px-3 py-2 text-[11px] text-stone-500 space-y-0.5">
        <p className="font-medium text-stone-600">What gets synced</p>
        <p>✓ clean-vault/ — your source documents</p>
        <p>✓ wiki-vault/ — agent-generated articles</p>
        <p>✗ .staging/ — excluded (temporary files)</p>
      </div>
    </div>
  );
}
