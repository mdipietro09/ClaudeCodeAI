import { useEffect, useMemo, useState } from "react";
import { STATUS } from "./data/team.js";
import useTeam from "./hooks/useTeam.js";
import OfficeMap from "./components/OfficeMap.jsx";
import SidePanel from "./components/SidePanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import Legend from "./components/Legend.jsx";
import { STATUS_COLOR } from "./components/AgentAvatar.jsx";

export default function App() {
  const { agents, chat, busyAgentId, connected, sendMessage, resetSession } = useTeam();
  const [selectedId, setSelectedId] = useState(null);
  const [now, setNow] = useState(Date.now());

  const handleReset = () => {
    if (busyAgentId) return;
    if (!window.confirm("Reset the session? This clears the chat and every agent's history.")) return;
    resetSession();
    setSelectedId(null);
  };

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const selected = agents.find((a) => a.id === selectedId) ?? null;

  const counts = useMemo(() => {
    const c = { [STATUS.WORKING]: 0, [STATUS.WAITING]: 0, [STATUS.ERROR]: 0, [STATUS.IDLE]: 0 };
    for (const a of agents) c[a.status]++;
    return c;
  }, [agents]);

  return (
    <div className="mx-auto flex h-screen max-w-[1500px] flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-neutral-100">🏢 AI Agent Office</h1>
          <p className="text-xs text-neutral-500">
            {agents.length > 0
              ? agents.map((a) => `${a.emoji} ${a.name}`).join(" · ") + " — powered by Ollama · click an agent for details"
              : "waiting for the Python backend…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {Object.entries(counts).map(([status, n]) => (
            <div key={status} className="flex items-center gap-1.5 rounded-lg border border-neutral-800 bg-neutral-950 px-2.5 py-1 text-sm">
              <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[status] }} />
              <span className="font-mono font-semibold text-neutral-200">{n}</span>
            </div>
          ))}
          <span
            className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${connected ? "text-emerald-400" : "text-red-400"}`}
          >
            <span className="relative flex h-2 w-2">
              {connected && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              )}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} />
            </span>
            {connected ? "Live" : "Offline"}
          </span>
          <button
            onClick={handleReset}
            disabled={!connected || !!busyAgentId}
            title="Clear the chat and reset every agent"
            className="rounded-lg border border-neutral-800 bg-neutral-950 px-2.5 py-1 text-xs font-semibold text-neutral-300 transition hover:border-neutral-600 hover:text-neutral-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ↺ Reset session
          </button>
        </div>
      </header>

      <main className="flex min-h-0 flex-1 items-stretch gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <OfficeMap agents={agents} now={now} selectedId={selectedId} onSelect={setSelectedId} />
          <Legend />
        </div>
        <div className="flex w-[380px] shrink-0 flex-col gap-4">
          <SidePanel agent={selected} now={now} onClose={() => setSelectedId(null)} />
          <ChatPanel agents={agents} chat={chat} busyAgentId={busyAgentId} connected={connected} onSend={sendMessage} />
        </div>
      </main>
    </div>
  );
}
