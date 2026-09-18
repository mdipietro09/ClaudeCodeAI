import { useCallback, useEffect, useRef, useState } from "react";

// Thin client for the Python backend (backend/server.py).
// Polls /api/state; the roster, chat, and statuses all come from the server,
// so agents are plug-and-play — edit backend/agents/*.py and restart it.
const POLL_MS = 1500;

export default function useTeam() {
  const [state, setState] = useState({ agents: [], chat: [], busy: null });
  const [connected, setConnected] = useState(true);
  const aliveRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/state");
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      if (aliveRef.current) {
        setState(data);
        setConnected(true);
      }
    } catch {
      if (aliveRef.current) setConnected(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(t);
    };
  }, [refresh]);

  const sendMessage = useCallback(
    async (text) => {
      if (!text.trim()) return;
      try {
        const res = await fetch("/api/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text.trim() }),
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        setConnected(false);
      }
      refresh(); // show the Boss's message immediately
    },
    [refresh]
  );

  const resetSession = useCallback(async () => {
    try {
      const res = await fetch("/api/reset", { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      setConnected(false);
    }
    refresh();
  }, [refresh]);

  return {
    agents: state.agents,
    chat: state.chat,
    busyAgentId: state.busy,
    connected,
    sendMessage,
    resetSession,
  };
}
