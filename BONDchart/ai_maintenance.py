"""
AI maintenance step — the part of the routine that used to be done by Claude,
now done fully locally (and for free) by an Ollama model.

Called from run.py as run_ai_maintenance(llm) BEFORE the chart is built, so a
plain `python3 run.py` executes the whole cycle:

  1) MACRO EVENTS  — write a macro_events.xlsx row for any weekly candle that
                     has none, and refresh the in-progress week's text.
  2) POST-MORTEMS  — write a `note` on any completed forecast week that MISSED
                     and has no note yet (the learning loop).
  3) RE-ANCHOR     — if the anchor drifted > REANCHOR_TOLERANCE or a completed
                     week of the live vintage missed, append a fresh 4-week
                     vintage to forecast.xlsx and mark the replaced upcoming
                     rows of the old vintage as superseded (never delete rows).

Talks to the local Ollama server over its HTTP API (stdlib urllib only — no
extra packages). If Ollama is not running the step is SKIPPED with a warning
and the chart is still built from the existing xlsx files.
"""

import json
import urllib.request
import urllib.error

import pandas as pd

OLLAMA_URL = "http://localhost:11434/api/chat"
CSV_PATH = "data.csv"
MACRO_EVENTS_PATH = "macro_events.xlsx"
FORECAST_PATH = "forecast.xlsx"

# Keep in sync with update.py
REANCHOR_TOLERANCE = 0.30

SYSTEM_PROMPT = (
    "You are a fixed-income market analyst maintaining the narrative for a "
    "weekly candlestick chart of the Italian BTP 4.5% Oct-2053 bond (price "
    "around 96-106, quoted in points). The 2026 storyline so far: Jan-Feb "
    "rally on rate-cut bets, US-Israel war on Iran erupted late Feb (Hormuz "
    "shut, oil spike, BTP crashed to the 96.60 YTD low), ceasefire relief "
    "rallies alternating with truce-break selloffs, ECB hiked to 2.25% in "
    "June and has held since (next projection meeting 10 Sept), hawkish Fed "
    "all year (no cuts in 2026), 10-day ceasefire SIGNED Aug 2. The Fed "
    "matters as much as the ECB in this narrative.\n"
    "ICON CONVENTION (dominant event of the week): \U0001F1EA\U0001F1FA ECB, "
    "\U0001F1EE\U0001F1F9 Italy, \U0001F1FA\U0001F1F8 Fed & US inflation, "
    "⚠️ US politics, other countries by their flag "
    "(\U0001F1EE\U0001F1F7 \U0001F1F7\U0001F1FA \U0001F1E8\U0001F1F3 ...), "
    "↔️ only for truly quiet weeks.\n"
    "Event text format: one line per sub-event, each formatted "
    '"ICON <b>Label:</b> text", lines joined with <br>. Be concrete about '
    "price levels and keep the story consistent with the candle given.\n"
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


# ------------------------------------------------------------------
# Shared loading (same cleaning as run.py / update.py)
# ------------------------------------------------------------------
def load_weekly():
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


def market_context(df, weekly):
    """Compact market snapshot pasted into every prompt."""
    from sr_levels import compute_levels
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
            f"{df.index.max().date()}")


def recent_events_text(events, n=4):
    ev = events.sort_values("date").tail(n)
    return "\n".join(
        f"  {pd.Timestamp(r['date']).date()} {r['icon']}: {r['text']}"
        for _, r in ev.iterrows())


def clean_icon(icon):
    icon = str(icon).strip()
    return icon if 0 < len(icon) <= 8 else "↔️"


# ------------------------------------------------------------------
# 1) Macro events: fill missing weeks + refresh the in-progress week
# ------------------------------------------------------------------
def maintain_macro_events(model, df, weekly, context):
    events = pd.read_excel(MACRO_EVENTS_PATH)
    events["date"] = pd.to_datetime(events["date"])
    have = set(events["date"].dt.date)
    last_day = df.index.max()
    last_week_end = weekly.index.max()
    changed = False

    def ask_event(week_end, row, in_progress, old_text=None):
        status = ("This week is STILL IN PROGRESS (data ends "
                  f"{last_day.date()}); phrase the last line as expectations "
                  "for the rest of the week." if in_progress else
                  "This week is complete; describe outcomes.")
        refresh = (f"\nThe row currently says (written before the week "
                   f"completed):\n{old_text}\nRewrite it so expectations "
                   "become outcomes consistent with the final candle."
                   if old_text else "")
        prompt = (
            f"{context}\n\nWrite the macro-event narrative for the weekly "
            f"candle ending Friday {week_end.date()}: O={row['Open']:.2f} "
            f"H={row['High']:.2f} L={row['Low']:.2f} C={row['Close']:.2f}. "
            f"{status}{refresh}\n\n"
            "Recent event rows for style/continuity:\n"
            f"{recent_events_text(events)}\n\n"
            'Reply with JSON: {"icon": "<dominant-event icon>", '
            '"text": "<icon <b>Label:</b> ... lines joined with <br>>", '
            '"source": "real news/institution domains joined with \' · \', '
            'e.g. reuters.com · federalreserve.gov · ecb.europa.eu"}')
        out = ollama_json(model, prompt)
        source = str(out.get("source", "")).strip()
        if not source or "site.com" in source:
            source = "reuters.com"
        return (clean_icon(out.get("icon", "")),
                str(out.get("text", "")).strip(),
                source)

    # fill weeks that have no row at all
    for week_end, row in weekly.iterrows():
        if week_end.date() in have:
            continue
        in_prog = week_end == last_week_end and last_day < last_week_end
        icon, text, source = ask_event(week_end, row, in_prog)
        events = pd.concat([events, pd.DataFrame([{
            "date": pd.Timestamp(week_end), "icon": icon,
            "text": text, "source": source}])], ignore_index=True)
        print(f"  [{model}] wrote macro event for {week_end.date()} {icon}")
        changed = True

    # refresh the latest data week's existing row (expectations -> outcomes)
    if not changed and last_week_end.date() in have:
        mask = events["date"].dt.date == last_week_end.date()
        old = events.loc[mask].iloc[0]
        in_prog = last_day < last_week_end
        icon, text, source = ask_event(
            last_week_end, weekly.loc[last_week_end], in_prog,
            old_text=str(old["text"]))
        events.loc[mask, ["icon", "text", "source"]] = [icon, text, source]
        print(f"  [{model}] refreshed macro event for {last_week_end.date()}")
        changed = True

    if changed:
        # GOTCHA: keep the whole date column datetime before writing
        events["date"] = pd.to_datetime(events["date"])
        events = events.sort_values("date").reset_index(drop=True)
        events.to_excel(MACRO_EVENTS_PATH, index=False)
    return changed


# ------------------------------------------------------------------
# 2+3) Forecast: post-mortem notes, drift check, re-anchor
# ------------------------------------------------------------------
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
            "- One coherent 4-week scenario arc (ECB 10 Sept meeting, Fed, "
            "ceasefire risk); per-week text formatted exactly like this "
            "example (with real flag emoji, never the word ICON): "
            '"<b>Week 1 — Truce rally stalls</b><br>\U0001F1FA\U0001F1F8 '
            '<b>Fed:</b> hot CPI keeps hike risk alive...<br>'
            '\U0001F1EA\U0001F1FA <b>ECB:</b> ...".\n'
            + (f'\nMOST IMPORTANT — the user explicitly demanded: '
               f'"{instructions}". The new forecast MUST follow this.\n'
               if instructions else "") +
            'Reply with JSON: {"weeks": [{"Open": .., "High": .., "Low": .., '
            '"Close": .., "icon": "..", "text": ".."}, ... 4 items ..]}. '
            'Every week MUST have an "icon": the dominant driver of that week '
            "(\U0001F1FA\U0001F1F8, \U0001F1EA\U0001F1FA, "
            "\U0001F1EE\U0001F1F9, \U0001F1EE\U0001F1F7 or ⚠️).")
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


# ------------------------------------------------------------------
# Entry point (called by run.py)
# ------------------------------------------------------------------
def run_ai_maintenance(model, instructions=""):
    print("=" * 70)
    print(f"0) AI MAINTENANCE (Ollama, model: {model})")
    if instructions:
        print(f'   user instructions: "{instructions}"')
    print("=" * 70)
    try:
        df, weekly = load_weekly()
        context = market_context(df, weekly)
        if instructions:
            # injected into every prompt (macro rows, notes, forecast)
            context += ("\n\nUSER INSTRUCTIONS for this update — follow "
                        f"them: {instructions}")
        maintain_macro_events(model, df, weekly, context)
        maintain_forecast(model, df, weekly, context, instructions)
    except OllamaUnavailable as e:
        print(f"  !! SKIPPED — {e}")
        print("  !! Building the chart from the existing xlsx files.")
    print()
