import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  STAGE_W, STAGE_H, CELL, ZONES, DESKS, deskRect, MEETING_TABLE, COUCH, RACK,
} from "../office/layout.js";
import AgentAvatar from "./AgentAvatar.jsx";

function Zone({ z }) {
  return (
    <div
      className="absolute rounded-xl border border-neutral-800"
      style={{ left: z.x, top: z.y, width: z.w, height: z.h, background: z.floor }}
    >
      <span className="absolute left-2 top-1 text-[10px] font-semibold uppercase tracking-wider text-neutral-500">
        {z.label}
      </span>
    </div>
  );
}

function Desk({ d }) {
  const r = deskRect(d);
  return (
    <div
      className="absolute flex items-center justify-center rounded-md border border-neutral-700 bg-neutral-800 shadow-md"
      style={{ left: r.x, top: r.y, width: r.w, height: r.h }}
    >
      <span className="text-sm">🖥️</span>
    </div>
  );
}

function RackLights() {
  return (
    <div className="grid grid-cols-2 gap-1.5 p-2">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: i % 3 === 0 ? "#22c55e" : "#38bdf8" }}
          animate={{ opacity: [1, 0.15, 1] }}
          transition={{ duration: 0.9 + (i % 4) * 0.4, repeat: Infinity, delay: i * 0.2 }}
        />
      ))}
    </div>
  );
}

export default function OfficeMap({ agents, now, selectedId, onSelect }) {
  const wrapRef = useRef(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(el.clientWidth / STAGE_W));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className="w-full" style={{ height: STAGE_H * scale }}>
      <div
        className="relative overflow-hidden rounded-2xl border border-neutral-800 bg-[#050506] shadow-2xl"
        style={{ width: STAGE_W, height: STAGE_H, transform: `scale(${scale})`, transformOrigin: "top left" }}
      >
        {/* floor grid */}
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(rgba(148,163,184,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.06) 1px, transparent 1px)",
            backgroundSize: `${CELL}px ${CELL}px`,
          }}
        />

        {Object.values(ZONES).map((z) => (
          <Zone key={z.label} z={z} />
        ))}

        {/* desks */}
        {DESKS.map((d, i) => (
          <Desk key={i} d={d} />
        ))}

        {/* meeting table */}
        <div
          className="absolute flex items-center justify-center rounded-xl border border-neutral-700 bg-neutral-800 shadow-md"
          style={{ left: MEETING_TABLE.c * CELL, top: MEETING_TABLE.r * CELL, width: MEETING_TABLE.w * CELL, height: MEETING_TABLE.h * CELL }}
        >
          <span className="text-lg">📊</span>
        </div>

        {/* couch */}
        <div
          className="absolute flex items-center justify-center rounded-lg border border-indigo-800 bg-indigo-900/80 shadow-md"
          style={{ left: COUCH.c * CELL, top: COUCH.r * CELL, width: COUCH.w * CELL, height: COUCH.h * CELL }}
        >
          <span className="text-sm">🛋️ 🛋️</span>
        </div>
        {/* coffee machine */}
        <div className="absolute text-base" style={{ left: 27.1 * CELL, top: 12.2 * CELL }}>☕</div>

        {/* server rack */}
        <div
          className="absolute rounded-md border border-neutral-700 bg-neutral-900 shadow-md"
          style={{ left: RACK.c * CELL, top: RACK.r * CELL, width: RACK.w * CELL, height: RACK.h * CELL }}
        >
          <RackLights />
        </div>

        {/* plants */}
        <div className="absolute text-lg" style={{ left: 17.6 * CELL, top: 1.4 * CELL }}>🪴</div>
        <div className="absolute text-lg" style={{ left: 1.4 * CELL, top: 9.6 * CELL }}>🪴</div>
        <div className="absolute text-lg" style={{ left: 27.6 * CELL, top: 9.6 * CELL }}>🪴</div>

        {/* agents */}
        {agents.map((a) => (
          <AgentAvatar
            key={a.id}
            agent={a}
            idleIndex={a.desk}
            now={now}
            selected={a.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}
