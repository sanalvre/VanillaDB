/**
 * GraphSettings — floating settings panel for the graph visualization.
 *
 * Triggered by a gear icon button overlaid on the GraphPanel canvas.
 * All changes write directly to graphSettingsStore (persisted to localStorage).
 * Cluster mode changes also trigger a fetchClusters() call in graphStore.
 */

import { useRef, useEffect } from "react";
import {
  useGraphSettingsStore,
  type ColorMode,
  type NodeSizeMode,
} from "@/stores/graphSettingsStore";
import { useGraphStore } from "@/stores/graphStore";

interface Props {
  onClose: () => void;
}

// ─── Small UI primitives ────────────────────────────────────────────────────

function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 py-1">
      <span className="flex flex-col">
        <span className="text-[11px] font-medium text-zinc-200">{label}</span>
        {hint && <span className="text-[10px] text-zinc-500">{hint}</span>}
      </span>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-4 w-7 flex-shrink-0 rounded-full transition-colors focus:outline-none ${
          checked ? "bg-indigo-500" : "bg-zinc-600"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-[11px] font-medium text-zinc-200">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded bg-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-200 outline-none ring-1 ring-zinc-600 focus:ring-indigo-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  hint?: string;
}) {
  return (
    <div className="py-1">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-200">{label}</span>
        <span className="text-[10px] tabular-nums text-zinc-400">
          {value.toFixed(1)}×
        </span>
      </div>
      {hint && <p className="mb-1 text-[10px] text-zinc-500">{hint}</p>}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="h-1 w-full cursor-pointer accent-indigo-500"
      />
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1 text-[9px] font-semibold uppercase tracking-widest text-zinc-500">
        {title}
      </p>
      <div className="divide-y divide-zinc-700/50">{children}</div>
    </div>
  );
}

// ─── Main panel ─────────────────────────────────────────────────────────────

export function GraphSettings({ onClose }: Props) {
  const s = useGraphSettingsStore();
  const fetchClusters = useGraphStore((g) => g.fetchClusters);
  const clusterStatus = useGraphStore((g) => g.clusterStatus);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on click-outside
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  function handleClusterModeChange(mode: "none" | "topology" | "semantic") {
    s.set("clusterMode", mode);
    if (mode !== "none") {
      fetchClusters(mode);
    }
  }

  function handleColorModeChange(mode: ColorMode) {
    s.set("colorMode", mode);
    // Auto-sync cluster mode when switching to a cluster color mode
    if (mode === "cluster-topology" && s.clusterMode !== "topology") {
      handleClusterModeChange("topology");
    } else if (mode === "cluster-semantic" && s.clusterMode !== "semantic") {
      handleClusterModeChange("semantic");
    }
  }

  return (
    <div
      ref={panelRef}
      className="absolute right-2 top-10 z-20 w-56 overflow-hidden rounded-xl border border-zinc-700 bg-zinc-800/95 shadow-2xl backdrop-blur-sm"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-700 px-3 py-2">
        <span className="text-[11px] font-semibold text-zinc-200">
          Graph Settings
        </span>
        <button
          onClick={onClose}
          className="rounded p-0.5 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
          aria-label="Close settings"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <line
              x1="1"
              y1="1"
              x2="11"
              y2="11"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
            <line
              x1="11"
              y1="1"
              x2="1"
              y2="11"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>

      <div className="space-y-3 p-3">
        {/* Nodes */}
        <Section title="Nodes">
          <Select<ColorMode>
            label="Color by"
            value={s.colorMode}
            options={[
              { value: "category", label: "Category" },
              { value: "cluster-topology", label: "Link clusters" },
              { value: "cluster-semantic", label: "Semantic clusters" },
              { value: "uniform", label: "Uniform" },
            ]}
            onChange={handleColorModeChange}
          />
          <Select<NodeSizeMode>
            label="Size by"
            value={s.nodeSizeMode}
            options={[
              { value: "degree", label: "Connections" },
              { value: "citations", label: "Source citations" },
              { value: "uniform", label: "Uniform" },
            ]}
            onChange={(v) => s.set("nodeSizeMode", v)}
          />
          <Toggle
            label="Dim on hover"
            checked={s.dimUnhoveredNodes}
            onChange={(v) => s.set("dimUnhoveredNodes", v)}
            hint="Highlights hovered node's neighbors"
          />
          <Slider
            label="Label zoom"
            value={s.labelZoomThreshold}
            min={0.4}
            max={2.0}
            step={0.1}
            onChange={(v) => s.set("labelZoomThreshold", v)}
            hint="Scale at which labels appear"
          />
        </Section>

        {/* Edges */}
        <Section title="Edges">
          <Toggle
            label="Color by type"
            checked={s.showEdgeTypeColors}
            onChange={(v) => s.set("showEdgeTypeColors", v)}
          />
          <Toggle
            label="Directional particles"
            checked={s.showEdgeParticles}
            onChange={(v) => s.set("showEdgeParticles", v)}
          />
          <Toggle
            label="Type labels"
            checked={s.showEdgeLabels}
            onChange={(v) => s.set("showEdgeLabels", v)}
          />
        </Section>

        {/* Clusters */}
        <Section title="Clusters">
          <Select
            label="Cluster by"
            value={s.clusterMode}
            options={[
              { value: "none", label: "Off" },
              { value: "topology", label: "Link structure" },
              { value: "semantic", label: "Semantic similarity" },
            ]}
            onChange={handleClusterModeChange}
          />

          {/* Status feedback */}
          {s.clusterMode !== "none" && clusterStatus.state === "loading" && (
            <p className="py-1 text-[10px] text-zinc-400">Computing clusters…</p>
          )}
          {s.clusterMode !== "none" && clusterStatus.state === "error" && (
            <p className="py-1 text-[10px] leading-tight text-amber-400">
              {clusterStatus.message}
            </p>
          )}
          {s.clusterMode !== "none" && clusterStatus.state === "ready" && (
            <p className="py-1 text-[10px] text-zinc-500">
              {clusterStatus.clusterCount} clusters found
            </p>
          )}

          <Toggle
            label="Hull overlay"
            checked={s.showHulls}
            onChange={(v) => s.set("showHulls", v)}
            hint="Draws a shape around each cluster"
          />
          <Toggle
            label="Force grouping"
            checked={s.forceGrouping}
            onChange={(v) => s.set("forceGrouping", v)}
            hint="Drifts clusters apart in the layout"
          />
        </Section>

        {/* Reset */}
        <button
          onClick={s.reset}
          className="w-full rounded py-1 text-[10px] text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
        >
          Reset to defaults
        </button>
      </div>
    </div>
  );
}
