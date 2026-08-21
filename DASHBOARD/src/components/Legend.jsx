const ITEMS = [
  { icon: "🟩", color: "#22c55e", label: "Working", hint: "desk when using tools · meeting room when chatting" },
  { icon: "🟨", color: "#eab308", label: "Waiting / blocked", hint: "standing still ❓" },
  { icon: "🟥", color: "#ef4444", label: "Error / stuck", hint: "debugging at the server rack 🚨" },
  { icon: "💤", color: "#818cf8", label: "Idle / sleeping", hint: "couch after 5 min idle" },
];

export default function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-neutral-800 bg-neutral-950 px-4 py-2.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-neutral-500">Legend</span>
      {ITEMS.map((it) => (
        <div key={it.label} className="flex items-center gap-2 text-xs">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: it.color }} />
          <span className="font-medium text-neutral-200">{it.icon} {it.label}</span>
          <span className="hidden text-neutral-500 sm:inline">— {it.hint}</span>
        </div>
      ))}
    </div>
  );
}
