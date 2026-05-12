/**
 * SidebarRail — narrow icon strip on the far left of the sidebar.
 * Controls which content panel is active: files, search, or research.
 */

import { memo } from "react";

export type SidebarPanel = "files" | "search" | "research" | "agent";

interface RailButtonProps {
  active: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  indicator?: "recording";
}

function RailButton({ active, title, onClick, children, indicator }: RailButtonProps) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-colors
        ${active
          ? "text-amber-600 dark:text-amber-400"
          : "text-stone-400 hover:text-stone-600 dark:text-zinc-500 dark:hover:text-zinc-300"
        }`}
    >
      {/* Active indicator — left amber bar */}
      {active && (
        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r bg-amber-500" />
      )}
      {children}
      {/* Recording indicator dot */}
      {indicator === "recording" && (
        <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
      )}
    </button>
  );
}

interface SidebarRailProps {
  activePanel: SidebarPanel;
  onPanelChange: (panel: SidebarPanel) => void;
}

export const SidebarRail = memo(function SidebarRail({
  activePanel,
  onPanelChange,
}: SidebarRailProps) {
  return (
    <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 border-r border-[var(--glass-border)] py-2">
      {/* Files */}
      <RailButton
        active={activePanel === "files"}
        title="Files"
        onClick={() => onPanelChange("files")}
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <path d="M3 2h7l3 3v9H3z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          <path d="M10 2v3h3" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          <line x1="5" y1="8" x2="11" y2="8" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <line x1="5" y1="10.5" x2="9" y2="10.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      </RailButton>

      {/* Search */}
      <RailButton
        active={activePanel === "search"}
        title="Search (Ctrl+Shift+F)"
        onClick={() => onPanelChange("search")}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.4" />
          <line x1="10" y1="10" x2="14" y2="14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </RailButton>

      {/* Research */}
      <RailButton
        active={activePanel === "research"}
        title="Browser Research"
        onClick={() => onPanelChange("research")}
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 2c-1.5 2-2 3.5-2 6s.5 4 2 6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M8 2c1.5 2 2 3.5 2 6s-.5 4-2 6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <line x1="2" y1="8" x2="14" y2="8" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          {/* Spark */}
          <path d="M12.5 3.5l-1 1.5h1.5l-1 1.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </RailButton>

      {/* Agent */}
      <RailButton
        active={activePanel === "agent"}
        title="Agent (⌘⇧A)"
        onClick={() => onPanelChange("agent")}
      >
        {/* Bot / agent icon */}
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <rect x="2" y="5" width="12" height="9" rx="2" stroke="currentColor" strokeWidth="1.3" />
          <circle cx="5.5" cy="9.5" r="1" fill="currentColor" />
          <circle cx="10.5" cy="9.5" r="1" fill="currentColor" />
          <path d="M8 2v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="8" cy="1.5" r="0.8" fill="currentColor" />
        </svg>
      </RailButton>

      {/* Spacer */}
      <div className="flex-1" />
    </div>
  );
});
