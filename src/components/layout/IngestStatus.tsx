/**
 * IngestStatus — shows active ingestion job progress in the sidebar.
 * Completed jobs linger for 2s then fade out rather than vanishing abruptly.
 */

import { useState, useEffect, useRef } from "react";
import { getIngestStatus } from "@/api/ingest";

interface IngestJob {
  jobId: string;
  label: string;
  status: "pending" | "processing" | "complete" | "error";
  progress: number;
  error?: string;
  completedAt?: number; // timestamp when completed
}

interface IngestStatusProps {
  jobs: IngestJob[];
  onJobComplete?: (jobId: string, outputPath: string) => void;
}

export function IngestStatus({ jobs, onJobComplete }: IngestStatusProps) {
  const [activeJobs, setActiveJobs] = useState<IngestJob[]>(jobs);
  const onJobCompleteRef = useRef(onJobComplete);
  onJobCompleteRef.current = onJobComplete;

  // Poll active jobs for status updates
  useEffect(() => {
    const pending = activeJobs.filter(
      (j) => j.status === "pending" || j.status === "processing",
    );
    if (pending.length === 0) return;

    const interval = setInterval(async () => {
      const updates = await Promise.all(
        pending.map(async (job) => {
          try {
            const status = await getIngestStatus(job.jobId);
            const updated: IngestJob = {
              ...job,
              status: status.status,
              progress: status.progress,
              error: status.error ?? undefined,
              completedAt: status.status === "complete" ? Date.now() : job.completedAt,
            };
            if (status.status === "complete" && status.output_path) {
              onJobCompleteRef.current?.(job.jobId, status.output_path);
            }
            return updated;
          } catch {
            return job;
          }
        }),
      );

      setActiveJobs((prev) =>
        prev.map((j) => updates.find((u) => u.jobId === j.jobId) || j),
      );
    }, 2000);

    return () => clearInterval(interval);
  }, [activeJobs]);

  // Sync new jobs from parent
  useEffect(() => {
    setActiveJobs((prev) => {
      const existingIds = new Set(prev.map((j) => j.jobId));
      const newJobs = jobs.filter((j) => !existingIds.has(j.jobId));
      return [...prev, ...newJobs];
    });
  }, [jobs]);

  // Expire completed jobs after 2.5s
  useEffect(() => {
    const completed = activeJobs.filter(
      (j) => j.status === "complete" && j.completedAt,
    );
    if (completed.length === 0) return;

    const oldest = Math.min(...completed.map((j) => j.completedAt!));
    const delay = Math.max(0, 2500 - (Date.now() - oldest));

    const timer = setTimeout(() => {
      setActiveJobs((prev) =>
        prev.filter(
          (j) => j.status !== "complete" || Date.now() - (j.completedAt ?? 0) < 2500,
        ),
      );
    }, delay);

    return () => clearTimeout(timer);
  }, [activeJobs]);

  const visibleJobs = activeJobs.filter(
    (j) => j.status !== "complete" || Date.now() - (j.completedAt ?? 0) < 2500,
  );

  if (visibleJobs.length === 0) return null;

  return (
    <div className="border-t border-stone-100 px-2 py-2 space-y-1.5 dark:border-zinc-800">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-stone-300 dark:text-zinc-700">
        Ingesting
      </p>
      {visibleJobs.map((job) => (
        <div key={job.jobId} className="text-xs">
          <div className="flex items-center justify-between gap-1">
            <span className="truncate text-stone-600 flex-1 dark:text-zinc-400">{job.label}</span>
            <span
              className={`shrink-0 font-medium ${
                job.status === "error"
                  ? "text-red-500"
                  : job.status === "complete"
                    ? "text-green-600"
                    : "text-stone-400"
              }`}
            >
              {job.status === "processing"
                ? `${Math.round(job.progress * 100)}%`
                : job.status === "complete"
                  ? "done"
                  : job.status}
            </span>
          </div>
          {/* Progress bar */}
          <div className="mt-0.5 h-0.5 w-full rounded-full bg-stone-100 dark:bg-zinc-800">
            <div
              className={`h-0.5 rounded-full transition-all duration-300 ${
                job.status === "complete"
                  ? "bg-green-400"
                  : job.status === "error"
                    ? "bg-red-400"
                    : "bg-amber-400"
              }`}
              style={{
                width: `${
                  job.status === "complete"
                    ? 100
                    : job.status === "error"
                      ? 100
                      : job.progress * 100
                }%`,
              }}
            />
          </div>
          {job.error && (
            <p className="mt-0.5 truncate text-[10px] text-red-400" title={job.error}>
              {job.error}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
