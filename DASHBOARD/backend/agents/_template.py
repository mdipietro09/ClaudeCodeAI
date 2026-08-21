"""Template for a new agent — PLUG AND PLAY.

1. Copy this file to backend/agents/<something>.py (no leading underscore).
2. Fill in the fields below.
3. Restart the backend (python3 backend/server.py).
The dashboard picks it up automatically: avatar, desk, chat, everything.

Required: id, system. Everything else has sensible defaults.
"""

from _shared import TEAM_RULES, TOOL_RULES

AGENT = {
    "id": "ada",                     # unique, lowercase; used for @mentions
    "name": "Ada",                   # display name
    "role": "Engineering Agent",     # shown under the name
    "emoji": "🛠️",                   # avatar
    "color": "#fb923c",              # accent color (hex)
    "order": 4,                      # position in a full team round (lower = earlier)
    # "model": "qwen3:latest",       # optional: per-agent Ollama model
    # "tools": [],                   # optional: [] = no tools (e.g. a pure-synthesis role
                                      #   like manager.py); omit to give it every discovered tool
    "system": "You are Ada, the engineering agent."
              + TEAM_RULES + TOOL_RULES  # drop "+ TOOL_RULES" if this agent has no tools
              + "\nYour job: technical feasibility, build-vs-buy, architecture, timelines.",
}
