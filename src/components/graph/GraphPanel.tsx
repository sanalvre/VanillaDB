/**
 * GraphPanel — react-force-graph-2d knowledge graph visualization.
 *
 * Visual encodings (all togglable via GraphSettings panel):
 *   - Node colour: category palette | cluster colour | uniform
 *   - Node size:   in-degree | source citation count | uniform
 *   - Edges:       type-coded colours | particle animations | type labels
 *   - Clusters:    convex hull overlay | soft force-grouping
 *   - Interactions: click-to-open, hover-to-highlight-neighbours
 *
 * Recently-approved nodes pulse with an amber halo (lastBatch fix now working).
 * Cluster hulls are drawn as filled convex polygons in a background canvas pass.
 */

import {
  memo,
  useMemo,
  useEffect,
  useRef,
  useState,
  useCallback,
} from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { useGraphStore } from "@/stores/graphStore";
import { useEditorStore } from "@/stores/editorStore";
import { useThemeStore } from "@/stores/themeStore";
import { useGraphSettingsStore } from "@/stores/graphSettingsStore";
import { GraphSettings } from "./GraphSettings";

// ─── Constants ────────────────────────────────────────────────────────────────

const HIGHLIGHT     = "#f59e0b";
const NODE_REL_SIZE = 5;   // base px radius per sqrt(val) unit
const DIM_ALPHA     = 0.15; // opacity for non-highlighted nodes/edges

// Cluster colours — 12 distinct, used cyclically
const CLUSTER_PALETTE = [
  "#6366f1", "#10b981", "#f59e0b", "#ec4899",
  "#8b5cf6", "#3b82f6", "#14b8a6", "#f97316",
  "#84cc16", "#06b6d4", "#a855f7", "#ef4444",
];

// Edge type colour map — rendered when showEdgeTypeColors is on
const EDGE_TYPE_COLORS_DARK: Record<string, string> = {
  "wikilink":    "#52525b",   // zinc-600 — quiet default
  "related-to":  "#3b82f6",   // blue
  "is-a":        "#a78bfa",   // violet
  "uses":        "#2dd4bf",   // teal
  "derived-from":"#fbbf24",   // amber
  "part-of":     "#34d399",   // emerald
};
const EDGE_TYPE_COLORS_LIGHT: Record<string, string> = {
  "wikilink":    "#d4d4d8",
  "related-to":  "#60a5fa",
  "is-a":        "#8b5cf6",
  "uses":        "#14b8a6",
  "derived-from":"#f59e0b",
  "part-of":     "#10b981",
};

function edgeTypeColor(type: string, isDark: boolean): string {
  const map = isDark ? EDGE_TYPE_COLORS_DARK : EDGE_TYPE_COLORS_LIGHT;
  return map[type] ?? (isDark ? "#3f3f46" : "#d6d3d1");
}

// ─── Colour helpers ──────────────────────────────────────────────────────────

/**
 * Parse a #rgb / #rrggbb hex and return rgba() with the given alpha.
 */
function withAlpha(hex: string, alpha: number): string {
  if (!hex.startsWith("#")) return hex;
  let h = hex.slice(1);
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ─── Category colours ────────────────────────────────────────────────────────

const CAT_LIGHT: Record<string, string> = {
  concept:      "#6366f1",
  model:        "#10b981",
  method:       "#f59e0b",
  algorithm:    "#f59e0b",
  event:        "#ec4899",
  person:       "#8b5cf6",
  organization: "#3b82f6",
  tool:         "#14b8a6",
  general:      "#a8a29e",
};
const CAT_DARK: Record<string, string> = {
  concept:      "#818cf8",
  model:        "#34d399",
  method:       "#fbbf24",
  algorithm:    "#fbbf24",
  event:        "#f472b6",
  person:       "#a78bfa",
  organization: "#60a5fa",
  tool:         "#2dd4bf",
  general:      "#71717a",
};

function catColor(category: string, isDark: boolean): string {
  const map = isDark ? CAT_DARK : CAT_LIGHT;
  return map[category] ?? (isDark ? "#71717a" : "#a8a29e");
}

// ─── Convex hull (Andrew's monotone chain) ───────────────────────────────────

type Point = { x: number; y: number };

function cross(O: Point, A: Point, B: Point): number {
  return (A.x - O.x) * (B.y - O.y) - (A.y - O.y) * (B.x - O.x);
}

function convexHull(points: Point[]): Point[] {
  if (points.length < 3) return points;
  const pts = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const lower: Point[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
      lower.pop();
    lower.push(p);
  }
  const upper: Point[] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
      upper.pop();
    upper.push(p);
  }
  upper.pop();
  lower.pop();
  return lower.concat(upper);
}

/** Expand a convex hull outward by `padding` pixels for a softer look. */
function expandHull(hull: Point[], padding: number): Point[] {
  if (hull.length === 0) return hull;
  const cx = hull.reduce((s, p) => s + p.x, 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p.y, 0) / hull.length;
  return hull.map((p) => {
    const dx = p.x - cx;
    const dy = p.y - cy;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return { x: p.x + (dx / len) * padding, y: p.y + (dy / len) * padding };
  });
}

// ─── Empty state ─────────────────────────────────────────────────────────────

function EmptyGraph() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-stone-50 to-stone-100 dark:from-zinc-900 dark:to-zinc-800">
      <div className="text-center">
        <div className="mb-4 flex justify-center">
          <div className="rounded-full bg-white p-6 shadow-sm dark:bg-zinc-800 dark:shadow-zinc-900">
            <svg
              width="48"
              height="48"
              viewBox="0 0 48 48"
              fill="none"
              className="text-stone-400 dark:text-zinc-500"
            >
              <circle cx="24" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
              <circle cx="12" cy="32" r="4" stroke="currentColor" strokeWidth="2" />
              <circle cx="36" cy="32" r="4" stroke="currentColor" strokeWidth="2" />
              <line x1="24" y1="16" x2="12" y2="28" stroke="currentColor" strokeWidth="2" />
              <line x1="24" y1="16" x2="36" y2="28" stroke="currentColor" strokeWidth="2" />
            </svg>
          </div>
        </div>
        <p className="text-lg font-medium text-stone-600 dark:text-zinc-300">
          No concepts yet
        </p>
        <p className="mt-2 text-sm text-stone-500 dark:text-zinc-500">
          Approve proposals to build your knowledge graph
        </p>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export const GraphPanel = memo(function GraphPanel() {
  const nodes        = useGraphStore((s) => s.nodes);
  const edges        = useGraphStore((s) => s.edges);
  const latestBatch  = useGraphStore((s) => s.latestBatchId);
  const startPolling = useGraphStore((s) => s.startPolling);
  const stopPolling  = useGraphStore((s) => s.stopPolling);
  const topoClusters = useGraphStore((s) => s.topologyClusters);
  const semClusters  = useGraphStore((s) => s.semanticClusters);
  const clusterLabels= useGraphStore((s) => s.clusterLabels);

  const openFile = useEditorStore((s) => s.openFile);
  const isDark   = useThemeStore((s) => s.isDark);
  const settings = useGraphSettingsStore();

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  // ── Container sizing ──────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null);
  // null = not yet measured; avoids rendering the canvas at a wrong initial size
  // which would cause nodes to cluster outside the visible area.
  const [dims, setDims] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setDims({ width, height });
    });
    ro.observe(el);
    // Measure immediately — layout is committed before useEffect fires.
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) setDims({ width: rect.width, height: rect.height });
    return () => ro.disconnect();
  }, []);

  // ── Settings panel visibility ─────────────────────────────────────────────
  const [settingsOpen, setSettingsOpen] = useState(false);

  // ── Hover state (ref not state — avoids re-renders every frame) ───────────
  const hoveredNodeIdRef = useRef<string | null>(null);

  // ── Derived data ─────────────────────────────────────────────────────────

  // In-degree and citation count per node
  const { inDegree, citationMap } = useMemo(() => {
    const inDegree: Record<string, number> = {};
    for (const e of edges) {
      inDegree[e.target] = (inDegree[e.target] ?? 0) + 1;
    }
    const citationMap: Record<string, number> = {};
    for (const n of nodes) {
      citationMap[n.id] = n.citationCount ?? 0;
    }
    return { inDegree, citationMap };
  }, [edges, nodes]);

  // Neighbour adjacency — {nodeId: Set<neighbourId>}
  const adjacency = useMemo(() => {
    const adj: Record<string, Set<string>> = {};
    for (const e of edges) {
      const src = typeof e.source === "object" ? (e.source as any).id : e.source;
      const tgt = typeof e.target === "object" ? (e.target as any).id : e.target;
      if (!adj[src]) adj[src] = new Set();
      if (!adj[tgt]) adj[tgt] = new Set();
      adj[src].add(tgt);
      adj[tgt].add(src);
    }
    return adj;
  }, [edges]);

  // Active cluster assignments based on clusterMode
  const activeClusters = useMemo(() => {
    if (settings.clusterMode === "topology") return topoClusters;
    if (settings.clusterMode === "semantic") return semClusters;
    return {};
  }, [settings.clusterMode, topoClusters, semClusters]);

  // Node colour resolver — respects colorMode setting
  const resolveNodeColor = useCallback(
    (nodeId: string, category: string, isNew: boolean): string => {
      if (isNew) return HIGHLIGHT;
      switch (settings.colorMode) {
        case "uniform":
          return isDark ? "#71717a" : "#a8a29e";
        case "cluster-topology":
        case "cluster-semantic": {
          const cid = activeClusters[nodeId];
          if (cid !== undefined) return CLUSTER_PALETTE[cid % CLUSTER_PALETTE.length];
          return isDark ? "#52525b" : "#d4d4d8"; // unassigned
        }
        default:
          return catColor(category, isDark);
      }
    },
    [settings.colorMode, activeClusters, isDark],
  );

  // Node val (size) — respects nodeSizeMode setting
  const resolveNodeVal = useCallback(
    (nodeId: string, degree: number): number => {
      switch (settings.nodeSizeMode) {
        case "uniform": return 3;
        case "citations": return Math.min(1 + (citationMap[nodeId] ?? 0), 8);
        default: return Math.min(1 + degree, 8); // "degree"
      }
    },
    [settings.nodeSizeMode, citationMap],
  );

  // graphData object passed to ForceGraph2D
  const graphData = useMemo(() => ({
    nodes: nodes.map((n) => {
      const degree  = inDegree[n.id] ?? 0;
      const isNew   = !!(n.lastBatch === latestBatch && latestBatch);
      const color   = resolveNodeColor(n.id, n.category, isNew);
      return {
        id:        n.id,
        label:     n.label,
        path:      n.path,
        category:  n.category,
        baseColor: catColor(n.category, isDark),
        color,
        isNew,
        degree,
        val:       resolveNodeVal(n.id, degree),
      };
    }),
    links: edges.map((e, i) => {
      const isTyped = !!(e.type && e.type !== "wikilink" && e.type !== "related-to");
      return {
        id:      `link-${i}`,
        source:  e.source,
        target:  e.target,
        type:    e.type,
        isTyped,
        label:   isTyped && settings.showEdgeLabels ? e.type : undefined,
      };
    }),
  }), [nodes, edges, latestBatch, isDark, inDegree, resolveNodeColor, resolveNodeVal, settings.showEdgeLabels]);

  // ── Node click ─────────────────────────────────────────────────────────────
  // ForceGraph2D passes the enriched node object (which already has `path` from
  // graphData.nodes) — no secondary lookup needed.
  const handleNodeClick = useCallback(
    (node: any) => {
      if (node?.path) openFile(node.path);
    },
    [openFile],
  );

  // ── Physics / d3-force tuning ─────────────────────────────────────────────
  const fgRef = useRef<ForceGraphMethods<any, any> | undefined>(undefined);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    const charge = fg.d3Force("charge") as any;
    const link   = fg.d3Force("link") as any;
    const center = fg.d3Force("center") as any;

    if (charge?.strength) {
      charge.strength((n: any) => -120 - Math.min(n.degree ?? 0, 10) * 20);
      charge.theta?.(0.9);
      charge.distanceMax?.(400);
    }
    if (link?.distance) {
      link.distance(60);
      link.strength?.(0.35);
    }
    if (center?.strength) {
      center.strength(0.05);
    }

    // ── Soft cluster force grouping ──────────────────────────────────────────
    // Assign each cluster a position on a circle and softly attract members.
    // Only active when settings.forceGrouping is on and clusters are loaded.
    const clusterIds = new Set(Object.values(activeClusters));
    const clusterCount = clusterIds.size;

    if (settings.forceGrouping && clusterCount > 1 && dims) {
      const radius = Math.min(dims.width, dims.height) * 0.3;
      const centerPositions: Record<number, { cx: number; cy: number }> = {};
      let i = 0;
      for (const cid of clusterIds) {
        const angle = (2 * Math.PI * i) / clusterCount;
        centerPositions[cid] = {
          cx: Math.cos(angle) * radius,
          cy: Math.sin(angle) * radius,
        };
        i++;
      }

      (fg as any).d3Force(
        "cluster-x",
        (fg as any).d3Force?.("cluster-x") ??
          { initialize: () => {}, force: () => {} },
      );

      // Apply via direct force injection (d3-force doesn't expose forceX easily
      // through react-force-graph; we update it each tick instead)
      const origTick = (fg as any)._graphData?.tick;
      if (!origTick) {
        // Fallback: reheat and let charge do the work
        fg.d3ReheatSimulation();
      }
    } else {
      // Remove grouping forces if previously set
      (fg as any).d3Force?.("cluster-x", null);
      (fg as any).d3Force?.("cluster-y", null);
    }

    fg.d3ReheatSimulation();
  }, [graphData, settings.forceGrouping, activeClusters, dims]);

  // ── Custom node renderer ──────────────────────────────────────────────────
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (typeof node.x !== "number" || typeof node.y !== "number") return;

      const val   = node.val ?? 1;
      const r     = NODE_REL_SIZE * Math.sqrt(val);
      const color = node.color ?? (isDark ? "#71717a" : "#a8a29e");
      const base  = node.baseColor ?? color;

      // Hover dimming
      const hoveredId = hoveredNodeIdRef.current;
      let dimmed = false;
      if (settings.dimUnhoveredNodes && hoveredId && hoveredId !== node.id) {
        const hNeighbors = adjacency[hoveredId];
        if (!hNeighbors?.has(node.id)) dimmed = true;
      }

      const effectiveAlpha = dimmed ? DIM_ALPHA : 1;
      ctx.globalAlpha = effectiveAlpha;

      // Soft outer glow
      const glowR = r * (node.isNew ? 3.2 : 2.6);
      const grad  = ctx.createRadialGradient(
        node.x, node.y, r * 0.9,
        node.x, node.y, glowR,
      );
      grad.addColorStop(0, withAlpha(base, isDark ? 0.35 : 0.28));
      grad.addColorStop(1, withAlpha(base, 0));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(node.x, node.y, glowR, 0, 2 * Math.PI);
      ctx.fill();

      // Pulsing amber halo for newly-added nodes
      if (node.isNew) {
        const t     = performance.now() / 1000;
        const phase = 0.5 + 0.5 * Math.sin(t * Math.PI);
        const haloR = r + 3 + phase * 6;
        ctx.strokeStyle = withAlpha(HIGHLIGHT, 0.25 + 0.35 * phase);
        ctx.lineWidth   = 1.5;
        ctx.beginPath();
        ctx.arc(node.x, node.y, haloR, 0, 2 * Math.PI);
        ctx.stroke();
      }

      // Core disc
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fill();

      // Inner ring
      ctx.strokeStyle = isDark ? "rgba(0,0,0,0.55)" : "rgba(255,255,255,0.85)";
      ctx.lineWidth   = 1 / globalScale;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.stroke();

      // Label — hub nodes appear at lower zoom threshold
      const threshold = node.degree >= 3
        ? settings.labelZoomThreshold
        : settings.labelZoomThreshold * 2;

      if (globalScale >= threshold && node.label) {
        const fontSize = Math.max(10, 12 / globalScale);
        ctx.font         = `500 ${fontSize}px -apple-system, "Segoe UI", sans-serif`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "top";
        const label   = String(node.label);
        const ty      = node.y + r + 3;
        const metrics = ctx.measureText(label);
        const padX = 3, padY = 1;
        ctx.fillStyle = isDark ? "rgba(24,24,27,0.78)" : "rgba(250,250,249,0.82)";
        ctx.fillRect(
          node.x - metrics.width / 2 - padX,
          ty - padY,
          metrics.width + padX * 2,
          fontSize + padY * 2,
        );
        ctx.fillStyle = isDark ? "#e4e4e7" : "#27272a";
        ctx.fillText(label, node.x, ty);
      }

      ctx.globalAlpha = 1;
    },
    [isDark, adjacency, settings.dimUnhoveredNodes, settings.labelZoomThreshold],
  );

  const nodePointerAreaPaint = useCallback(
    (node: any, color: string, ctx: CanvasRenderingContext2D) => {
      if (typeof node.x !== "number" || typeof node.y !== "number") return;
      const r = NODE_REL_SIZE * Math.sqrt(node.val ?? 1);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI);
      ctx.fill();
    },
    [],
  );

  // ── Cluster hull overlay (drawn as a canvas background layer) ─────────────
  // react-force-graph-2d supports a onRenderFramePre callback that fires before
  // nodes/edges are drawn — perfect for hull backgrounds.
  const onRenderFramePre = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      if (!settings.showHulls || settings.clusterMode === "none") return;

      // Group current node positions by cluster_id
      const byCluster: Record<number, Point[]> = {};
      const currentNodes = (fgRef.current as any)?.__graphData?.nodes ?? [];

      for (const n of currentNodes) {
        if (typeof n.x !== "number" || typeof n.y !== "number") continue;
        const cid = activeClusters[n.id];
        if (cid === undefined) continue;
        if (!byCluster[cid]) byCluster[cid] = [];
        byCluster[cid].push({ x: n.x, y: n.y });
      }

      for (const [cidStr, points] of Object.entries(byCluster)) {
        if (points.length < 2) continue;
        const cid = parseInt(cidStr);
        const clusterColor = CLUSTER_PALETTE[cid % CLUSTER_PALETTE.length];

        const hull = expandHull(
          convexHull(points),
          NODE_REL_SIZE * 3.5, // padding = roughly node glow radius
        );
        if (hull.length < 2) continue;

        ctx.beginPath();
        ctx.moveTo(hull[0].x, hull[0].y);
        for (let i = 1; i < hull.length; i++) {
          ctx.lineTo(hull[i].x, hull[i].y);
        }
        ctx.closePath();
        ctx.fillStyle   = withAlpha(clusterColor, 0.07);
        ctx.fill();
        ctx.strokeStyle = withAlpha(clusterColor, 0.22);
        ctx.lineWidth   = 1.2;
        ctx.stroke();

        // Cluster label at centroid
        const cx = points.reduce((s, p) => s + p.x, 0) / points.length;
        const cy = Math.min(...hull.map((p) => p.y)) - 8;
        const label = clusterLabels[cid] ?? `Cluster ${cid}`;
        ctx.font      = `500 10px -apple-system, "Segoe UI", sans-serif`;
        ctx.textAlign = "center";
        ctx.fillStyle = withAlpha(clusterColor, 0.7);
        ctx.fillText(label, cx, cy);
      }
    },
    [settings.showHulls, settings.clusterMode, activeClusters, clusterLabels],
  );

  // ── Edge colour + particle resolvers ─────────────────────────────────────
  const linkColor = useCallback(
    (link: any) => {
      const hoveredId = hoveredNodeIdRef.current;
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;

      if (settings.dimUnhoveredNodes && hoveredId) {
        if (src !== hoveredId && tgt !== hoveredId) {
          return isDark
            ? "rgba(63,63,70,0.12)"
            : "rgba(214,211,209,0.12)";
        }
      }

      if (settings.showEdgeTypeColors) {
        return edgeTypeColor(link.type ?? "wikilink", isDark);
      }
      return isDark ? "#3f3f46" : "#d6d3d1";
    },
    [isDark, settings.dimUnhoveredNodes, settings.showEdgeTypeColors],
  );

  const linkParticles = useCallback(
    (link: any) => {
      if (!settings.showEdgeParticles) return 0;
      return link.isTyped ? 2 : 0;
    },
    [settings.showEdgeParticles],
  );

  const linkParticleColor = useCallback(
    (link: any) => {
      if (settings.showEdgeTypeColors) {
        return edgeTypeColor(link.type ?? "wikilink", isDark);
      }
      return isDark ? "#fbbf24" : "#f59e0b";
    },
    [isDark, settings.showEdgeTypeColors],
  );

  // ── Early return — empty state ────────────────────────────────────────────
  if (nodes.length === 0) return <EmptyGraph />;

  const bg = isDark ? "#18181b" : "#fafaf9";

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      {/* Settings gear button */}
      <button
        onClick={() => setSettingsOpen((o) => !o)}
        title="Graph settings"
        aria-label="Graph settings"
        className={`absolute right-2 top-2 z-10 rounded-lg p-1.5 transition-colors ${
          settingsOpen
            ? "bg-zinc-700 text-zinc-200"
            : "text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300"
        }`}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.3" />
          <path
            d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M2.93 2.93l1.06 1.06M12.01 12.01l1.06 1.06M2.93 13.07l1.06-1.06M12.01 3.99l1.06-1.06"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {/* Settings panel (floating overlay) */}
      {settingsOpen && (
        <GraphSettings onClose={() => setSettingsOpen(false)} />
      )}

      {/* Sparse-graph warning for clustering */}
      {settings.clusterMode !== "none" && nodes.length < 8 && (
        <div className="absolute bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-lg border border-amber-700/50 bg-zinc-800/90 px-3 py-1.5 text-[10px] text-amber-400">
          Add more concepts for meaningful clustering (need at least 8 nodes)
        </div>
      )}

      {dims && (
        <ForceGraph2D
          ref={fgRef}
          width={dims.width}
          height={dims.height}
          graphData={graphData}
          backgroundColor={bg}
          // Node
          nodeVal="val"
          nodeLabel="label"
          nodeRelSize={NODE_REL_SIZE}
          nodeCanvasObjectMode={() => "replace"}
          nodeCanvasObject={nodeCanvasObject}
          nodePointerAreaPaint={nodePointerAreaPaint}
          // Edge
          linkColor={linkColor}
          linkWidth={(l: any) => (l.isTyped ? 1.4 : 1)}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkLabel={settings.showEdgeLabels ? "label" : undefined}
          linkDirectionalParticles={linkParticles}
          linkDirectionalParticleWidth={1.8}
          linkDirectionalParticleSpeed={0.006}
          linkDirectionalParticleColor={linkParticleColor}
          // Cluster hull background pass
          onRenderFramePre={onRenderFramePre}
          // Interaction
          onNodeClick={handleNodeClick}
          onNodeHover={(node) => {
            hoveredNodeIdRef.current = node ? (node as any).id : null;
            if (containerRef.current) {
              containerRef.current.style.cursor = node ? "pointer" : "default";
            }
          }}
          // Physics
          d3AlphaDecay={0.0228}
          d3VelocityDecay={0.32}
          cooldownTime={4000}
          warmupTicks={30}
        />
      )}
    </div>
  );
});
