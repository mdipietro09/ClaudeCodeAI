"""
Daily/weekly maintenance check for the BTP chart.

Run AFTER downloading a fresh data.csv:

    python3 update.py

It reports:
  1) NEW DATA      — latest daily rows and the current weekly candle
  2) MACRO EVENTS  — weeks in the data that have no row in macro_events.xlsx
                     (i.e. narrative needs to be written for them)
  3) FORECAST      — per forecast week in forecast.xlsx:
                       - completed weeks: actual vs forecast (HIT/MISS on range
                         and direction)
                       - the in-progress / upcoming weeks: whether the anchor
                         close has drifted since the forecast was made
     Verdict: KEEP the forecast or REVIEW/RE-ANCHOR it.

It changes nothing by itself — edit macro_events.xlsx / forecast.xlsx by hand,
or just run `python3 run.py`: its AI maintenance step (local Ollama model, see
the `llm` variable at the top of run.py) applies the fixes and rebuilds.
"""

import pandas as pd

CSV_PATH = "data.csv"
MACRO_EVENTS_PATH = "macro_events.xlsx"
FORECAST_PATH = "forecast.xlsx"

# Anchor drift (in price points) beyond which the forecast should be redone
REANCHOR_TOLERANCE = 0.30

# ------------------------------------------------------------------
# Load daily data -> weekly candles (same logic as run.py)
# ------------------------------------------------------------------
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

last_day = df.index.max()
last_week_end = weekly.index.max()
last_close = weekly["Close"].iloc[-1]

print("=" * 70)
print("1) NEW DATA")
print("=" * 70)
print(f"Latest daily row : {last_day.date()}  close={df['Price'].iloc[-1]:.2f}")
print(f"Latest week      : ending {last_week_end.date()}  "
      f"O={weekly['Open'].iloc[-1]:.2f} H={weekly['High'].iloc[-1]:.2f} "
      f"L={weekly['Low'].iloc[-1]:.2f} C={last_close:.2f}")
print("Last 5 daily rows:")
print(df.tail(5)[["Open", "High", "Low", "Price"]].to_string())

# ------------------------------------------------------------------
# Macro events coverage
# ------------------------------------------------------------------
print()
print("=" * 70)
print("2) MACRO EVENTS (macro_events.xlsx)")
print("=" * 70)
events = pd.read_excel(MACRO_EVENTS_PATH)
event_dates = set(pd.to_datetime(events["date"]).dt.date)
week_dates = [d.date() for d in weekly.index]

missing = [d for d in week_dates if d not in event_dates]
if missing:
    print("Weeks WITHOUT a macro event row (write narrative for these):")
    for d in missing:
        print(f"  - {d}")
else:
    print("Every weekly candle has a macro event row. ✔")
latest_ev = events.sort_values("date").iloc[-1]
print(f"Latest event row : {pd.Timestamp(latest_ev['date']).date()} "
      f"{latest_ev['icon']} — check its text still matches what actually "
      f"happened that week.")

# ------------------------------------------------------------------
# Forecast validity
# ------------------------------------------------------------------
print()
print("=" * 70)
print("3) FORECAST (forecast.xlsx)")
print("=" * 70)
fc_all = pd.read_excel(FORECAST_PATH)
fc_all["week_end"] = pd.to_datetime(fc_all["week_end"])
fc_all["made_on"] = pd.to_datetime(fc_all["made_on"])
if "note" not in fc_all.columns:
    fc_all["note"] = ""
fc_all["note"] = fc_all["note"].fillna("")

# the file is an append-only log of every forecast vintage; only the LATEST
# vintage is "live" (plotted by run.py and judged for the verdict below)
fc = fc_all[fc_all["made_on"] == fc_all["made_on"].max()]
made_on = pd.to_datetime(fc["made_on"].iloc[0])
anchor_close = float(fc["anchor_close"].iloc[0])

print(f"Forecast made on : {made_on.date()}  anchored to close {anchor_close:.2f}")
print(f"Data now ends on : {last_day.date()}  weekly close {last_close:.2f}")

problems = []

drift = last_close - anchor_close
if abs(drift) > REANCHOR_TOLERANCE:
    problems.append(
        f"anchor drift {drift:+.2f} (> {REANCHOR_TOLERANCE}) — price has moved "
        f"since the forecast was made"
    )

print()
for _, row in fc.iterrows():
    we = row["week_end"]
    tag = f"  {we.date()} {row['icon']}  " \
          f"fc O={row['Open']:.2f} H={row['High']:.2f} " \
          f"L={row['Low']:.2f} C={row['Close']:.2f}"
    if we <= last_week_end and we in weekly.index:
        act = weekly.loc[we]
        in_range = row["Low"] - 0.05 <= act["Close"] <= row["High"] + 0.05
        same_dir = (row["Close"] - row["Open"]) * (act["Close"] - act["Open"]) >= 0
        verdict = "HIT" if (in_range and same_dir) else "MISS"
        print(f"{tag}  | actual C={act['Close']:.2f}  -> {verdict}")
        if verdict == "MISS":
            problems.append(f"week {we.date()} missed (actual close "
                            f"{act['Close']:.2f} vs forecast "
                            f"{row['Low']:.2f}-{row['High']:.2f})")
    else:
        print(f"{tag}  | upcoming")

# ------------------------------------------------------------------
# Forecast track record — every vintage ever made, scored, with the
# post-mortem note explaining each miss. Misses without a note are
# flagged: write the lesson down so the next forecast is better.
# ------------------------------------------------------------------
print()
print("=" * 70)
print("4) FORECAST TRACK RECORD (all vintages)")
print("=" * 70)
hits = misses = 0
for vintage, grp in fc_all.groupby("made_on"):
    live = " (LIVE)" if vintage == fc_all["made_on"].max() else ""
    print(f"\nVintage made {vintage.date()}  anchor {float(grp['anchor_close'].iloc[0]):.2f}{live}")
    for _, row in grp.iterrows():
        we = row["week_end"]
        note = str(row["note"]).strip()
        superseded = note.lower().startswith("superseded")
        tag = f"  {we.date()} {row['icon']}  " \
              f"fc O={row['Open']:.2f} H={row['High']:.2f} " \
              f"L={row['Low']:.2f} C={row['Close']:.2f}"
        if superseded:
            print(f"{tag}  | — {note}")
            continue
        if we <= last_week_end and we in weekly.index:
            act = weekly.loc[we]
            in_range = row["Low"] - 0.05 <= act["Close"] <= row["High"] + 0.05
            same_dir = (row["Close"] - row["Open"]) * (act["Close"] - act["Open"]) >= 0
            verdict = "HIT" if (in_range and same_dir) else "MISS"
            hits += verdict == "HIT"
            misses += verdict == "MISS"
            print(f"{tag}  | actual C={act['Close']:.2f}  -> {verdict}")
            if verdict == "MISS":
                if note:
                    print(f"      note: {note}")
                else:
                    print("      note: (MISSING — write a `note` in forecast.xlsx "
                          "explaining why this missed)")
                    problems.append(f"week {we.date()} (vintage {vintage.date()}) "
                                    f"missed but has no post-mortem note")
        else:
            print(f"{tag}  | upcoming")
scored = hits + misses
if scored:
    print(f"\nScore: {hits}/{scored} weeks hit ({100 * hits / scored:.0f}%)")

print()
print("=" * 70)
print("VERDICT")
print("=" * 70)
if problems:
    print("REVIEW / RE-ANCHOR the forecast:")
    for p in problems:
        print(f"  ✗ {p}")
    print("\n-> APPEND a new vintage to forecast.xlsx (week_end, OHLC, icon, "
          "text, made_on,\n   anchor_close, note) — never delete old rows; add "
          "a `note` post-mortem to any\n   missed week; mark replaced upcoming "
          "rows 'superseded by <date> re-anchor'.\n   Refresh the latest macro "
          "event text, then run: python3 run.py")
else:
    print("Forecast still valid — KEEP. ✔  (rebuild chart with: python3 run.py)")
