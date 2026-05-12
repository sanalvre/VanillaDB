/**
 * ResizableSplit — vertical drag-resizable splitter.
 *
 * Top child gets `splitPercent`% of height; bottom child gets the rest.
 * Drag the handle to resize. No external deps — pure pointer events.
 */

import { useRef, useCallback, memo, type ReactNode } from "react";

interface ResizableSplitProps {
  splitPercent: number;
  onSplitChange: (pct: number) => void;
  top: ReactNode;
  bottom: ReactNode;
}

export const ResizableSplit = memo(function ResizableSplit({
  splitPercent,
  onSplitChange,
  top,
  bottom,
}: ResizableSplitProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      const container = containerRef.current;
      if (!container) return;

      isDragging.current = true;
      const el = e.currentTarget as HTMLElement;
      el.setPointerCapture(e.pointerId);

      const onMove = (me: PointerEvent) => {
        if (!isDragging.current) return;
        const rect = container.getBoundingClientRect();
        const y = me.clientY - rect.top;
        const pct = Math.min(80, Math.max(20, (y / rect.height) * 100));
        onSplitChange(pct);
      };

      const onUp = () => {
        isDragging.current = false;
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
      };

      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    },
    [onSplitChange],
  );

  return (
    <div ref={containerRef} className="flex h-full w-full flex-col overflow-hidden">
      {/* Top pane — flex-basis so it reliably fills its share of the flex column */}
      <div style={{ flex: `0 0 ${splitPercent}%`, minHeight: 0 }} className="overflow-hidden">
        {top}
      </div>

      {/* Drag handle */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize graph and editor"
        onPointerDown={handlePointerDown}
        className="group flex h-1.5 shrink-0 cursor-row-resize items-center
                   justify-center bg-stone-100 hover:bg-stone-200 transition-colors
                   dark:bg-zinc-800 dark:hover:bg-zinc-700"
      >
        <div className="h-0.5 w-8 rounded-full bg-stone-300 transition-colors group-hover:bg-stone-400
                        dark:bg-zinc-600 dark:group-hover:bg-zinc-500" />
      </div>

      {/* Bottom pane */}
      <div className="flex flex-1 overflow-hidden">{bottom}</div>
    </div>
  );
});
