"""Fetch a web page and return its readable text."""

import re
import urllib.request

TOOL = {
    "name": "fetch_url",
    "description": "Download a web page and return its text content (first ~3000 chars). "
                   "Use after web_search to read a promising result.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "full http(s) URL"},
        },
        "required": ["url"],
    },
}


def run(args):
    url = str(args.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return "Error: url must start with http:// or https://"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AgentOffice)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            html = res.read(500_000).decode("utf-8", "ignore")
    except Exception as e:
        return "Error fetching %s: %s" % (url, e)
    html = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:3000] if text else "Fetched page had no readable text."
