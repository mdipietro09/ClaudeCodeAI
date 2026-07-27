"""
IT000553414 — Weekly candlestick chart with filtered, full-width Support/Resistance
levels + a full price-level (100, 101, 102...) reference grid on the y-axis.

Requires: pandas, plotly
"""

import pandas as pd
import plotly.graph_objects as go

# ------------------------------------------------------------------
# 1) LOAD & CLEAN
# ------------------------------------------------------------------
CSV_PATH = "data.csv"

df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
df.columns = [c.strip() for c in df.columns]

df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
for col in ["Price", "Open", "High", "Low"]:
    df[col] = df[col].astype(str).str.replace(",", "").astype(float)

df = df.sort_values("Date").set_index("Date")

# ------------------------------------------------------------------
# 2) RESAMPLE TO WEEKLY OHLC (week ending Friday)
# ------------------------------------------------------------------
weekly = df.resample("W-FRI").agg(
    Open=("Open", "first"),
    High=("High", "max"),
    Low=("Low", "min"),
    Close=("Price", "last"),
).dropna()

weekly = weekly.reset_index().rename(columns={"Date": "WeekEnd"})
weekly["week_idx"] = weekly.index  # 0,1,2... sequential week number

# ------------------------------------------------------------------
# 3) BUILD CANDLESTICK
# ------------------------------------------------------------------
candle = go.Candlestick(
    x=weekly["WeekEnd"],
    open=weekly["Open"],
    high=weekly["High"],
    low=weekly["Low"],
    close=weekly["Close"],
    name="IT000553414 (weekly)",
    increasing=dict(line=dict(color="#2ecc71")),
    decreasing=dict(line=dict(color="#e74c3c")),
)

fig = go.Figure(data=[candle])

# ------------------------------------------------------------------
# 4) FULL-CHART SUPPORT / RESISTANCE LINES — FILTERED
#    Cluster weekly Highs (resistance candidates) and weekly Lows (support
#    candidates) that sit within TOLERANCE of each other into one "level".
#    Keep a level ONLY if its earliest and latest touch are MORE THAN
#    MIN_WEEK_SPAN weeks apart (i.e. it's a level the market keeps coming
#    back to over time — not a one-off wick).
# ------------------------------------------------------------------
x_start = weekly["WeekEnd"].min()
x_end = weekly["WeekEnd"].max()

# Clustering/merging logic lives in sr_levels.py, shared with
# forecast_plot.py so both charts show identical levels.
from sr_levels import MERGE_DIST, compute_levels

merged_levels = compute_levels(weekly)

print(f"\nMerged into {len(merged_levels)} final level(s) (merge dist < {MERGE_DIST}):")
for lvl in sorted(merged_levels, key=lambda l: -l["price"]):
    print(f"  🟨{lvl['kind']} {lvl['price']:.2f}  touches={lvl['touches']}  span={lvl['span']}wk")

shapes = []
annotations = []

for lvl in merged_levels:
    shapes.append(dict(
        type="line", xref="x", yref="y",
        x0=x_start, x1=x_end,
        y0=lvl["price"], y1=lvl["price"],
        line=dict(color="rgba(241,196,15,0.75)", width=1.4, dash="dot"),
    ))
    annotations.append(dict(
        x=x_end, y=lvl["price"], xref="x", yref="y",
        text=f"🟨{lvl['kind']} {lvl['price']:.2f}", showarrow=False,
        xanchor="left", font=dict(color="#f1c40f", size=11),
    ))

# ------------------------------------------------------------------
# 4c) ABSOLUTE MAX / MIN OF THE WHOLE DATASET
#     Green = all-time high (of the full period), Red = all-time low.
# ------------------------------------------------------------------
abs_high = df["High"].max()
abs_low = df["Low"].min()

shapes.append(dict(
    type="line", xref="x", yref="y",
    x0=x_start, x1=x_end,
    y0=abs_high, y1=abs_high,
    line=dict(color="#2ecc71", width=2, dash="solid"),
))
annotations.append(dict(
    x=x_end, y=abs_high, xref="x", yref="y",
    text=f"🟩 ATH {abs_high:.2f}", showarrow=False,
    xanchor="left", font=dict(color="#2ecc71", size=12),
))

shapes.append(dict(
    type="line", xref="x", yref="y",
    x0=x_start, x1=x_end,
    y0=abs_low, y1=abs_low,
    line=dict(color="#e74c3c", width=2, dash="solid"),
))
annotations.append(dict(
    x=x_end, y=abs_low, xref="x", yref="y",
    text=f"🟥 ATL {abs_low:.2f}", showarrow=False,
    xanchor="left", yanchor="top", font=dict(color="#e74c3c", size=12),
))

print(f"\nAbsolute high (ATH): {abs_high:.2f}")
print(f"Absolute low (ATL):  {abs_low:.2f}")

# ------------------------------------------------------------------
# 6) MACRO EVENT MARKERS
#    One marker per week where price broke a level, mapped to the real
#    macro catalyst (sourced from tradingeconomics.com/calendar + news).
#    Hover shows the event description + source.
#    Events are maintained in macro_events.xlsx (columns: date, icon,
#    text, source).
# ------------------------------------------------------------------
MACRO_EVENTS_PATH = "macro_events.xlsx"

macro_events = pd.read_excel(MACRO_EVENTS_PATH).to_dict("records")

event_df = weekly.set_index("WeekEnd")
marker_x, marker_y, marker_text, marker_icon = [], [], [], []

for ev in macro_events:
    d = pd.Timestamp(ev["date"])
    if d not in event_df.index:
        continue
    row = event_df.loc[d]
    marker_x.append(d)
    marker_y.append(row["High"] + 0.9)  # float marker just above the candle
    marker_icon.append(ev["icon"])
    marker_text.append(f"<b>{d.strftime('%d %b %Y')}</b><br>{ev['text']}<br>"
                        f"<i>Source: {ev['source']}</i>")

fig.add_trace(go.Scatter(
    x=marker_x, y=marker_y,
    mode="text",
    text=marker_icon,
    textfont=dict(size=20),
    hovertext=marker_text,
    hoverinfo="text",
    hoverlabel=dict(bgcolor="#1a1b22", font=dict(color="#eaeaea", size=12), align="left"),
    name="Macro events",
    showlegend=True,
))


# ------------------------------------------------------------------
# 7) FORECAST — NEXT 4 WEEKLY CANDLES (BLUE)
#     Scenario-weighted, anchored to the 23 Jul 2026 close (97.50).
#     Drivers: (1) ECB held at 2.25% on 23 Jul — a "hawkish-leaning hold",
#     with the 10 Sept projection meeting as the live hike risk;
#     (2) US-Iran: mediators floated a 10-day ceasefire proposal (21 Jul)
#     but US strikes continue and Houthis threaten a Saudi naval blockade;
#     (3) price sits BELOW every support level — no technical floor
#     until the 96.60 YTD low.
#     Forecast candles are maintained in forecast.xlsx (columns:
#     week_end, Open, High, Low, Close, icon, text, made_on,
#     anchor_close). Run `python3 update.py` after refreshing data.csv
#     to check whether the forecast is still valid.
# ------------------------------------------------------------------
last_date = weekly["WeekEnd"].max()
last_close = weekly["Close"].iloc[-1]

FORECAST_PATH = "forecast.xlsx"

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

# Blue forecast candles
fig.add_trace(go.Candlestick(
    x=fc_x, open=fc_open, high=fc_high, low=fc_low, close=fc_close,
    name="Forecast (4wk)",
    increasing=dict(line=dict(color="#5dade2"), fillcolor="rgba(93,173,226,0.30)"),
    decreasing=dict(line=dict(color="#2980b9"), fillcolor="rgba(41,128,185,0.80)"),
))

# Forecast direction icons
fig.add_trace(go.Scatter(
    x=fc_icon_x, y=fc_icon_y,
    mode="text", text=fc_icon, textfont=dict(size=20),
    hovertext=fc_icon_text, hoverinfo="text",
    hoverlabel=dict(bgcolor="#12283a", font=dict(color="#eaeaea", size=12), align="left"),
    name="Forecast drivers", showlegend=True,
))

# Divider marking where history ends and forecast begins
divider_x = last_date + pd.Timedelta(days=3)
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

# Extend S/R + ATH/ATL lines across the forecast window
for s in shapes:
    if s.get("yref") == "y" and s.get("x1") == x_end:
        s["x1"] = fc_x[-1]
for a in annotations:
    if a.get("yref") == "y" and a.get("x") == x_end:
        a["x"] = fc_x[-1]

# ------------------------------------------------------------------
# 7b) FLAT WHITE LINE AT PRICE = 100 (round-number psychological level)
# ------------------------------------------------------------------
shapes.append(dict(
    type="line", xref="x", yref="y",
    x0=x_start, x1=fc_x[-1],
    y0=100, y1=100,
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
    paper_bgcolor="#0e0f13",
    plot_bgcolor="#0e0f13",
    font=dict(color="#eaeaea"),
    margin=dict(t=40, r=90, b=40, l=50),
    xaxis=dict(
        rangeslider=dict(visible=True, bgcolor="#1a1b22"),
        gridcolor="#23242c",
        type="date",
    ),
    yaxis=dict(
        gridcolor="#23242c",
        side="right",
        dtick=1,          # gridline + label every whole price point: 96, 97, 98...
        tick0=0,
        showgrid=True,
    ),
    shapes=shapes,
    annotations=annotations,
    showlegend=False,
)

# ------------------------------------------------------------------
# 6) EXPORT
# ------------------------------------------------------------------
OUT_PATH = "PLOT.html"
fig.write_html(OUT_PATH, include_plotlyjs="cdn")
print(f"\nSaved: {OUT_PATH}")
