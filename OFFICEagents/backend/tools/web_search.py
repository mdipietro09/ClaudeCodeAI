"""Web search. Primary: DuckDuckGo's lite HTML endpoint (no API key). DDG's
anti-bot system intermittently serves a CAPTCHA/"anomaly" page instead of
real results for automated traffic — this used to be silently mistaken for
"no results found". Now it's detected explicitly, retried once, and falls
back to Wikipedia's official search API (a real API, never bot-blocked) so
the agent gets *something* instead of a false "nothing found"."""

import json
import re
import time
import urllib.parse
import urllib.request

TOOL = {
    "name": "web_search",
    "description": "Search the web. Returns the top results (title, url, snippet). "
                   "Use for market research, competitor checks, regulations, current facts.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search query"},
        },
        "required": ["query"],
    },
}

_TAG = re.compile(r"<[^>]+>")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _ddg_lite(query):
    """Returns a result string, or None if DDG blocked us / had nothing."""
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        html = res.read().decode("utf-8", "ignore")

    if "anomaly.js" in html or "id=\"challenge-form\"" in html:
        return None  # bot-challenge page, not a real "no results"

    links = re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>', html)
    if not links:
        return None  # unexpected markup / blocked in some other way — treat as unusable
    snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html, re.S)
    out = []
    for i, (href, title) in enumerate(links[:5]):
        m = re.search(r"uddg=([^&]+)", href)
        real = urllib.parse.unquote(m.group(1)) if m else href
        snip = _TAG.sub("", snippets[i]).strip() if i < len(snippets) else ""
        out.append("%d. %s\n   %s\n   %s" % (i + 1, _TAG.sub("", title).strip(), real, snip))
    return "\n".join(out) if out else None


def _wikipedia_fallback(query):
    """Real API, never bot-blocked. Narrower than general web search, but
    always honest about what it found (or didn't)."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query,
        "format": "json", "srlimit": 5,
    })
    req = urllib.request.Request(url, headers={"User-Agent": "AgentOffice/1.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode())
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None
    out = ["(DuckDuckGo was unavailable, falling back to Wikipedia:)"]
    for i, h in enumerate(hits):
        snippet = _TAG.sub("", h.get("snippet", ""))
        title = h.get("title", "")
        out.append("%d. %s\n   https://en.wikipedia.org/wiki/%s\n   %s" %
                   (i + 1, title, urllib.parse.quote(title.replace(" ", "_")), snippet))
    return "\n".join(out)


def run(args):
    query = str(args.get("query", "")).strip()
    if not query:
        return "Error: empty query"

    for attempt in range(2):
        try:
            result = _ddg_lite(query)
            if result:
                return result
        except Exception:
            pass
        if attempt == 0:
            time.sleep(1.5)  # brief backoff, DDG's block is often momentary

    try:
        result = _wikipedia_fallback(query)
        if result:
            return result
    except Exception:
        pass

    return ("Search unavailable right now: DuckDuckGo blocked automated requests "
            "and no Wikipedia fallback matched. Try rephrasing the query, or ask "
            "the Boss for the information directly.")
