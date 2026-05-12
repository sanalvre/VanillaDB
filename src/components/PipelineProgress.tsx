import { usePipelineEvents } from "../hooks/usePipelineEvents";

const AGENT_ORDER = ["ingest", "analysis", "proposal", "review", "fileback"];

interface AgentStatus {
  status: "pending" | "running" | "success" | "error";
  duration?: number;
  tokens?: number;
  message?: string;
}

export function PipelineProgress() {
  const { events, connected, currentRun } = usePipelineEvents();

  if (!currentRun) return null;

  const agentStatuses = new Map<string, AgentStatus>(
    AGENT_ORDER.map((a) => [a, { status: "pending" }])
  );

  events
    .filter((e) => e.data.run_id === currentRun)
    .forEach((e) => {
      const agent = e.data.agent as string;
      if (!agent) return;

      if (e.type === "agent.started") {
        agentStatuses.set(agent, { status: "running" });
      } else if (e.type === "agent.completed") {
        agentStatuses.set(agent, {
          status: e.data.status === "success" ? "success" : "error",
          duration: e.data.duration_ms as number,
          tokens: (e.data.tokens_in as number) + (e.data.tokens_out as number),
        });
      } else if (e.type === "agent.progress") {
        const current = agentStatuses.get(agent);
        if (current) {
          agentStatuses.set(agent, {
            ...current,
            message: e.data.message as string,
          });
        }
      }
    });

  const latestProgress = events.filter((e) => e.type === "agent.progress").at(-1);

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 rounded-lg border border-zinc-700 bg-zinc-900 p-4 shadow-xl">
      <div className="mb-3 flex items-center gap-2">
        <div
          className={`h-2 w-2 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`}
        />
        <span className="font-mono text-xs uppercase tracking-wider text-zinc-400">
          Pipeline running
        </span>
      </div>

      <div className="space-y-2">
        {AGENT_ORDER.map((agent) => {
          const s = agentStatuses.get(agent)!;
          return (
            <div key={agent} className="flex items-center gap-3">
              <div
                className={`h-1.5 w-1.5 rounded-full ${
                  s.status === "running"
                    ? "animate-pulse bg-blue-400"
                    : s.status === "success"
                      ? "bg-green-400"
                      : s.status === "error"
                        ? "bg-red-400"
                        : "bg-zinc-600"
                }`}
              />
              <span
                className={`flex-1 text-sm ${
                  s.status === "pending" ? "text-zinc-600" : "text-zinc-300"
                }`}
              >
                {agent}
              </span>
              {s.duration != null && (
                <span className="font-mono text-xs text-zinc-500">
                  {(s.duration / 1000).toFixed(1)}s
                </span>
              )}
              {s.tokens != null && (
                <span className="font-mono text-xs text-zinc-600">
                  {s.tokens.toLocaleString()}t
                </span>
              )}
            </div>
          );
        })}
      </div>

      {latestProgress && (
        <div className="mt-3 truncate text-xs italic text-zinc-500">
          {latestProgress.data.message as string}
        </div>
      )}
    </div>
  );
}
