"""
IT000553414 — Weekly candlestick chart with filtered, full-width Support/Resistance
levels + a full price-level (100, 101, 102...) reference grid on the y-axis.

run.py is the WHOLE PIPELINE — the only command needed:

    python3 run.py
        AI maintenance (Ollama) -> PLOT.html -> FORECAST.html

    python3 run.py "the forecast is really bad so do it again"
        Same, but the quoted instructions are passed to the local model
        (they force a fresh forecast vintage and steer all the rewrites).

Everything lives in this one file: S/R level clustering, the Ollama-driven
forecast maintenance (post-mortems + re-anchoring), the main chart, and the
forecast-review chart. Macro narrative (macro.xlsx) is maintained BY HAND —
downloaded fresh data + a manually written row every run; the AI never
touches it, but its latest entry is fed into every AI prompt as ground
truth for current events. `_api.py` is an unrelated, unused data-fetch
script, untouched by this file.

Requires: pandas, plotly, and a running Ollama server (fully local, free).
"""

# ------------------------------------------------------------------
# 0) LOCAL LLM — the Ollama model that maintains the narrative
#    (macro events, forecast post-mortems, re-anchoring).
#    Change ONLY this line to switch models.
# ------------------------------------------------------------------
llm = 'gemma4'
OLLAMA_URL = "http://localhost:11434/api/chat"

import json
import re
import sys
import textwrap
import urllib.error
import urllib.request

import pandas as pd
import plotly.graph_objects as go

CSV_PATH = "data.csv"
MACRO_PATH = "macro.xlsx"
FORECAST_PATH = "forecast.xlsx"
PLOT_OUT_PATH = "PLOT.html"
FORECAST_OUT_PATH = "FORECAST.html"

# Anchor drift (price points) beyond which the forecast gets re-anchored —
# shared between the AI maintenance step and the printed report.
REANCHOR_TOLERANCE = 0.30

# tiny W/D pill-switch injected into both PLOT.html and FORECAST.html
# (plotly's native updatemenus buttons were rejected as too bulky)
TOGGLE_SNIPPET = """
<style>
#wd-toggle {{
  position: fixed; top: 10px; left: 14px; z-index: 999;
  display: flex; align-items: center; gap: 7px;
  font: 11px sans-serif; color: #8a8d98; user-select: none; cursor: pointer;
}}
#wd-toggle .lbl.on {{ color: #eaeaea; font-weight: 600; }}
#wd-track {{
  width: 30px; height: 16px; border-radius: 8px;
  background: #2b2d38; position: relative; transition: background .15s;
}}
#wd-knob {{
  width: 12px; height: 12px; border-radius: 50%; background: #5dade2;
  position: absolute; top: 2px; left: 2px; transition: left .15s;
}}
#wd-toggle.daily #wd-knob {{ left: 16px; }}
</style>
<div id="wd-toggle">
  <span class="lbl on" id="wd-w">W</span>
  <div id="wd-track"><div id="wd-knob"></div></div>
  <span class="lbl" id="wd-d">D</span>
</div>
<script>
(function () {{
  var el = document.getElementById('wd-toggle'), daily = false;
  el.addEventListener('click', function () {{
    daily = !daily;
    el.classList.toggle('daily', daily);
    document.getElementById('wd-w').classList.toggle('on', !daily);
    document.getElementById('wd-d').classList.toggle('on', daily);
    Plotly.restyle('chart',
      {{visible: daily ? {daily_mask} : {weekly_mask}}},
      {trace_idx});
  }});}})();
</script>
"""


def inject_toggle(path, trace_idx, weekly_mask, daily_mask):
    # json.dumps, not str() — Python's [True, False] would render as
    # invalid JS ([True, False] instead of [true, false]) and silently
    # break the click handler.
    snippet = TOGGLE_SNIPPET.format(
        trace_idx=json.dumps(trace_idx),
        weekly_mask=json.dumps(weekly_mask),
        daily_mask=json.dumps(daily_mask))
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace("</body>", snippet + "</body>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ------------------------------------------------------------------
# 1) SHARED DATA LOADING
#    Same daily->weekly cleaning used by the AI maintenance step, the
#    main chart and the forecast-review chart — loaded once.
# ------------------------------------------------------------------
def load_price_data():
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    for col in ["Price", "Open", "High", "Low"]:
        df[col] = df[col].astype(str).str.replace(",", "").astype(float)
    df = df.sort_values("Date").set_index("Date")

    weekly = df.resample("W-FRI").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Price", "last"),
    ).dropna()
    return df, weekly


# ------------------------------------------------------------------
# 2) SUPPORT / RESISTANCE LEVELS
#    Cluster weekly Highs (resistance candidates) and weekly Lows (support
#    candidates) within TOLERANCE into levels, keep levels whose touches
#    span more than MIN_WEEK_SPAN weeks, then merge R+S levels closer than
#    MERGE_DIST (touch-weighted price; mixed groups labeled "R/S"). Shared
#    by the main chart and the forecast-review chart so both agree.
# ------------------------------------------------------------------
TOLERANCE = 0.40     # price points considered "the same" level
MIN_WEEK_SPAN = 3    # must span MORE than this many weeks between first/last touch
MERGE_DIST = 0.5     # levels closer than this get merged


def cluster_levels(prices_with_weeks, tolerance):
    """Sort by price, merge points within `tolerance` of each other into clusters."""
    pts = sorted(prices_with_weeks, key=lambda t: t[0])
    clusters, current = [], [pts[0]]
    for p, w in pts[1:]:
        if p - current[-1][0] <= tolerance:
            current.append((p, w))
        else:
            clusters.append(current)
            current = [(p, w)]
    clusters.append(current)
    return clusters


def valid_levels(clusters, min_span):
    """Keep clusters whose touches span more than `min_span` weeks."""
    levels = []
    for c in clusters:
        prices = [p for p, w in c]
        weeks = [w for p, w in c]
        span = max(weeks) - min(weeks)
        if span > min_span:
            levels.append(dict(price=sum(prices) / len(prices), touches=len(c), span=span))
    return levels


def compute_levels(weekly):
    """weekly: DataFrame with High/Low columns and a `week_idx` column.
    Returns the merged level list: dicts with price, touches, span, kind."""
    resistance_pts = list(zip(weekly["High"], weekly["week_idx"]))
    support_pts = list(zip(weekly["Low"], weekly["week_idx"]))

    resistance_levels = valid_levels(cluster_levels(resistance_pts, TOLERANCE), MIN_WEEK_SPAN)
    support_levels = valid_levels(cluster_levels(support_pts, TOLERANCE), MIN_WEEK_SPAN)

    pool = (
        [dict(price=l["price"], touches=l["touches"], span=l["span"], kind="R") for l in resistance_levels]
        + [dict(price=l["price"], touches=l["touches"], span=l["span"], kind="S") for l in support_levels]
    )
    pool.sort(key=lambda l: l["price"])

    merged_groups, current = [], [pool[0]] if pool else []
    for lvl in pool[1:]:
        if lvl["price"] - current[-1]["price"] < MERGE_DIST:
            current.append(lvl)
        else:
            merged_groups.append(current)
            current = [lvl]
    if current:
        merged_groups.append(current)

    merged_levels = []
    for g in merged_groups:
        total_touches = sum(l["touches"] for l in g)
        weighted_price = sum(l["price"] * l["touches"] for l in g) / total_touches
        kinds = set(l["kind"] for l in g)
        kind_label = "R/S" if len(kinds) > 1 else kinds.pop()
        merged_levels.append(dict(
            price=weighted_price,
            touches=total_touches,
            span=max(l["span"] for l in g),
            kind=kind_label,
        ))
    return merged_levels


# ------------------------------------------------------------------
# 3) AI MAINTENANCE — the part of the routine that used to be done by
#    Claude, now done fully locally (and for free) by an Ollama model.
#
#    Macro narrative (macro.xlsx) is maintained BY HAND by the user —
#    downloaded fresh data + a manually written/updated row (date, icon,
#    text) every run. The AI step no longer touches it. It only maintains
#    the forecast:
#      1) POST-MORTEMS  — write a `note` on any completed forecast week
#                         that MISSED and has no note yet (the learning
#                         loop).
#      2) RE-ANCHOR     — if the anchor drifted > REANCHOR_TOLERANCE or a
#                         completed week of the live vintage missed,
#                         append a fresh 4-week vintage to forecast.xlsx
#                         and mark the replaced upcoming rows of the old
#                         vintage as superseded (never delete rows).
#
#    Talks to the local Ollama server over its HTTP API (stdlib urllib
#    only — no extra packages). If Ollama is not running the step is
#    SKIPPED with a warning and the chart is still built from the
#    existing xlsx files.
# ------------------------------------------------------------------
# Defined once, reused by SYSTEM_PROMPT and the re-anchor prompt so the
# model never sees two disagreeing icon lists.
ICON_CONVENTION = ('''Icon = the dominant driver of the week:
    💥 for war, 
    💵 for the FED, 
    ⚠️ for macro economic data (like US inflation and unemployment),
    🇪🇺 for the ECB,
    🇺🇸 for USA, 🇮🇹 for Italy, 🇨🇳 for China, 🇷🇺 for Russia, 🇮🇷 for Iran (and other countries by their flag).'''
)

# No hardcoded storyline/dates here on purpose — those go stale (e.g. a
# past "next ECB meeting" date left in forever). Ground truth for CURRENT
# events comes from market_context(), which splices in the latest hand-
# written row of macro.xlsx on every call.
SYSTEM_PROMPT = (
    "You are a fixed-income market analyst assisting with a weekly "
    "candlestick chart of the Italian BTP 4.5% Oct-2053 bond (price "
    "typically 90-106, quoted in points). The macro narrative itself "
    "(which events happened, which icon fits) is written by hand by the "
    "user, not you — your two jobs are: (1) CONDENSE the user's hand-"
    "written macro briefing into a one-sentence caption when asked, never "
    "inventing events not present in the text given; (2) maintain the "
    "FORECAST (post-mortem notes + the next 4-week vintage when "
    "re-anchoring). Base every judgment on the context passed in the user "
    "message (recent candles, S/R levels, and the latest hand-written "
    "macro briefing) — never on assumptions about what's happening in the "
    "world.\n"
    f"{ICON_CONVENTION}\n"
    "Forecast week text format: \"<b>Week N — short title</b><br>ICON "
    '<b>Label:</b> concrete detail...\", lines joined with <br>. Be '
    "concrete about price levels and keep the story consistent with the "
    "candle given.\n"
    "Always answer with ONLY the JSON object requested — no prose around it."
)


class OllamaUnavailable(RuntimeError):
    pass


def ollama_chat(model, user_prompt, temperature=0.4):
    """One JSON-mode chat round-trip against the local Ollama server."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OllamaUnavailable(
            f"Cannot reach Ollama at {OLLAMA_URL} ({e}). "
            "Start it with `ollama serve` (and `ollama pull <model>` once).")
    except urllib.error.HTTPError as e:
        raise OllamaUnavailable(f"Ollama error: {e.read().decode('utf-8', 'replace')}")
    return body["message"]["content"]


def ollama_json(model, user_prompt, temperature=0.4, retries=2):
    """Chat and parse the reply as JSON, re-asking on garbage output."""
    prompt = user_prompt
    for attempt in range(retries + 1):
        raw = ollama_chat(model, prompt, temperature)
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            prompt = (user_prompt +
                      "\n\nYour previous reply was not valid JSON. "
                      "Reply with ONLY the JSON object.")
    raise RuntimeError(f"Model kept returning invalid JSON:\n{raw[:400]}")


def maintain_macro_summary(model):
    """Condense any macro.xlsx row missing a `summary` into a one-sentence
    caption of its single most important event, paired with the user's
    icon. The full briefing (macro.xlsx's `text`) can run long — this is
    what the chart marker's hover shows and what gets pasted into every
    forecast/post-mortem prompt, instead of the whole raw blob."""
    try:
        events = pd.read_excel(MACRO_PATH)
    except FileNotFoundError:
        return False
    if events.empty:
        return False
    events["date"] = pd.to_datetime(events["date"])
    if "summary" not in events.columns:
        events["summary"] = ""
    events["summary"] = events["summary"].fillna("")
    changed = False

    for idx, row in events.iterrows():
        if str(row["summary"]).strip():
            continue
        prompt = (
            f"The user's hand-written macro briefing for the week of "
            f"{pd.Timestamp(row['date']).date()} (they chose icon "
            f"{row['icon']} as the dominant driver):\n\n{row['text']}\n\n"
            "Condense ONLY the single most important event/development "
            "from this text into one short, concrete sentence (max ~20 "
            "words, numbers/names over adjectives) — a caption to pair "
            "with the icon above that week's candle. Do not add anything "
            "not present in the text.\n"
            'Reply with JSON: {"summary": "..."}')
        summary = str(ollama_json(model, prompt, temperature=0.2)
                      .get("summary", "")).strip()
        events.loc[idx, "summary"] = summary
        print(f"  [{model}] summarized macro event "
              f"{pd.Timestamp(row['date']).date()}: {summary}")
        changed = True

    if changed:
        events["date"] = pd.to_datetime(events["date"])
        events.to_excel(MACRO_PATH, index=False)
    return changed


def latest_macro_briefing(max_chars=2500):
    """The most recent hand-written macro.xlsx row — the model's only
    grounding in real-world events now that macro narrative is user-owned.
    Prefers the short AI `summary` (see maintain_macro_summary); falls
    back to the raw `text`, truncated, if no summary exists yet."""
    try:
        events = pd.read_excel(MACRO_PATH)
    except FileNotFoundError:
        return ""
    if events.empty:
        return ""
    events["date"] = pd.to_datetime(events["date"])
    latest = events.sort_values("date").iloc[-1]
    summary = str(latest.get("summary", "")).strip()
    if summary and summary.lower() != "nan":
        body = summary
    else:
        body = str(latest["text"]).strip()
        if len(body) > max_chars:
            body = body[:max_chars] + " …(truncated)"
    return (f"\nLatest hand-written macro briefing "
            f"({pd.Timestamp(latest['date']).date()}, this IS current "
            f"reality, treat it as ground truth): {body}\n")


def market_context(df, weekly):
    """Compact market snapshot pasted into every prompt."""
    wk = weekly.reset_index().rename(columns={"Date": "WeekEnd"})
    wk["week_idx"] = wk.index
    levels = compute_levels(wk)
    lvl_txt = ", ".join(f"{l['kind']} {l['price']:.2f}"
                        for l in sorted(levels, key=lambda l: -l["price"]))
    candles = "\n".join(
        f"  week ending {d.date()}: O={r['Open']:.2f} H={r['High']:.2f} "
        f"L={r['Low']:.2f} C={r['Close']:.2f}"
        for d, r in weekly.tail(8).iterrows())
    return (f"Recent weekly candles:\n{candles}\n"
            f"S/R levels: {lvl_txt}\n"
            f"ATH {df['High'].max():.2f}, ATL {df['Low'].min():.2f}, "
            f"psychological level 100.00\n"
            f"Latest daily close: {df['Price'].iloc[-1]:.2f} on "
            f"{df.index.max().date()}\n"
            f"{latest_macro_briefing()}")


def clean_icon(icon):
    """Keep just the emoji: the model sometimes returns "🇪🇺 ECB" instead of
    "🇪🇺", which would otherwise render as literal text on the chart."""
    icon = str(icon).strip().split()[0] if str(icon).strip() else ""
    return icon if 0 < len(icon) <= 8 else "↔️"


def score_week(fc_row, actual):
    in_range = fc_row["Low"] - 0.05 <= actual["Close"] <= fc_row["High"] + 0.05
    same_dir = ((fc_row["Close"] - fc_row["Open"]) *
                (actual["Close"] - actual["Open"]) >= 0)
    return "HIT" if (in_range and same_dir) else "MISS"


def sane_candle(o, h, l, c, anchor):
    """Clamp one forecast candle into a plausible shape/range."""
    o, h, l, c = float(o), float(h), float(l), float(c)
    lo_bound, hi_bound = anchor - 6.0, anchor + 6.0
    o = min(max(o, lo_bound), hi_bound)
    c = min(max(c, lo_bound), hi_bound)
    h = min(max(h, max(o, c)), hi_bound)
    l = max(min(l, min(o, c)), lo_bound)
    return round(o, 2), round(h, 2), round(l, 2), round(c, 2)


def maintain_forecast(model, df, weekly, context, instructions=""):
    """Post-mortem notes on misses, drift check, re-anchor into a new vintage."""
    fc_all = pd.read_excel(FORECAST_PATH)
    fc_all["week_end"] = pd.to_datetime(fc_all["week_end"])
    fc_all["made_on"] = pd.to_datetime(fc_all["made_on"])
    if "note" not in fc_all.columns:
        fc_all["note"] = ""
    fc_all["note"] = fc_all["note"].fillna("")

    last_day = df.index.max()
    last_week_end = weekly.index.max()
    last_close = weekly["Close"].iloc[-1]
    live_made_on = fc_all["made_on"].max()
    live = fc_all[fc_all["made_on"] == live_made_on]
    anchor = float(live["anchor_close"].iloc[0])
    changed = False

    lessons = [n for n in fc_all["note"]
               if n and not n.lower().startswith("superseded")]
    lessons_txt = ("\nPast forecast post-mortems (learn from these):\n" +
                   "\n".join(f"  - {n}" for n in lessons[-4:])) if lessons else ""

    # --- post-mortem notes on completed MISSes without one -------------
    problems = []
    for idx, row in fc_all.iterrows():
        we = row["week_end"]
        note = str(row["note"]).strip()
        if note.lower().startswith("superseded") or we > last_week_end \
                or we not in weekly.index:
            continue
        act = weekly.loc[we]
        verdict = score_week(row, act)
        if row["made_on"] == live_made_on and verdict == "MISS":
            problems.append(f"week {we.date()} missed")
        if verdict == "MISS" and not note:
            provisional = we == last_week_end and last_day < last_week_end
            prompt = (
                f"{context}\n\nA forecast made on "
                f"{row['made_on'].date()} (anchor {row['anchor_close']:.2f}) "
                f"predicted for the week ending {we.date()}: "
                f"O={row['Open']:.2f} H={row['High']:.2f} L={row['Low']:.2f} "
                f"C={row['Close']:.2f}.\nThe actual candle was: "
                f"O={act['Open']:.2f} H={act['High']:.2f} L={act['Low']:.2f} "
                f"C={act['Close']:.2f} -> scored MISS.\n"
                f"{'The week is NOT finished yet, so this is a PROVISIONAL verdict (it can still flip at Friday close). ' if provisional else ''}"
                "Write a 2-3 sentence post-mortem note: why it missed and the "
                'lesson for the next forecast. Reply with JSON: {"note": "..."}')
            note_txt = str(ollama_json(model, prompt).get("note", "")).strip()
            if provisional:
                note_txt = "PROVISIONAL MISS (week not finished): " + note_txt
            fc_all.loc[idx, "note"] = note_txt
            print(f"  [{model}] post-mortem note on {we.date()} "
                  f"(vintage {row['made_on'].date()})")
            changed = True

    # --- drift check / re-anchor --------------------------------------
    drift = last_close - anchor
    if abs(drift) > REANCHOR_TOLERANCE:
        problems.append(f"anchor drift {drift:+.2f}")
    if instructions:
        # explicit user instructions always force a fresh vintage
        problems.append(f'user instruction: "{instructions}"')

    if problems:
        print(f"  REVIEW ({'; '.join(problems)}) -> re-anchoring forecast")
        fridays = [last_week_end + pd.Timedelta(days=7 * i) for i in (1, 2, 3, 4)]
        prompt = (
            f"{context}\n{lessons_txt}\n\n"
            f"The live forecast (made {live_made_on.date()}, anchor "
            f"{anchor:.2f}) needs re-anchoring: {'; '.join(problems)}. "
            f"The latest weekly close is {last_close:.2f}.\n"
            "Write a NEW 4-week forecast for the weeks ending "
            f"{', '.join(str(d.date()) for d in fridays)}. Rules:\n"
            f"- Week 1 Open must equal the latest close {last_close:.2f}; "
            "each later Open equals the previous Close.\n"
            "- High >= max(Open, Close), Low <= min(Open, Close); weekly "
            "ranges typically 0.6-1.7 points; stay within a few points of "
            f"{last_close:.2f} and respect the S/R levels above.\n"
            "- One coherent 4-week scenario arc grounded in the specific "
            "catalysts named in the context above (the macro briefing and "
            "recent candles) — do not invent events not mentioned there; "
            "per-week text formatted exactly like this example (with real "
            "flag emoji, never the word ICON): "
            '"<b>Week 1 — Truce rally stalls</b><br>\U0001F1FA\U0001F1F8 '
            '<b>Fed:</b> hot CPI keeps hike risk alive...<br>'
            '\U0001F1EA\U0001F1FA <b>ECB:</b> ...".\n'
            + (f'\nMOST IMPORTANT — the user explicitly demanded: '
               f'"{instructions}". The new forecast MUST follow this.\n'
               if instructions else "") +
            'Reply with JSON: {"weeks": [{"Open": .., "High": .., "Low": .., '
            '"Close": .., "icon": "..", "text": ".."}, ... 4 items ..]}. '
            f'Every week MUST have an "icon": {ICON_CONVENTION}')
        for attempt in range(2):
            out = ollama_json(model, prompt, temperature=0.5)
            weeks = out.get("weeks", [])
            if len(weeks) == 4:
                break
            prompt += "\n\nYou must return exactly 4 items in \"weeks\"."
        if len(weeks) != 4:
            raise RuntimeError("Model failed to produce a 4-week forecast.")

        made_on = pd.Timestamp(last_day.date())
        if made_on <= live_made_on:
            # same-day re-anchor: keep the date but make the vintage key
            # unique, otherwise the new rows would merge into the old vintage
            made_on = live_made_on + pd.Timedelta(hours=1)
        new_rows, prev_close = [], last_close
        for d, w in zip(fridays, weeks):
            o, h, l, c = sane_candle(w.get("Open", prev_close),
                                     w.get("High", prev_close),
                                     w.get("Low", prev_close),
                                     w.get("Close", prev_close), last_close)
            o = prev_close  # chain opens onto the anchor / previous close
            h, l = max(h, max(o, c)), min(l, min(o, c))
            new_rows.append({"week_end": d, "Open": round(o, 2),
                             "High": round(h, 2), "Low": round(l, 2),
                             "Close": round(c, 2),
                             "icon": clean_icon(w.get("icon", "")),
                             "text": str(w.get("text", "")).strip(),
                             "made_on": made_on, "anchor_close": last_close,
                             "note": ""})
            prev_close = c

        # mark the replaced upcoming rows of the old vintage — never delete
        sup = ((fc_all["made_on"] == live_made_on) &
               (fc_all["week_end"] > last_week_end) &
               (fc_all["note"] == ""))
        fc_all.loc[sup, "note"] = (
            f"superseded by {made_on.date()} re-anchor "
            f"({'; '.join(problems)})")

        fc_all = pd.concat([fc_all, pd.DataFrame(new_rows)], ignore_index=True)
        for d, r in zip(fridays, new_rows):
            print(f"    new fc {d.date()} {r['icon']} O={r['Open']:.2f} "
                  f"H={r['High']:.2f} L={r['Low']:.2f} C={r['Close']:.2f}")
        changed = True
    else:
        print(f"  forecast KEEP (drift {drift:+.2f} within "
              f"±{REANCHOR_TOLERANCE})")

    if changed:
        fc_all["week_end"] = pd.to_datetime(fc_all["week_end"])
        fc_all["made_on"] = pd.to_datetime(fc_all["made_on"])
        fc_all.to_excel(FORECAST_PATH, index=False)
    return changed


def run_ai_maintenance(model, df, weekly, instructions=""):
    print("=" * 70)
    print(f"0) AI MAINTENANCE (Ollama, model: {model})")
    if instructions:
        print(f'   user instructions: "{instructions}"')
    print("=" * 70)
    try:
        maintain_macro_summary(model)
        context = market_context(df, weekly)
        if instructions:
            # injected into every prompt (notes, forecast)
            context += ("\n\nUSER INSTRUCTIONS for this update — follow "
                        f"them: {instructions}")
        maintain_forecast(model, df, weekly, context, instructions)
    except OllamaUnavailable as e:
        print(f"  !! SKIPPED — {e}")
        print("  !! Building the chart from the existing xlsx files.")
    print()


# ------------------------------------------------------------------
# 4) MAIN CHART — weekly candles + daily toggle, S/R, ATH/ATL, macro
#    markers and the 4-week forecast.
# ------------------------------------------------------------------
def weekly_to_daily(week_end, o, h, l, c):
    """Expand one weekly forecast candle into a deterministic 5-day path
    reproducing the weekly OHLC exactly: first open=O, last close=C, H/L
    each touched once. Bullish weeks dip early and rally late; bearish
    weeks pop early and fade late."""
    days = pd.bdate_range(end=week_end, periods=5)
    if c >= o:  # bullish: O -> dip to L -> rally through H -> settle C
        closes = [o + 0.5 * (l - o), l, l + 0.55 * (h - l), h, c]
        low_day, high_day = 1, 3
    else:       # bearish: O -> pop to H -> fade through L -> settle C
        closes = [o + 0.5 * (h - o), h, h - 0.55 * (h - l), l, c]
        high_day, low_day = 1, 3
    wick = 0.05 * (h - l)
    candles, prev = [], o
    for i, (d, cl) in enumerate(zip(days, closes)):
        hi = min(h, max(prev, cl) + wick)
        lo = max(l, min(prev, cl) - wick)
        if i == high_day:
            hi = h
        if i == low_day:
            lo = l
        candles.append(dict(Date=d, Open=prev, High=hi, Low=lo, Close=cl))
        prev = cl
    return candles


def build_main_chart(df, weekly):
    weekly = weekly.reset_index().rename(columns={"Date": "WeekEnd"})
    weekly["week_idx"] = weekly.index  # 0,1,2... sequential week number

    candle = go.Candlestick(
        x=weekly["WeekEnd"],
        open=weekly["Open"], high=weekly["High"],
        low=weekly["Low"], close=weekly["Close"],
        name="IT000553414 (weekly)",
        increasing=dict(line=dict(color="#2ecc71")),
        decreasing=dict(line=dict(color="#e74c3c")),
    )

    # Daily view of the SAME history (toggled via the Weekly/Daily buttons;
    # weekly stays the driver — S/R, events and forecast are all computed weekly)
    candle_daily = go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Price"],
        name="IT000553414 (daily)",
        increasing=dict(line=dict(color="#2ecc71")),
        decreasing=dict(line=dict(color="#e74c3c")),
        visible=False,
    )

    fig = go.Figure(data=[candle, candle_daily])

    # --- S/R levels (filtered/merged) ---------------------------------
    x_start = weekly["WeekEnd"].min()
    x_end = weekly["WeekEnd"].max()

    merged_levels = compute_levels(weekly)

    print(f"\nMerged into {len(merged_levels)} final level(s) (merge dist < {MERGE_DIST}):")
    for lvl in sorted(merged_levels, key=lambda l: -l["price"]):
        print(f"  🟨{lvl['kind']} {lvl['price']:.2f}  touches={lvl['touches']}  span={lvl['span']}wk")

    shapes, annotations = [], []
    for lvl in merged_levels:
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=x_start, x1=x_end, y0=lvl["price"], y1=lvl["price"],
            line=dict(color="rgba(241,196,15,0.75)", width=1.4, dash="dot"),
        ))
        annotations.append(dict(
            x=x_end, y=lvl["price"], xref="x", yref="y",
            text=f"🟨{lvl['kind']} {lvl['price']:.1f}", showarrow=False,
            xanchor="left", font=dict(color="#f1c40f", size=11),
        ))

    # --- ATH / ATL (whole dataset) -------------------------------------
    abs_high = df["High"].max()
    abs_low = df["Low"].min()

    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x_start, x1=x_end, y0=abs_high, y1=abs_high,
        line=dict(color="#2ecc71", width=2, dash="solid"),
    ))
    annotations.append(dict(
        x=x_end, y=abs_high, xref="x", yref="y",
        text=f"🟩 ATH {abs_high:.2f}", showarrow=False,
        xanchor="left", font=dict(color="#2ecc71", size=12),
    ))

    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x_start, x1=x_end, y0=abs_low, y1=abs_low,
        line=dict(color="#e74c3c", width=2, dash="solid"),
    ))
    annotations.append(dict(
        x=x_end, y=abs_low, xref="x", yref="y",
        text=f"🟥 ATL {abs_low:.2f}", showarrow=False,
        xanchor="left", yanchor="top", font=dict(color="#e74c3c", size=12),
    ))

    print(f"\nAbsolute high (ATH): {abs_high:.2f}")
    print(f"Absolute low (ATL):  {abs_low:.2f}")

    # --- macro event markers ---------------------------------------------
    # macro.xlsx (date, icon, text) is maintained BY HAND by the user — a
    # fresh row every time they download new data, dated whatever day they
    # actually wrote it (not necessarily a Friday). `text` is often a long
    # freeform briefing, so the hover shows the AI-condensed `summary`
    # (see maintain_macro_summary) instead — one sentence, paired with the
    # user's icon. Falls back to the raw text (truncated) if no summary
    # exists yet (e.g. Ollama was unreachable).
    macro_df = pd.read_excel(MACRO_PATH)
    macro_df["date"] = pd.to_datetime(macro_df["date"])
    # snap each row to the Friday of its own Mon-Sun week, so a row dated
    # any weekday still lands on that week's candle; if two rows land on
    # the same Friday, the most recently written one wins
    macro_df["friday"] = macro_df["date"] + pd.to_timedelta(
        (4 - macro_df["date"].dt.weekday) % 7, unit="D")
    macro_df = macro_df.sort_values("date").drop_duplicates("friday", keep="last")
    macro_events = macro_df.to_dict("records")

    event_df = weekly.set_index("WeekEnd")
    marker_x, marker_y, marker_text, marker_icon = [], [], [], []

    for ev in macro_events:
        d = pd.Timestamp(ev["friday"])
        if d not in event_df.index:
            continue
        row = event_df.loc[d]
        marker_x.append(d)
        marker_y.append(row["High"] + 0.9)  # float marker just above the candle
        marker_icon.append(ev["icon"])
        summary = str(ev.get("summary", "")).strip()
        if summary and summary.lower() != "nan":
            body = summary
        else:
            body = str(ev["text"]).replace("\n", "<br>")
            body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
            if len(body) > 400:
                body = body[:400] + " …"
        marker_text.append(
            f"<b>{pd.Timestamp(ev['date']).strftime('%d %b %Y')}</b><br>{body}")

    fig.add_trace(go.Scatter(
        x=marker_x, y=marker_y,
        mode="text", text=marker_icon, textfont=dict(size=20),
        hovertext=marker_text, hoverinfo="text",
        hoverlabel=dict(bgcolor="#1a1b22", font=dict(color="#eaeaea", size=12), align="left"),
        name="Macro events", showlegend=True,
    ))

    # --- forecast: next 4 weekly candles (blue) -------------------------
    last_date = weekly["WeekEnd"].max()
    last_close = weekly["Close"].iloc[-1]

    forecast_df = pd.read_excel(FORECAST_PATH)
    forecast_df["week_end"] = pd.to_datetime(forecast_df["week_end"])
    forecast_df["made_on"] = pd.to_datetime(forecast_df["made_on"])
    # the file is an append-only log of every forecast vintage (keyed by made_on,
    # with a `note` column scoring past vintages) — plot only the latest vintage
    forecast_df = forecast_df[forecast_df["made_on"] == forecast_df["made_on"].max()]
    fc_made_on = pd.Timestamp(forecast_df["made_on"].iloc[0])
    fc_anchor = float(forecast_df["anchor_close"].iloc[0])
    # only plot weeks that are still in the future vs the actual data
    forecast = forecast_df[forecast_df["week_end"] > last_date].to_dict("records")

    fc_x, fc_open, fc_high, fc_low, fc_close = [], [], [], [], []
    fc_icon_x, fc_icon_y, fc_icon, fc_icon_text = [], [], [], []

    for f in forecast:
        d = f["week_end"]
        fc_x.append(d)
        fc_open.append(f["Open"])
        fc_high.append(f["High"])
        fc_low.append(f["Low"])
        fc_close.append(f["Close"])
        fc_icon_x.append(d)
        fc_icon_y.append(f["High"] + 0.9)
        fc_icon.append(f["icon"])
        fc_icon_text.append(f"<b>{d.strftime('%d %b %Y')} — FORECAST</b><br>{f['text']}")

    fig.add_trace(go.Candlestick(
        x=fc_x, open=fc_open, high=fc_high, low=fc_low, close=fc_close,
        name="Forecast (4wk)",
        increasing=dict(line=dict(color="#5dade2"), fillcolor="rgba(93,173,226,0.30)"),
        decreasing=dict(line=dict(color="#2980b9"), fillcolor="rgba(41,128,185,0.80)"),
    ))

    fcd = [c for f in forecast
           for c in weekly_to_daily(f["week_end"], f["Open"], f["High"], f["Low"], f["Close"])]

    fig.add_trace(go.Candlestick(
        x=[c["Date"] for c in fcd],
        open=[c["Open"] for c in fcd], high=[c["High"] for c in fcd],
        low=[c["Low"] for c in fcd], close=[c["Close"] for c in fcd],
        name="Forecast (daily)",
        increasing=dict(line=dict(color="#5dade2"), fillcolor="rgba(93,173,226,0.30)"),
        decreasing=dict(line=dict(color="#2980b9"), fillcolor="rgba(41,128,185,0.80)"),
        visible=False,
    ))

    fig.add_trace(go.Scatter(
        x=fc_icon_x, y=fc_icon_y,
        mode="text", text=fc_icon, textfont=dict(size=20),
        hovertext=fc_icon_text, hoverinfo="text",
        hoverlabel=dict(bgcolor="#12283a", font=dict(color="#eaeaea", size=12), align="left"),
        name="Forecast drivers", showlegend=True,
    ))

    # divider marking where history ends and forecast begins (Saturday
    # 00:00 = start of the weekend rangebreak, so in both views it renders
    # right between the last actual candle and the first forecast one)
    divider_x = last_date + pd.Timedelta(days=1)
    shapes.append(dict(
        type="line", xref="x", yref="paper",
        x0=divider_x, x1=divider_x, y0=0, y1=1,
        line=dict(color="#5dade2", width=1.5, dash="dash"),
    ))
    annotations.append(dict(
        x=divider_x, y=1.0, xref="x", yref="paper",
        text="FORECAST →", showarrow=False, xanchor="left", yanchor="bottom",
        font=dict(color="#5dade2", size=11),
    ))

    # extend S/R + ATH/ATL lines across the forecast window
    for s in shapes:
        if s.get("yref") == "y" and s.get("x1") == x_end:
            s["x1"] = fc_x[-1]
    for a in annotations:
        if a.get("yref") == "y" and a.get("x") == x_end:
            a["x"] = fc_x[-1]

    # flat white line at price = 100 (round-number psychological level)
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x_start, x1=fc_x[-1], y0=100, y1=100,
        line=dict(color="#ffffff", width=1.5, dash="solid"),
    ))
    annotations.append(dict(
        x=fc_x[-1], y=100, xref="x", yref="y",
        text="100.00", showarrow=False,
        xanchor="left", font=dict(color="#ffffff", size=11),
    ))

    print(f"\nForecast made on {fc_made_on.date()} (anchor close {fc_anchor:.2f}); "
          f"data now ends {last_date.date()} close = {last_close:.2f}")
    for f, d in zip(forecast, fc_x):
        print(f"  {d.date()} {f['icon']}  O={f['Open']:.2f} H={f['High']:.2f} "
              f"L={f['Low']:.2f} C={f['Close']:.2f}")

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e0f13", plot_bgcolor="#0e0f13",
        font=dict(color="#eaeaea"),
        margin=dict(t=40, r=90, b=40, l=50),
        xaxis=dict(
            rangeslider=dict(visible=True, bgcolor="#1a1b22"),
            gridcolor="#23242c", type="date",
            rangebreaks=[dict(bounds=["sat", "mon"])],  # hide weekends (daily view)
        ),
        yaxis=dict(
            gridcolor="#23242c", side="right",
            dtick=1, tick0=0, showgrid=True,  # gridline + label every whole price point
        ),
        shapes=shapes, annotations=annotations, showlegend=False,
    )

    fig.write_html(PLOT_OUT_PATH, include_plotlyjs="cdn", div_id="chart")
    # W/D toggle flips visibility of traces 0/1 (history) and 3/4 (forecast);
    # traces 2/5 (macro + forecast icons) are weekly-anchored and stay on.
    inject_toggle(PLOT_OUT_PATH, trace_idx=[0, 1, 3, 4],
                  weekly_mask=[True, False, True, False],
                  daily_mask=[False, True, False, True])
    print(f"\nSaved: {PLOT_OUT_PATH}")


# ------------------------------------------------------------------
# 5) FORECAST REVIEW CHART — every forecast vintage in forecast.xlsx vs
#    the real weekly candles, with HIT/MISS verdicts and the post-mortem
#    `note` on hover.
# ------------------------------------------------------------------
CONTEXT_WEEKS = 8          # actual candles shown before the first forecast week
# vintage colors, oldest -> newest (newest = the live, brightest blue);
# all steps pass >=3:1 contrast on the #0e0f13 surface — don't go darker
VINTAGE_LADDER = ["#3465ad", "#4f8ecf", "#66b8f2"]


def wrap(s, width=70):
    return "<br>".join(textwrap.wrap(str(s), width)) if str(s).strip() else ""


def build_forecast_review_chart(df, weekly):
    weekly = weekly.copy()
    weekly["week_idx"] = range(len(weekly))
    last_week_end = weekly.index.max()

    fc = pd.read_excel(FORECAST_PATH)
    fc["week_end"] = pd.to_datetime(fc["week_end"])
    fc["made_on"] = pd.to_datetime(fc["made_on"])
    if "note" not in fc.columns:
        fc["note"] = ""
    fc["note"] = fc["note"].fillna("")

    vintages = sorted(fc["made_on"].unique())
    # spread vintage colors across the ladder so consecutive vintages contrast,
    # with the live (newest) vintage always the brightest blue
    L = len(VINTAGE_LADDER)
    n = len(vintages)
    colors = [VINTAGE_LADDER[-1]] if n == 1 else \
        [VINTAGE_LADDER[min(round(i * (L - 1) / (n - 1)), L - 1)] for i in range(n)]

    window_start = fc["week_end"].min() - pd.Timedelta(weeks=CONTEXT_WEEKS)
    win = weekly[weekly.index >= window_start]

    fig = go.Figure()

    # actual weekly candles (trace 0)
    fig.add_trace(go.Candlestick(
        x=win.index, open=win["Open"], high=win["High"],
        low=win["Low"], close=win["Close"],
        name="actual",
        increasing=dict(line=dict(color="#2ecc71")),
        decreasing=dict(line=dict(color="#e74c3c")),
    ))

    # daily view of the same actuals (toggled via the W/D switch; forecast
    # vintages and verdicts stay weekly — daily is visualization only).
    # MUST be trace 1: the toggle snippet restyles traces [0, 1].
    win_daily = df[df.index >= window_start]
    fig.add_trace(go.Candlestick(
        x=win_daily.index, open=win_daily["Open"], high=win_daily["High"],
        low=win_daily["Low"], close=win_daily["Price"],
        name="actual (daily)",
        increasing=dict(line=dict(color="#2ecc71")),
        decreasing=dict(line=dict(color="#e74c3c")),
        visible=False,
    ))

    # one band + close-line per forecast vintage, plus verdict markers
    hits = misses = 0
    annotations = []

    for vi, made in enumerate(vintages):
        grp_all = fc[fc["made_on"] == made].sort_values("week_end")
        anchor = float(grp_all["anchor_close"].iloc[0])
        # drop rows superseded by a later vintage's forecast for the same
        # week — if two forecasts are made for the same week, only the
        # latest one is drawn (older vintages just stop at their last
        # still-live/completed week instead of overlapping the new one)
        grp = grp_all[~grp_all["note"].str.lower().str.startswith("superseded")]
        if grp.empty:
            continue
        color = colors[vi]
        is_live = made == vintages[-1]
        label = f"made {pd.Timestamp(made).strftime('%d %b')}" + (" · live" if is_live else "")

        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        xs = list(grp["week_end"])

        # Low-High range band
        fig.add_trace(go.Scatter(
            x=xs + xs[::-1],
            y=list(grp["High"]) + list(grp["Low"])[::-1],
            mode="none", fill="toself", fillcolor=f"rgba({r},{g},{b},0.14)",
            hoverinfo="skip", showlegend=False,
        ))

        # anchor point -> forecast Close path
        hover = [f"<b>{pd.Timestamp(made).strftime('%d %b %Y')} — anchor {anchor:.2f}</b><br>"
                 f"forecast {label} starts here"]
        for _, row in grp.iterrows():
            note = wrap(row["note"])
            hover.append(
                f"<b>{row['week_end'].strftime('%d %b %Y')} — FORECAST ({label})</b><br>"
                f"O={row['Open']:.2f} H={row['High']:.2f} "
                f"L={row['Low']:.2f} C={row['Close']:.2f}"
                + (f"<br><i>{note}</i>" if note else "")
            )
        fig.add_trace(go.Scatter(
            x=[made] + xs, y=[anchor] + list(grp["Close"]),
            mode="lines+markers",
            line=dict(color=color, width=2, dash="solid" if is_live else "dash"),
            marker=dict(size=8, symbol=["diamond"] + ["circle"] * len(xs)),
            hovertext=hover, hoverinfo="text",
            hoverlabel=dict(bgcolor="#12283a", font=dict(color="#eaeaea", size=12),
                            align="left"),
            showlegend=False,
        ))

        # direct label at the vintage's last point (legend-free identity)
        annotations.append(dict(
            x=xs[-1], y=float(grp["Close"].iloc[-1]), xref="x", yref="y",
            text=label, showarrow=False, xanchor="left", xshift=8,
            yshift=0 if is_live else -12,
            font=dict(color=color, size=11),
        ))

        # verdict markers on completed, non-superseded weeks
        for _, row in grp.iterrows():
            note = str(row["note"]).strip()
            if note.lower().startswith("superseded"):
                continue
            we = row["week_end"]
            if we <= last_week_end and we in weekly.index:
                act = weekly.loc[we]
                in_range = row["Low"] - 0.05 <= act["Close"] <= row["High"] + 0.05
                same_dir = (row["Close"] - row["Open"]) * (act["Close"] - act["Open"]) >= 0
                hit = in_range and same_dir
                hits += hit
                misses += not hit
                verdict = "HIT ✅" if hit else "MISS ❌"
                vtext = (f"<b>{we.strftime('%d %b %Y')} — {verdict} ({label})</b><br>"
                         f"forecast {row['Low']:.2f}–{row['High']:.2f} C={row['Close']:.2f} "
                         f"| actual C={act['Close']:.2f}")
                wnote = wrap(row["note"])
                if wnote:
                    vtext += f"<br><i>{wnote}</i>"
                elif not hit:
                    vtext += "<br><i>(no post-mortem note yet — add one in forecast.xlsx)</i>"
                fig.add_trace(go.Scatter(
                    x=[we], y=[max(row["High"], act["High"]) + 0.6],
                    mode="text", text=["✅" if hit else "❌"], textfont=dict(size=17),
                    hovertext=[vtext], hoverinfo="text",
                    hoverlabel=dict(bgcolor="#1a1b22", font=dict(color="#eaeaea", size=12),
                                    align="left"),
                    showlegend=False,
                ))

    # S/R levels (same computation as the main chart, over the FULL weekly
    # history) + the white line at 100 — identical to the main chart
    shapes = []
    x0 = win.index.min()
    x1 = fc["week_end"].max()

    for lvl in compute_levels(weekly.reset_index().rename(columns={"Date": "WeekEnd"})):
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=x0, x1=x1, y0=lvl["price"], y1=lvl["price"],
            line=dict(color="rgba(241,196,15,0.75)", width=1.4, dash="dot"),
        ))
        annotations.append(dict(
            x=x1, y=lvl["price"], xref="x", yref="y",
            text=f"🟨{lvl['kind']} {lvl['price']:.1f}", showarrow=False,
            xanchor="left", font=dict(color="#f1c40f", size=11),
        ))

    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x0, x1=x1, y0=100, y1=100,
        line=dict(color="#ffffff", width=1.5, dash="solid"),
    ))
    annotations.append(dict(
        x=x1, y=100, xref="x", yref="y",
        text="100.00", showarrow=False,
        xanchor="left", font=dict(color="#ffffff", size=11),
    ))

    # divider where actual data ends (Saturday = weekend-rangebreak edge, so
    # it sits between candles in both the weekly and daily views)
    divider_x = last_week_end + pd.Timedelta(days=1)
    shapes.append(dict(
        type="line", xref="x", yref="paper",
        x0=divider_x, x1=divider_x, y0=0, y1=1,
        line=dict(color="#66b8f2", width=1.5, dash="dash"),
    ))
    annotations.append(dict(
        x=divider_x, y=1.0, xref="x", yref="paper",
        text="FORECAST →", showarrow=False, xanchor="left", yanchor="bottom",
        font=dict(color="#66b8f2", size=11),
    ))

    scored = hits + misses
    title = "Forecast vs actual — hover ❌/✅ for the verdict & post-mortem"
    if scored:
        title += f"   ·   track record {hits}/{scored} ({100 * hits / scored:.0f}%)"

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e0f13", plot_bgcolor="#0e0f13",
        font=dict(color="#eaeaea"),
        # x shifted right to clear the fixed W/D toggle pinned at the top-left
        title=dict(text=title, font=dict(size=13, color="#aab4c0"), x=0.06),
        margin=dict(t=50, r=110, b=40, l=50),
        xaxis=dict(
            rangeslider=dict(visible=False), gridcolor="#23242c", type="date",
            rangebreaks=[dict(bounds=["sat", "mon"])],  # hide weekends (daily view)
        ),
        yaxis=dict(gridcolor="#23242c", side="right", dtick=1, tick0=0, showgrid=True),
        shapes=shapes, annotations=annotations, showlegend=False,
    )

    fig.write_html(FORECAST_OUT_PATH, include_plotlyjs="cdn", div_id="chart")
    # here the toggle only flips the actual candles: trace 0 (weekly) <-> trace 1 (daily)
    inject_toggle(FORECAST_OUT_PATH, trace_idx=[0, 1],
                  weekly_mask=[True, False], daily_mask=[False, True])

    print(f"{len(vintages)} vintage(s), track record {hits}/{scored} hit")
    print(f"Saved: {FORECAST_OUT_PATH}")


# ------------------------------------------------------------------
# 6) ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    # optional free-text instructions from the terminal
    instructions = " ".join(sys.argv[1:]).strip()

    df, weekly = load_price_data()

    run_ai_maintenance(llm, df, weekly, instructions)

    build_main_chart(df, weekly)

    print("\nBuilding forecast review chart...")
    build_forecast_review_chart(df, weekly)
