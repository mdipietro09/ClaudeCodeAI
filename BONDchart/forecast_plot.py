"""
Forecast review chart: every forecast vintage in forecast.xlsx vs the real
weekly candles, with HIT/MISS verdicts and the post-mortem `note` on hover.

    python3 forecast_plot.py   ->  FORECAST.html

Reads the same files as run.py / update.py; changes nothing.
"""

import textwrap

import pandas as pd
import plotly.graph_objects as go

from sr_levels import compute_levels

CSV_PATH = "data.csv"
FORECAST_PATH = "forecast.xlsx"
OUT_PATH = "FORECAST.html"

CONTEXT_WEEKS = 8          # actual candles shown before the first forecast week
# vintage colors, oldest -> newest (newest = the live, brightest blue);
# all steps pass >=3:1 contrast on the #0e0f13 surface — don't go darker
VINTAGE_LADDER = ["#3465ad", "#4f8ecf", "#66b8f2"]


def wrap(s, width=70):
    return "<br>".join(textwrap.wrap(str(s), width)) if str(s).strip() else ""


# ------------------------------------------------------------------
# Load actuals -> weekly candles (same logic as run.py)
# ------------------------------------------------------------------
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]
df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
for col in ["Price", "Open", "High", "Low"]:
    df[col] = df[col].astype(str).str.replace(",", "").astype(float)
df = df.sort_values("Date").set_index("Date")

weekly = df.resample("W-FRI").agg(
    Open=("Open", "first"), High=("High", "max"),
    Low=("Low", "min"), Close=("Price", "last"),
).dropna()
weekly["week_idx"] = range(len(weekly))
last_week_end = weekly.index.max()

# ------------------------------------------------------------------
# Load the forecast log
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# Actual weekly candles
# ------------------------------------------------------------------
fig.add_trace(go.Candlestick(
    x=win.index, open=win["Open"], high=win["High"],
    low=win["Low"], close=win["Close"],
    name="actual",
    increasing=dict(line=dict(color="#2ecc71")),
    decreasing=dict(line=dict(color="#e74c3c")),
))

# ------------------------------------------------------------------
# One band + close-line per forecast vintage, plus verdict markers
# ------------------------------------------------------------------
hits = misses = 0
annotations = []

for vi, made in enumerate(vintages):
    grp = fc[fc["made_on"] == made].sort_values("week_end")
    color = colors[vi]
    is_live = made == vintages[-1]
    anchor = float(grp["anchor_close"].iloc[0])
    label = f"made {pd.Timestamp(made).strftime('%d %b')}" + (" · live" if is_live else "")

    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    xs = list(grp["week_end"])

    # Low–High range band
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

# ------------------------------------------------------------------
# S/R levels (same computation as run.py, over the FULL weekly history)
# + the white line at 100 — identical to the main chart
# ------------------------------------------------------------------
shapes = []
x0 = win.index.min()
x1 = fc["week_end"].max()

for lvl in compute_levels(weekly):
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x0, x1=x1, y0=lvl["price"], y1=lvl["price"],
        line=dict(color="rgba(241,196,15,0.75)", width=1.4, dash="dot"),
    ))
    annotations.append(dict(
        x=x1, y=lvl["price"], xref="x", yref="y",
        text=f"🟨{lvl['kind']} {lvl['price']:.2f}", showarrow=False,
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

# divider where actual data ends
divider_x = last_week_end + pd.Timedelta(days=3)
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
    title=dict(text=title, font=dict(size=13, color="#aab4c0"), x=0.01),
    margin=dict(t=50, r=110, b=40, l=50),
    xaxis=dict(rangeslider=dict(visible=False), gridcolor="#23242c", type="date"),
    yaxis=dict(gridcolor="#23242c", side="right", dtick=1, tick0=0, showgrid=True),
    shapes=shapes, annotations=annotations, showlegend=False,
)

fig.write_html(OUT_PATH, include_plotlyjs="cdn")
print(f"{len(vintages)} vintage(s), track record {hits}/{scored} hit")
print(f"Saved: {OUT_PATH}")
