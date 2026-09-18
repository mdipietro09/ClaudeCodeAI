# 🏢 AI Agent Office

An interactive top-down office dashboard where real AI agents (local Ollama
LLMs) work as a team. Each agent's avatar physically walks between zones
(workstations, meeting room, break room, server rack) based on its live
status. Chat with the team, hand out a task, and watch them go.

> New to this project? `memory.txt` has the full architecture/history brief —
> read that first if you're picking this back up.

## Run

```bash
npm install
npm run backend   # terminal 1: Python agent server (stdlib only, no pip installs)
npm run dev       # terminal 2: frontend on http://localhost:5173
```

Requires `ollama serve` running with `qwen3.6`.

## Status → behavior

| Status | Behavior |
|---|---|
| 🟩 working | using tools → at its workstation desk; just chatting/reasoning → at the meeting-room table. Typing/gear animation, floating bubble with task name + timer. During an `@all` chained round the whole group gathers in the meeting room (and lingers 5 min after) |
| 🟨 waiting/blocked | freezes in place, bobbing ❓ bubble |
| 🟥 error/stuck | walks to the server room to debug, red pulse ring + 🚨 alert |
| 💤 idle | see below |

**Session start / after ↺ Reset:** the whole team opens with a 5-minute
kickoff huddle in the meeting room (nothing to do yet, just gathered). When
that ends they go straight to the break-room couch 💤 — no second 5-minute
wait tacked on. Any later idle period (after finishing a real task) gets its
own full 5-minute at-desk grace before heading to the break room, as usual.

Click any agent to open the side panel: current task, uptime %, task history.

**↺ Reset session** (top right) clears the chat and every agent's task
history/status — a fresh start with the same team. Disabled while the team is
mid-round; asks for confirmation first.

## The team — plug-and-play Python agents

Agents live in **`backend/agents/`** — one `.py` file each. Every file that
defines an `AGENT` dict becomes a team member; the dashboard discovers the
roster from the API, so nothing is hardcoded in the frontend:

- `financial.py` — **Finley 💰** (pricing, budgets, forecasts)
- `marketing.py` — **Mave 📣** (research, positioning, launch plans)
- `legal.py` — **Lex ⚖️** (compliance, IP, risk)
- `manager.py` — **Manager 🗂️** (no tools; speaks last in `@all` rounds, reads
  the chat, and gives the Boss one plain-English bottom line + a per-teammate
  bullet — use this when the specialists' three separate answers are too much
  to parse at a glance)

**To add an agent:** copy `backend/agents/_template.py` to a new file, fill in
the fields (`id`, `name`, `emoji`, `color`, `order`, optional per-agent
`model`, and the `system` prompt), restart the backend. Avatar, desk, chat and
@mention support appear automatically. Delete the file to remove the agent.
Files starting with `_` are ignored.

Use the **Team Chat** panel. Message routing:

- `@<id>` (e.g. `@lex`) — only that agent replies
- `@all` (or `@team`, `@everyone`) — full team round in `order`, each agent
  seeing the Boss's message plus teammates' earlier replies
- untagged — goes only to agents currently 🟨 waiting on your answer;
  if nobody is waiting you get a hint instead

While an agent generates, its avatar moves per the table above; a reply
ending with a question to you sets 🟨 waiting; a failed Ollama call sets 🟥
error. Teammate rosters are injected into every prompt by the server, so new
agents are automatically known to the rest of the team. The Boss is
addressed as "Boss" (not "CEO") throughout.

## Tools — plug-and-play too

Agents have native tool calling (Ollama tool API). Tools live in
**`backend/tools/`**, one `.py` file each, auto-discovered on startup:

- `web_search` — DuckDuckGo search, no API key
- `fetch_url` — download a page and return its readable text
- `calculate` — safe arithmetic (pricing, forecasts)
- `save_note` / `read_notes` — shared team notepad, persists to
  `backend/workspace/notes.md` (you can open it yourself)

Every tool call appears in the chat feed as a small 🔧 line. **To add a tool:**
copy any file in `backend/tools/`, define a `TOOL` spec (JSON-schema
parameters) and a `run(args)` function, restart the backend. All agents get
all tools by default; limit an agent with `"tools": ["calculate", ...]` in its
`AGENT` dict.

## Architecture

- `backend/server.py` — Python stdlib HTTP server (port 8000): loads agents,
  orchestrates rounds, calls Ollama (`/api/chat`, `think: false`), exposes
  `GET /api/state`, `POST /api/message`, `POST /api/reset`
- `backend/agents/*.py` — plug-and-play agent definitions (`_shared.py` holds common rules)
- `backend/tools/*.py` — plug-and-play tool definitions
- `backend/workspace/notes.md` — agents' shared persistent notepad
- `src/hooks/useTeam.js` — thin client: polls `/api/state` every 1.5s, posts messages/reset
- `vite.config.js` — dev proxy `/api` → `http://localhost:8000`
- `src/office/layout.js` — 30×18 cell grid (32px cells), zone/furniture rects, blocked-cell map
- `src/office/pathfinding.js` — A* over the grid; returns pixel waypoints (collinear cells collapsed)
- `src/components/AgentAvatar.jsx` — Framer Motion `useMotionValue` + keyframe `animate()` walks the
  waypoint path at constant speed; interruptible mid-walk (re-paths from current position); also
  holds the movement-precedence rules from the table above
