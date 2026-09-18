import { motion, AnimatePresence } from "framer-motion";
import { STATUS, uptimePct } from "../data/team.js";
import { STATUS_COLOR } from "./AgentAvatar.jsx";

const STATUS_LABEL = {
  [STATUS.WORKING]: "Working",
  [STATUS.WAITING]: "Waiting for your answer",
  [STATUS.ERROR]: "Error / stuck",
  [STATUS.IDLE]: "Idle",
};

function fmtDur(ms) {
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function SidePanel({ agent, now, onClose }) {
  return (
    <AnimatePresence>
      {agent && (
        <motion.aside
          key={agent.id}
          initial={{ y: -12, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -12, opacity: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          className="flex shrink-0 flex-col gap-3 rounded-2xl border border-neutral-800 bg-neutral-950 p-4 shadow-2xl"
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div
                className="flex h-11 w-11 items-center justify-center rounded-full text-xl"
                style={{ background: "#171717", border: `2.5px solid ${STATUS_COLOR[agent.status]}` }}
              >
                {agent.emoji}
              </div>
              <div>
                <h2 className="text-base font-bold text-neutral-100">
                  {agent.name} <span className="text-xs font-normal text-neutral-500">{agent.role}</span>
                </h2>
                <span className="text-xs font-medium" style={{ color: STATUS_COLOR[agent.status] }}>
                  ● {STATUS_LABEL[agent.status]}
                </span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="rounded-md px-2 py-0.5 text-neutral-500 transition hover:bg-neutral-800 hover:text-neutral-100"
            >
              ✕
            </button>
          </div>

          {agent.task && (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">Current task</div>
              <div className="text-neutral-200">{agent.task}</div>
              <div className="mt-0.5 font-mono text-xs text-neutral-500">
                {fmtDur(now - agent.statusSince)} in this state
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[10px] uppercase tracking-wider text-neutral-500">
                Task success rate
              </span>
              <span className="font-mono text-sm font-semibold text-neutral-200">
                {uptimePct(agent).toFixed(0)}%
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-neutral-800">
              <motion.div
                className="h-full rounded-full"
                style={{ background: uptimePct(agent) > 90 ? "#22c55e" : uptimePct(agent) > 60 ? "#eab308" : "#ef4444" }}
                initial={{ width: 0 }}
                animate={{ width: `${uptimePct(agent)}%` }}
                transition={{ duration: 0.6 }}
              />
            </div>
          </div>

          <div>
            <div className="mb-2 text-[10px] uppercase tracking-wider text-neutral-500">Task history</div>
            <ul className="flex max-h-40 flex-col gap-1.5 overflow-y-auto pr-1">
              {[...agent.history].reverse().map((h, i) => (
                <li
                  key={i}
                  className="flex items-center gap-2 rounded-md border border-neutral-800 bg-neutral-900/70 px-2.5 py-1.5 text-xs"
                >
                  <span>{h.status === "failed" ? "🟥" : "🟩"}</span>
                  <span className="flex-1 truncate text-neutral-300">{h.task}</span>
                  <span className="shrink-0 font-mono text-[10px] text-neutral-500">
                    {fmtTime(h.startedAt)} · {fmtDur(h.durationMs)}
                  </span>
                </li>
              ))}
              {agent.history.length === 0 && (
                <li className="text-xs text-neutral-600">No tasks completed yet.</li>
              )}
            </ul>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
