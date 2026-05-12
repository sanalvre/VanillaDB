import { useState, useEffect, useCallback } from "react";
import { useVaultStore } from "@/stores/vaultStore";

export interface PipelineEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export function usePipelineEvents() {
  const sidecarPort = useVaultStore((s) => s.sidecarPort);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [currentRun, setCurrentRun] = useState<string | null>(null);

  useEffect(() => {
    if (!sidecarPort) return;

    const sidecarUrl = `http://127.0.0.1:${sidecarPort}`;
    const source = new EventSource(`${sidecarUrl}/events`);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const handleEvent = (type: string) => (e: MessageEvent) => {
      const data = JSON.parse(e.data) as Record<string, unknown>;
      const event: PipelineEvent = { type, data, timestamp: Date.now() };

      setEvents((prev) => [...prev.slice(-100), event]); // keep last 100

      if (type === "pipeline.started") setCurrentRun(data.run_id as string);
      if (type === "pipeline.completed") setCurrentRun(null);
    };

    const eventTypes = [
      "pipeline.started",
      "pipeline.completed",
      "agent.started",
      "agent.completed",
      "agent.progress",
      "agent.tool_call",
    ];

    eventTypes.forEach((type) => {
      source.addEventListener(type, handleEvent(type));
    });

    return () => source.close();
  }, [sidecarPort]);

  const clearEvents = useCallback(() => setEvents([]), []);

  return { events, connected, currentRun, clearEvents };
}
