/**
 * DropZone — handles drag-and-drop file ingestion over the app window.
 *
 * Listens for Tauri's drag-drop events and sends files to the sidecar
 * for ingestion. Shows a visual overlay when dragging.
 */

import { useState, useCallback, useEffect } from "react";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { ingestFile } from "@/api/ingest";

interface DropZoneProps {
  children: React.ReactNode;
  onIngestStarted?: (jobId: string, filePath: string) => void;
  onError?: (error: string) => void;
}

export function DropZone({ children, onIngestStarted, onError }: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    let unlisten: (() => void) | undefined;

    const setup = async () => {
      try {
        const appWindow = getCurrentWebviewWindow();
        unlisten = await appWindow.onDragDropEvent((event) => {
          if (event.payload.type === "over") {
            setIsDragging(true);
          } else if (event.payload.type === "drop") {
            setIsDragging(false);
            handleDrop(event.payload.paths);
          } else {
            // "cancel"
            setIsDragging(false);
          }
        });
      } catch {
        // Not running in Tauri (dev mode in browser)
        console.warn("Tauri drag-drop not available (browser dev mode)");
      }
    };

    setup();
    return () => unlisten?.();
  }, []);

  const handleDrop = useCallback(
    async (paths: string[]) => {
      for (const filePath of paths) {
        try {
          const result = await ingestFile(filePath);
          onIngestStarted?.(result.job_id, filePath);
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          onError?.(msg);
        }
      }
    },
    [onIngestStarted, onError],
  );

  return (
    <div className="relative h-full">
      {children}

      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-stone-900/30 backdrop-blur-sm">
          <div className="rounded-xl border-2 border-dashed border-amber-400 bg-white/90 px-12 py-8 shadow-lg">
            <p className="text-lg font-medium text-stone-700">
              Drop files to ingest
            </p>
            <p className="mt-1 text-sm text-stone-400">
              PDF, Markdown, or text files
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
