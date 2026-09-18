import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, animate, AnimatePresence } from "framer-motion";
import { findPath } from "../office/pathfinding.js";
import {
  posToCell, cellCenter, DESKS, deskSeat, IDLE_SPOTS, MEETING_SPOTS, ERROR_SPOTS,
} from "../office/layout.js";
import { STATUS } from "../data/team.js";

const WALK_SPEED = 110; // px per second
const IDLE_TO_BREAK_MS = 5 * 60 * 1000; // stay at the desk this long before heading to the break room

export const STATUS_COLOR = {
  [STATUS.WORKING]: "#22c55e",
  [STATUS.WAITING]: "#eab308",
  [STATUS.ERROR]: "#ef4444",
  [STATUS.IDLE]: "#818cf8",
};

function fmtElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export default function AgentAvatar({ agent, idleIndex, now, selected, onSelect }) {
  const seat = deskSeat(DESKS[agent.desk]);
  const home = cellCenter(seat.c, seat.r);
  const x = useMotionValue(home.x);
  const y = useMotionValue(home.y);
  const [walking, setWalking] = useState(false);
  const animsRef = useRef([]);

  // Where should this agent be standing? Precedence:
  // error: server room to debug.
  // working + usingTool: its workstation desk.
  // working without tools (just chatting): the meeting table.
  // part of a chained round / post-@all linger: the meeting table.
  // idle: at the desk, break room after IDLE_TO_BREAK_MS of inactivity.
  // waiting outside a meeting: freeze in place (null target).
  const lingering = now < (agent.meetingUntil ?? 0);
  const onBreak =
    agent.status === STATUS.IDLE && !agent.inMeeting && !lingering &&
    now - agent.statusSince >= IDLE_TO_BREAK_MS;
  const meetingSpot = MEETING_SPOTS[idleIndex % MEETING_SPOTS.length];
  let targetCell = null;
  if (agent.status === STATUS.ERROR) targetCell = ERROR_SPOTS[idleIndex % ERROR_SPOTS.length];
  else if (agent.status === STATUS.WORKING) targetCell = agent.usingTool ? seat : meetingSpot;
  else if (agent.inMeeting || lingering) targetCell = meetingSpot;
  else if (agent.status === STATUS.IDLE)
    targetCell = onBreak ? IDLE_SPOTS[idleIndex % IDLE_SPOTS.length] : seat;

  const targetKey = targetCell ? `${targetCell.c},${targetCell.r}` : "stay";

  useEffect(() => {
    if (!targetCell) {
      // waiting/error freezes the agent where it stands, mid-path included
      animsRef.current.forEach((a) => a.stop());
      setWalking(false);
      return;
    }
    const from = posToCell(x.get(), y.get());
    const path = findPath(from, targetCell);
    const xs = [x.get(), ...path.map((p) => p.x)];
    const ys = [y.get(), ...path.map((p) => p.y)];

    // cumulative distance -> shared keyframe times so speed stays constant
    const dists = [0];
    for (let i = 1; i < xs.length; i++)
      dists.push(dists[i - 1] + Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]));
    const total = dists[dists.length - 1];
    if (total < 2) return;
    const times = dists.map((d) => d / total);
    const duration = Math.max(0.35, total / WALK_SPEED);

    animsRef.current.forEach((a) => a.stop());
    setWalking(true);
    const ax = animate(x, xs, { duration, times, ease: "linear" });
    const ay = animate(y, ys, { duration, times, ease: "linear" });
    animsRef.current = [ax, ay];
    Promise.all([ax, ay]).then(() => setWalking(false));
    return () => animsRef.current.forEach((a) => a.stop());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  const color = STATUS_COLOR[agent.status];
  const isError = agent.status === STATUS.ERROR;
  const showTyping = agent.status === STATUS.WORKING && !walking;

  return (
    <motion.div
      className="absolute z-20 cursor-pointer select-none"
      style={{ x, y, translateX: "-50%", translateY: "-50%" }}
      onClick={() => onSelect(agent.id)}
    >
      {/* error pulse ring */}
      {isError && (
        <motion.span
          className="absolute -inset-3 rounded-full"
          style={{ background: "rgba(239,68,68,0.35)" }}
          animate={{ scale: [1, 1.7], opacity: [0.7, 0] }}
          transition={{ duration: 1, repeat: Infinity, ease: "easeOut" }}
        />
      )}

      {/* body */}
      <motion.div
        className="relative flex h-9 w-9 items-center justify-center rounded-full text-lg shadow-lg"
        style={{
          background: "#171717",
          border: `2.5px solid ${color}`,
          boxShadow: selected ? `0 0 0 3px ${agent.color}66, 0 4px 10px rgba(0,0,0,.5)` : "0 4px 10px rgba(0,0,0,.5)",
        }}
        animate={
          walking
            ? { y: [0, -3, 0], rotate: [-4, 4, -4] }
            : showTyping
              ? { y: [0, -1, 0] }
              : { y: 0, rotate: 0 }
        }
        transition={walking ? { duration: 0.35, repeat: Infinity } : showTyping ? { duration: 0.5, repeat: Infinity } : { duration: 0.2 }}
      >
        <span>{agent.emoji}</span>
        {/* status dot */}
        <span
          className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-black"
          style={{ background: color }}
        />
        {/* typing gear */}
        {showTyping && (
          <motion.span
            className="absolute -right-3 -top-2 text-[11px]"
            animate={{ rotate: 360 }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          >
            ⚙️
          </motion.span>
        )}
      </motion.div>

      {/* name tag */}
      <div className="absolute left-1/2 top-full mt-0.5 -translate-x-1/2 whitespace-nowrap rounded px-1 text-[9px] font-semibold text-neutral-300"
        style={{ background: "rgba(2,6,23,0.7)" }}>
        {agent.name}
      </div>

      {/* status bubble */}
      <AnimatePresence>
        {agent.status === STATUS.WORKING && !walking && (
          <motion.div
            key="work"
            initial={{ opacity: 0, y: 4, scale: 0.8 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            className="absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-lg border border-emerald-500/40 bg-neutral-950/95 px-2 py-0.5 text-[10px] shadow-xl"
          >
            <span className="text-neutral-200">{agent.task}</span>
            <span className="ml-1.5 font-mono text-emerald-400">{fmtElapsed(now - agent.statusSince)}</span>
            <span className="absolute left-1/2 top-full -ml-1 border-4 border-transparent border-t-neutral-950/95" />
          </motion.div>
        )}
        {agent.status === STATUS.WAITING && (
          <motion.div
            key="wait"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1, y: [0, -3, 0] }}
            exit={{ opacity: 0, scale: 0.5 }}
            transition={{ y: { duration: 1.2, repeat: Infinity } }}
            className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 rounded-full border border-yellow-500/50 bg-neutral-950/95 px-1.5 py-0.5 text-xs shadow-xl"
          >
            ❓
          </motion.div>
        )}
        {isError && (
          <motion.div
            key="err"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: [1, 1.15, 1] }}
            exit={{ opacity: 0, scale: 0.5 }}
            transition={{ scale: { duration: 0.7, repeat: Infinity } }}
            className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 rounded-full border border-red-500/60 bg-red-950/95 px-1.5 py-0.5 text-xs shadow-xl"
          >
            🚨
          </motion.div>
        )}
        {onBreak && !walking && (
          <motion.div
            key="zzz"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.4, 1, 0.4], y: [0, -6, -10] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 2, repeat: Infinity }}
            className="absolute bottom-full left-1/2 mb-0.5 -translate-x-1/2 text-sm"
          >
            💤
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
