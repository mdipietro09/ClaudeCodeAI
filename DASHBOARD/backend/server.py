#!/usr/bin/env python3
"""AI Agent Office backend — pure stdlib, no pip installs.

Agents are plug-and-play: every .py file in backend/agents/ that defines an
AGENT dict becomes a team member. Add/edit/remove files and restart the
server; the dashboard adapts automatically.

Run:  python3 backend/server.py          (serves http://localhost:8000)
Env:  OLLAMA_URL (default http://localhost:11434), PORT (default 8000)
"""

import importlib.util
import json
import os
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
PORT = int(os.environ.get("PORT", "8000"))
DEFAULT_MODEL = os.environ.get("MODEL", "qwen3:latest")
AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")

now_ms = lambda: int(time.time() * 1000)
BREAK_GRACE_MS = 5 * 60 * 1000  # idle-at-desk grace before walking to the break room
BOOT_MEETING_MS = 5 * 60 * 1000  # kickoff huddle in the meeting room at session start


# ---------------------------------------------------------------- agents ----
def load_agents():
    """Import every backend/agents/*.py (not starting with _) exposing AGENT."""
    if AGENTS_DIR not in sys.path:
        sys.path.insert(0, AGENTS_DIR)  # lets agent files do `from _shared import ...`
    agents = []
    for fname in sorted(os.listdir(AGENTS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(AGENTS_DIR, fname)
        spec = importlib.util.spec_from_file_location(fname[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print("!! skipping %s: %s" % (fname, e))
            continue
        a = getattr(mod, "AGENT", None)
        if not isinstance(a, dict) or "id" not in a or "system" not in a:
            print("!! skipping %s: no valid AGENT dict" % fname)
            continue
        agents.append(a)
    agents.sort(key=lambda a: (a.get("order", 99), a.get("name", "")))
    # runtime state lives alongside the definition
    for i, a in enumerate(agents):
        a.setdefault("name", a["id"].title())
        a.setdefault("role", "Agent")
        a.setdefault("emoji", "🤖")
        a.setdefault("color", "#a3a3a3")
        a.setdefault("model", DEFAULT_MODEL)
        a["desk"] = i % 6
        a["history"] = []
        a["inMeeting"] = False  # true while part of a chained (multi-agent) round
        a["usingTool"] = False  # true while executing tools (drives desk vs meeting room)
        reset_to_boot_state(a)
    return agents


def reset_to_boot_state(a):
    """Fresh session start (server boot, or POST /api/reset): agents gather in
    the meeting room for BOOT_MEETING_MS, then go straight to the break room
    (no second idle grace period tacked on afterwards)."""
    now = now_ms()
    a["status"] = "idle"
    a["task"] = None
    a["meetingUntil"] = now + BOOT_MEETING_MS
    a["statusSince"] = now - BREAK_GRACE_MS  # break-room grace already "used up" by the huddle


def load_tools():
    """Import every backend/tools/*.py (not starting with _). A file exposes
    either TOOL + run(args), or TOOLS (a list) + run_<name>(args) per tool."""
    tools = {}
    if not os.path.isdir(TOOLS_DIR):
        return tools
    if TOOLS_DIR not in sys.path:
        sys.path.insert(0, TOOLS_DIR)
    for fname in sorted(os.listdir(TOOLS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(TOOLS_DIR, fname)
        spec = importlib.util.spec_from_file_location("tool_" + fname[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print("!! skipping tool %s: %s" % (fname, e))
            continue
        specs = getattr(mod, "TOOLS", None) or ([mod.TOOL] if hasattr(mod, "TOOL") else [])
        for t in specs:
            fn = getattr(mod, "run_" + t["name"], None) or getattr(mod, "run", None)
            if not callable(fn):
                print("!! tool %s in %s has no run function" % (t["name"], fname))
                continue
            tools[t["name"]] = {"spec": {"type": "function", "function": t}, "run": fn}
    return tools


STATE = {"agents": load_agents(), "chat": [], "busy": None}
TOOLS = load_tools()
LOCK = threading.Lock()
MSG_ID = [0]


def push_chat(sender, text, agent=None):
    with LOCK:
        MSG_ID[0] += 1
        m = {"id": MSG_ID[0], "from": sender, "text": text, "ts": now_ms()}
        if agent:
            m["agent"] = agent
        STATE["chat"].append(m)
        STATE["chat"] = STATE["chat"][-200:]


def public_agent(a):
    return {k: a[k] for k in
            ("id", "name", "role", "emoji", "color", "desk", "status", "task",
             "statusSince", "history", "inMeeting", "meetingUntil", "usingTool")}


# ---------------------------------------------------------------- ollama ----
def ollama_chat(model, messages, tools=None):
    """One Ollama call; returns the raw assistant message dict."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.7, "num_predict": 450},
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as res:
        data = json.loads(res.read().decode())
    return data.get("message") or {}


def strip_think(text):
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()


def agent_tools(agent):
    """All discovered tools, unless the AGENT dict lists a 'tools' subset."""
    allowed = agent.get("tools")
    names = allowed if allowed is not None else list(TOOLS.keys())
    return [TOOLS[n]["spec"] for n in names if n in TOOLS]


def fmt_args(args):
    return ", ".join("%s=%s" % (k, json.dumps(v)[:60]) for k, v in (args or {}).items())


def run_agent_turn(agent, msgs):
    """Tool-use loop: keep calling Ollama until the agent answers in prose."""
    tools = agent_tools(agent)
    for _ in range(6):
        message = ollama_chat(agent["model"], msgs, tools)
        calls = message.get("tool_calls") or []
        if not calls:
            with LOCK:
                agent["usingTool"] = False
            return strip_think(message.get("content", ""))
        with LOCK:
            agent["usingTool"] = True  # frontend sends it to its workstation
        msgs.append(message)
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "?")
            args = fn.get("arguments") or {}
            push_chat("tool", "%s(%s)" % (name, fmt_args(args)), agent=agent["id"])
            tool = TOOLS.get(name)
            try:
                result = tool["run"](args) if tool else "Error: unknown tool %r" % name
            except Exception as e:
                result = "Error running %s: %s" % (name, e)
            msgs.append({"role": "tool", "tool_name": name, "content": str(result)[:4000]})

    # Hit the tool-call cap: force one last call with tools disabled, so the
    # model MUST answer in prose using whatever it already gathered, instead
    # of trying (and failing) to call another tool.
    msgs.append({"role": "user", "content":
                 "You're out of tool calls for this turn. Answer the Boss now, in plain "
                 "prose, using only what you've already found. Say plainly if it's incomplete."})
    message = ollama_chat(agent["model"], msgs, tools=None)
    with LOCK:
        agent["usingTool"] = False
    final = strip_think(message.get("content", ""))
    return final or "I ran out of tool calls and don't have enough to go on yet for this one."


def build_messages(agent, chat_log, roster):
    """Shared transcript: own turns = assistant, everyone else labeled user turns."""
    names = {a["id"]: a["name"] for a in roster}
    teammates = "\n".join(
        "- %s — %s" % (a["name"], a["role"]) for a in roster if a["id"] != agent["id"])
    system = agent["system"]
    if teammates:
        system += "\n\nYour current teammates:\n" + teammates
    system += "\nToday's date: " + time.strftime("%Y-%m-%d")
    msgs = [{"role": "system", "content": system}]
    for m in chat_log:
        if m["from"] in ("system", "tool"):
            continue
        if m["from"] == agent["id"]:
            msgs.append({"role": "assistant", "content": m["text"]})
        else:
            label = "Boss" if m["from"] == "ceo" else names.get(m["from"], m["from"])
            msgs.append({"role": "user", "content": "%s: %s" % (label, m["text"])})
    return msgs


# ----------------------------------------------------------- orchestrator ----
def run_round(text):
    agents = STATE["agents"]
    m = re.match(r"^@(\w+)", text)
    if m:
        tag = m.group(1).lower()
        if tag in ("all", "team", "everyone"):
            responders = agents
        else:
            responders = [a for a in agents if a["id"].lower() == tag
                          or a["name"].lower() == tag]
            if not responders:
                push_chat("system", "No agent named @%s. Team: %s — or @all for everyone."
                          % (tag, ", ".join("@" + a["id"] for a in agents)))
                with LOCK:
                    STATE["busy"] = None
                return
    else:
        # untagged: goes to whoever is waiting on your answer; nobody else butts in
        responders = [a for a in agents if a["status"] == "waiting"]
        if not responders:
            push_chat("system", "Tag an agent (%s) or @all for a full team round."
                      % ", ".join("@" + a["id"] for a in agents))
            with LOCK:
                STATE["busy"] = None
            return

    task = re.sub(r"^@\w+\s*", "", text)[:38]
    if len(text) > 38:
        task += "…"

    # chained round: each agent's output feeds the next -> they meet up
    chained = len(responders) > 1
    if chained:
        with LOCK:
            for a in responders:
                a["inMeeting"] = True

    for agent in responders:
        started = now_ms()
        with LOCK:
            STATE["busy"] = agent["id"]
            # a fresh task cancels any post-meeting linger (they leave to work)
            agent.update(status="working", task=task, statusSince=started, usingTool=False,
                         meetingUntil=0 if not chained else agent["meetingUntil"])
        try:
            with LOCK:
                msgs = build_messages(agent, list(STATE["chat"]), agents)
            reply = run_agent_turn(agent, msgs)
            push_chat(agent["id"], reply)
            asked = reply.rstrip().endswith("?")
            with LOCK:
                agent["history"] = (agent["history"] + [
                    {"task": task, "status": "completed", "startedAt": started,
                     "durationMs": now_ms() - started}])[-12:]
                agent.update(status="waiting" if asked else "idle",
                             task=task if asked else None, statusSince=now_ms())
        except Exception as e:
            push_chat("system", "⚠️ %s hit an error: %s" % (agent["name"], e))
            with LOCK:
                agent["history"] = (agent["history"] + [
                    {"task": task, "status": "failed", "startedAt": started,
                     "durationMs": now_ms() - started}])[-12:]
                agent.update(status="error", statusSince=now_ms(), usingTool=False)
    with LOCK:
        STATE["busy"] = None
        if chained:
            for a in responders:  # round over: linger at the table 5 more minutes
                a["inMeeting"] = False
                a["meetingUntil"] = now_ms() + 5 * 60 * 1000


# ------------------------------------------------------------------ http ----
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path == "/api/state":
            with LOCK:
                self._send(200, {
                    "agents": [public_agent(a) for a in STATE["agents"]],
                    "chat": list(STATE["chat"]),
                    "busy": STATE["busy"],
                })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/reset":
            with LOCK:
                if STATE["busy"]:
                    return self._send(409, {"error": "team is busy"})
                STATE["chat"] = []
                for a in STATE["agents"]:
                    a.update(history=[], inMeeting=False, usingTool=False)
                    reset_to_boot_state(a)
            return self._send(200, {"ok": True})
        if self.path != "/api/message":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            text = json.loads(self.rfile.read(length).decode()).get("text", "").strip()
        except Exception:
            return self._send(400, {"error": "bad json"})
        if not text:
            return self._send(400, {"error": "empty message"})
        with LOCK:
            if STATE["busy"]:
                return self._send(409, {"error": "team is busy"})
        push_chat("ceo", text)
        threading.Thread(target=run_round, args=(text,), daemon=True).start()
        self._send(200, {"ok": True})

    def log_message(self, fmt, *args):  # quiet
        pass


if __name__ == "__main__":
    roster = ", ".join("%s %s (%s)" % (a["emoji"], a["name"], a["role"]) for a in STATE["agents"])
    print("AI Agent Office backend on http://localhost:%d" % PORT)
    print("Team: %s" % (roster or "NO AGENTS FOUND in backend/agents/"))
    print("Ollama: %s (default model %s)" % (OLLAMA_URL, DEFAULT_MODEL))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
