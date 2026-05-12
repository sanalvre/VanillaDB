import { useEffect, useRef, useState, useCallback, lazy, Suspense } from "react";
import { useVaultStore } from "./stores/vaultStore";
import { useStatusStore } from "./stores/statusStore";
import { useEditorStore } from "./stores/editorStore";
import { useThemeStore } from "./stores/themeStore";
import { startVaultWatcher, stopVaultWatcher } from "./api/fileWatcher";
import { checkHealth } from "./api/sidecar";
import { DropZone } from "./components/layout/DropZone";
import { UrlBar } from "./components/layout/UrlBar";
import { IngestStatus } from "./components/layout/IngestStatus";
import { OnboardingFlow } from "./components/onboarding/OnboardingFlow";
import { ProposalPanel } from "./components/proposals/ProposalPanel";
import { FileTree } from "./components/layout/FileTree";
import { EditorPanel } from "./components/editor/EditorPanel";
import { ResizableSplit } from "./components/layout/ResizableSplit";
import { CommandPalette } from "./components/command/CommandPalette";
import { Logo } from "./components/layout/Logo";
import { SearchPanel } from "./components/layout/SearchPanel";
import { SettingsPanel } from "./components/settings/SettingsPanel";
import { SidebarRail, type SidebarPanel } from "./components/layout/SidebarRail";
import { ResearchPanel } from "./components/layout/ResearchPanel";
import { AgentPanel } from "./components/agent/AgentPanel";
import { useTauriSidecar } from "./hooks/useTauriSidecar";
import { PipelineProgress } from "./components/PipelineProgress";

// Lazy load graph (pulls Three.js ~500KB)
const GraphPanel = lazy(() =>
  import("./components/graph/GraphPanel").then((m) => ({
    default: m.GraphPanel,
  })),
);

function App() {
  const {
    initialized,
    loading,
    sidecarConnected,
    cleanVaultPath,
    wikiVaultPath,
    vaultWarnings,
    checkInitialization,
    setSidecarConnected,
    setVaultPaths,
  } = useVaultStore();

  const { agentStatus, currentPhase, pendingProposals, startPolling, stopPolling } =
    useStatusStore();

  // Wire Tauri sidecar port discovery (no-op in browser dev mode)
  useTauriSidecar();

  const { isDark, toggle: toggleDark } = useThemeStore();

  const graphVisible = useEditorStore((s) => s.graphVisible);
  const graphSplitPercent = useEditorStore((s) => s.graphSplitPercent);
  const setSplitPercent = useEditorStore((s) => s.setSplitPercent);
  const toggleGraph = useEditorStore((s) => s.toggleGraph);

  // Ingestion job tracking
  const [ingestJobs, setIngestJobs] = useState<
    Array<{
      jobId: string;
      label: string;
      status: "pending" | "processing" | "complete" | "error";
      progress: number;
    }>
  >([]);

  const handleIngestStarted = useCallback(
    (jobId: string, source: string) => {
      const label = source.split(/[/\\]/).pop() || source;
      setIngestJobs((prev) => [
        ...prev,
        { jobId, label, status: "pending", progress: 0 },
      ]);
    },
    [],
  );

  const handleIngestError = useCallback((error: string) => {
    console.error("Ingest error:", error);
  }, []);

  const handleJobComplete = useCallback(
    (_jobId: string, _outputPath: string) => {
      // File landed in clean-vault — tree auto-refreshes via polling
    },
    [],
  );

  // Proposal panel visibility
  const [proposalPanelOpen, setProposalPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Sidebar panel state (replaces searchOpen boolean)
  const [activePanel, setActivePanel] = useState<SidebarPanel>("files");

  // Listen for command palette opening proposals
  useEffect(() => {
    const handler = () => setProposalPanelOpen(true);
    window.addEventListener("vanilla:open-proposals", handler);
    return () => window.removeEventListener("vanilla:open-proposals", handler);
  }, []);

  // Auto-open panel when new proposals arrive
  useEffect(() => {
    if (pendingProposals > 0) {
      setProposalPanelOpen(true);
    }
  }, [pendingProposals]);

  // Check sidecar health and vault state on mount
  useEffect(() => {
    const init = async () => {
      try {
        const health = await checkHealth();
        setSidecarConnected(health.status === "ok");
      } catch {
        setSidecarConnected(false);
      }
      await checkInitialization();
    };

    init();
  }, [checkInitialization, setSidecarConnected]);

  // Start status polling when initialized and connected
  useEffect(() => {
    if (initialized && sidecarConnected) {
      startPolling();
      return () => stopPolling();
    }
  }, [initialized, sidecarConnected, startPolling, stopPolling]);

  // Reset editor state when vault is configured for the first time (false → true transition)
  const prevInitialized = useRef(initialized);
  useEffect(() => {
    if (!prevInitialized.current && initialized) {
      useEditorStore.getState().reset();
    }
    prevInitialized.current = initialized;
  }, [initialized]);

  // Start file watcher when vault paths are known
  useEffect(() => {
    if (cleanVaultPath && wikiVaultPath) {
      const vaultRoot = cleanVaultPath.replace(/\/clean-vault$/, "");
      startVaultWatcher(cleanVaultPath, wikiVaultPath, vaultRoot).catch(
        (err) => {
          console.warn("File watcher not available (dev mode?):", err);
        },
      );

      return () => {
        stopVaultWatcher();
      };
    }
  }, [cleanVaultPath, wikiVaultPath]);

  // Ambient clipboard clip — triggered by Tauri tray:clip-clipboard event
  useEffect(() => {
    let unlisten: (() => void) | null = null;

    (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const { readText } = await import("@tauri-apps/plugin-clipboard-manager");
        const { clipToVault } = await import("./stores/ambientStore");

        unlisten = await listen("tray:clip-clipboard", async () => {
          try {
            const text = await readText();
            if (text) await clipToVault(text);
          } catch (e) {
            console.warn("Clipboard clip failed:", e);
          }
        });
      } catch {
        // Not running inside Tauri — ignore
      }
    })();

    return () => unlisten?.();
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Cmd/Ctrl+Shift+G — toggle graph
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "g") {
        e.preventDefault();
        toggleGraph();
      }
      // Cmd/Ctrl+Shift+P — toggle proposals
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "p") {
        e.preventDefault();
        setProposalPanelOpen((o) => !o);
      }
      // Cmd/Ctrl+Shift+F — toggle search
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "f") {
        e.preventDefault();
        setActivePanel((p) => p === "search" ? "files" : "search");
      }
      // Cmd/Ctrl+Shift+A — toggle agent panel
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "a") {
        e.preventDefault();
        setActivePanel((p) => p === "agent" ? "files" : "agent");
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [toggleGraph]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center dark:bg-zinc-950">
        <p className="text-stone-500 dark:text-zinc-500">Loading Vanilla...</p>
      </div>
    );
  }

  return (
    <DropZone
      onIngestStarted={handleIngestStarted}
      onError={handleIngestError}
    >
      <div className="flex h-full flex-col">
        {/* Top bar */}
        <header className="flex items-center justify-between border-b border-[var(--glass-border)] bg-[var(--glass-bg-strong)] px-4 py-2 backdrop-blur-md dark:border-zinc-700/50">
          <Logo variant="full" size="lg" />
          <div className="flex items-center gap-2 text-sm text-stone-500 dark:text-zinc-400">
            {initialized && sidecarConnected && (
              <UrlBar
                onIngestStarted={handleIngestStarted}
                onError={handleIngestError}
              />
            )}

            {/* Dark / light mode toggle — sun in light mode, moon in dark mode */}
            <button
              onClick={toggleDark}
              className="rounded p-1.5 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            >
              {isDark ? (
                /* Sun icon shown in dark mode — click to go light */
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="8" r="2.8" stroke="currentColor" strokeWidth="1.4" />
                  <path
                    d="M8 1.5v1M8 13.5v1M1.5 8h1M13.5 8h1M3.4 3.4l.7.7M11.9 11.9l.7.7M11.9 3.4l-.7.7M4.1 11.9l-.7.7"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                /* Moon icon shown in light mode — click to go dark */
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M13.5 10A6 6 0 0 1 6 2.5a6 6 0 1 0 7.5 7.5z"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>

            {/* Settings gear */}
            <button
              onClick={() => setSettingsOpen((o) => !o)}
              className={`rounded p-1.5 transition-colors ${
                settingsOpen
                  ? "bg-stone-200 text-stone-700 dark:bg-zinc-700 dark:text-zinc-200"
                  : "text-stone-400 hover:bg-stone-100 hover:text-stone-700 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
              }`}
              title="Settings"
              aria-label="Open settings"
            >
              {/* Classic gear / cog icon */}
              <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z"
                />
              </svg>
            </button>

            <span
              className={`h-2 w-2 rounded-full ${
                sidecarConnected ? "bg-green-500" : "bg-red-400"
              }`}
              role="status"
              aria-label={sidecarConnected ? "Sidecar connected" : "Sidecar disconnected"}
              title={sidecarConnected ? "Connected" : "Disconnected"}
            />
          </div>
        </header>

        {/* Vault warnings */}
        {vaultWarnings.length > 0 && (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            <strong>Vault warnings:</strong>{" "}
            {vaultWarnings.join("; ")}
          </div>
        )}

        {/* Main content */}
        <main className="flex flex-1 overflow-hidden dark:bg-zinc-950">
          {!initialized ? (
            <OnboardingFlow
              onComplete={(cleanPath, wikiPath) => {
                setVaultPaths(cleanPath, wikiPath);
              }}
            />
          ) : (
            <div className="flex flex-1 dark:bg-zinc-900">
              {/* Left sidebar — icon rail + content panel */}
              <aside className="flex w-56 shrink-0 border-r border-[var(--glass-border)] bg-[var(--glass-bg)] backdrop-blur-md dark:border-zinc-700/40">
                {/* Icon rail */}
                <SidebarRail
                  activePanel={activePanel}
                  onPanelChange={setActivePanel}
                />

                {/* Content panel */}
                <div className="flex flex-1 flex-col overflow-hidden">
                  <div className="flex-1 overflow-y-auto">
                    {activePanel === "search" ? (
                      <SearchPanel onClose={() => setActivePanel("files")} />
                    ) : activePanel === "research" ? (
                      <ResearchPanel onIngestStarted={handleIngestStarted} />
                    ) : activePanel === "agent" ? (
                      <AgentPanel />
                    ) : (
                      <div className="px-2 py-1">
                        <FileTree />
                      </div>
                    )}
                  </div>

                  {/* Ingestion status at bottom of sidebar */}
                  <IngestStatus
                    jobs={ingestJobs}
                    onJobComplete={handleJobComplete}
                  />
                </div>
              </aside>

              {/* Right area — graph + editor or proposals */}
              <section className="flex flex-1 overflow-hidden dark:bg-zinc-900">
                {proposalPanelOpen ? (
                  <ProposalPanel
                    onClose={() => setProposalPanelOpen(false)}
                  />
                ) : graphVisible ? (
                  <ResizableSplit
                    splitPercent={graphSplitPercent}
                    onSplitChange={setSplitPercent}
                    top={
                      <Suspense
                        fallback={
                          <div className="flex h-full items-center justify-center text-sm text-stone-400">
                            Loading graph...
                          </div>
                        }
                      >
                        <GraphPanel />
                      </Suspense>
                    }
                    bottom={<EditorPanel />}
                  />
                ) : (
                  <EditorPanel />
                )}
              </section>
            </div>
          )}
        </main>

        {/* Bottom bar */}
        <footer className="flex items-center justify-between border-t border-stone-200 bg-white px-4 py-1.5 text-xs text-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-500">
          <div className="flex items-center gap-3">
            <span>
              Agent:{" "}
              <span
                className={
                  agentStatus === "running"
                    ? "text-blue-500 dark:text-blue-400"
                    : agentStatus === "error"
                      ? "text-red-500 dark:text-red-400"
                      : "dark:text-zinc-400"
                }
              >
                {agentStatus}
              </span>
            </span>
            {currentPhase && (
              <span className="text-blue-400">{currentPhase}</span>
            )}
          </div>
          <span>
            {pendingProposals > 0 ? (
              <button
                onClick={() => setProposalPanelOpen((o) => !o)}
                className="font-medium text-amber-600 underline-offset-2 hover:underline"
              >
                {pendingProposals} proposal{pendingProposals !== 1 ? "s" : ""}{" "}
                pending
              </button>
            ) : (
              "Up to date"
            )}
          </span>
        </footer>

        {/* Command palette overlay */}
        <CommandPalette />

        {/* Settings panel */}
        {settingsOpen && (
          <SettingsPanel onClose={() => setSettingsOpen(false)} />
        )}

        {/* Pipeline progress overlay — visible only during active runs */}
        <PipelineProgress />
      </div>
    </DropZone>
  );
}

export default App;
