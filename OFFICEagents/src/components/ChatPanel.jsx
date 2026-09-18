import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

const FALLBACK = { name: "Agent", role: "", emoji: "🤖", color: "#a3a3a3" };

function AgentTag({ agent }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full text-[11px]"
        style={{ background: "#171717", border: `1.5px solid ${agent.color}` }}
      >
        {agent.emoji}
      </span>
      <span className="text-xs font-semibold" style={{ color: agent.color }}>
        {agent.name}
      </span>
      <span className="text-[10px] text-neutral-500">{agent.role}</span>
    </span>
  );
}

export default function ChatPanel({ agents, chat, busyAgentId, connected, onSend }) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);
  const byId = (id) => agents.find((a) => a.id === id) ?? { ...FALLBACK, name: id };
  const busyAgent = busyAgentId ? byId(busyAgentId) : null;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.length, busyAgentId]);

  const submit = (e) => {
    e.preventDefault();
    if (!draft.trim() || busyAgentId) return;
    onSend(draft);
    setDraft("");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-neutral-800 bg-neutral-950 shadow-2xl">
      <div className="flex items-center justify-between gap-2 border-b border-neutral-800 px-4 py-2.5">
        <h2 className="text-sm font-bold text-neutral-100">💬 Team Chat</h2>
        <span className="truncate text-[10px] text-neutral-500">
          {agents.map((a) => `@${a.id}`).join(" · ")} · @all for everyone
        </span>
      </div>

      {!connected && (
        <div className="border-b border-red-900/50 bg-red-950/40 px-4 py-1.5 text-xs text-red-300">
          Backend offline — start it with <code className="font-mono">python3 backend/server.py</code>
        </div>
      )}

      <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {chat.length === 0 && connected && (
          <div className="m-auto max-w-[85%] text-center text-xs leading-5 text-neutral-500">
            Give your team a task, e.g.
            <button
              className="mt-2 block w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-neutral-300 transition hover:border-neutral-600"
              onClick={() => onSend("@all Research and plan the launch of a new product: an AI-powered meal-planning app for busy professionals. Work as a team.")}
            >
              "@all Research and launch a new product: an AI meal-planning app" →
            </button>
          </div>
        )}

        {chat.map((m) => {
          if (m.from === "ceo")
            return (
              <div key={m.id} className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-neutral-100 px-3.5 py-2 text-sm text-neutral-900 shadow">
                {m.text}
              </div>
            );
          if (m.from === "tool") {
            const agent = byId(m.agent);
            return (
              <div key={m.id} className="mr-auto flex items-center gap-1.5 pl-1 font-mono text-[10px] text-neutral-500">
                <span>🔧</span>
                <span style={{ color: agent.color }}>{agent.name}</span>
                <span className="truncate">{m.text}</span>
              </div>
            );
          }
          if (m.from === "system")
            return (
              <div key={m.id} className="mx-auto rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-1.5 text-xs text-red-300">
                {m.text}
              </div>
            );
          const agent = byId(m.from);
          return (
            <div key={m.id} className="mr-auto max-w-[90%]">
              <AgentTag agent={agent} />
              <div
                className="mt-1 whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-neutral-800 bg-neutral-900 px-3.5 py-2 text-[13px] leading-relaxed text-neutral-200 shadow"
                style={{ borderLeftColor: agent.color, borderLeftWidth: 2 }}
              >
                {m.text}
              </div>
            </div>
          );
        })}

        {busyAgent && (
          <div className="mr-auto">
            <AgentTag agent={busyAgent} />
            <div className="mt-1 flex w-16 items-center justify-center gap-1 rounded-2xl rounded-tl-sm border border-neutral-800 bg-neutral-900 px-3 py-2.5">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="h-1.5 w-1.5 rounded-full bg-neutral-400"
                  animate={{ opacity: [0.2, 1, 0.2] }}
                  transition={{ duration: 1, repeat: Infinity, delay: i * 0.25 }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-neutral-800 p-3">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={busyAgentId ? "Team is thinking…" : "@name or @all — untagged replies go to whoever asked you"}
          disabled={!!busyAgentId || !connected}
          className="min-w-0 flex-1 rounded-xl border border-neutral-800 bg-neutral-900 px-3.5 py-2 text-sm text-neutral-100 placeholder-neutral-600 outline-none transition focus:border-neutral-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!!busyAgentId || !connected || !draft.trim()}
          className="rounded-xl bg-neutral-100 px-4 py-2 text-sm font-semibold text-neutral-900 transition hover:bg-white disabled:opacity-30"
        >
          Send
        </button>
      </form>
    </div>
  );
}
