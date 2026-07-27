"""
Shared S/R level computation, used by run.py (PLOT.html) and
forecast_plot.py (FORECAST.html) so both charts show identical levels.

Cluster weekly Highs (resistance candidates) and weekly Lows (support
candidates) within TOLERANCE into levels, keep levels whose touches span
more than MIN_WEEK_SPAN weeks, then merge R+S levels closer than
MERGE_DIST (touch-weighted price; mixed groups labeled "R/S").
"""

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
