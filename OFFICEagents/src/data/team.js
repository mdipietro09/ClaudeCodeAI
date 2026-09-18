// The agent roster lives in the Python backend (backend/agents/*.py) and is
// served by /api/state — nothing about specific agents is hardcoded here.

export const STATUS = {
  WORKING: "working",
  WAITING: "waiting",
  ERROR: "error",
  IDLE: "idle",
};

export function uptimePct(agent) {
  const total = agent.history.length;
  if (total === 0) return 100;
  const failed = agent.history.filter((h) => h.status === "failed").length;
  return 100 * (1 - failed / total);
}
