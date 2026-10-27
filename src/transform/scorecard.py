"""Overview scorecard: organic (follower growth, views) per brand x platform and influencer KPIs (spend, ROAS,
CPM) per brand with breakdowns by goal (Performance vs Brand/awareness), tier and industry (category).

Period handling: a scorecard period is a ``(start, end)`` date pair. Organic Instagram comes from the daily API
frame (``new_followers`` only exists for the last 30 days, so follower growth is labelled accordingly); TikTok
organic comes from the monthly sheet (months whose first day falls inside the period). Influencer rows are Klar
``influencer_flex`` rows (per brand) selected by ``posting_date``; affiliates (platform == Affiliate) are excluded.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from src.transform.metrics import _safe_div

GOAL_MAP = {
    "performance": "Performance",
    "performace": "Performance",
    "brand": "Brand (awareness)",
    "awareness": "Brand (awareness)",
}
TIER_ORDER = ["Nano", "Micro", "Mid", "Macro", "Mega", "Unknown"]


def normalise_goal(v: object) -> str:
    if not isinstance(v, str) or not v.strip():
        return "Unknown"
    return GOAL_MAP.get(v.strip().lower(), v.strip())


def tier_from_followers(followers: object) -> str | None:
    """Fallback tier when the worksheet carries none: <25k Micro, 25-100k Mid, 100-500k Macro, >=500k Mega."""
    try:
        f = float(followers)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    if f < 25_000:
        return "Micro"
    if f < 100_000:
        return "Mid"
    if f < 500_000:
        return "Macro"
    return "Mega"


def period_bounds(kind: str, today: dt.date | None = None) -> tuple[dt.date, dt.date, str]:
    """Named period -> (start, end, label). end is inclusive."""
    today = today or dt.date.today()
    if kind == "last_30d":
        return today - dt.timedelta(days=30), today - dt.timedelta(days=1), "last 30 days"
    if kind == "last_90d":
        return today - dt.timedelta(days=90), today - dt.timedelta(days=1), "last 90 days"
    if kind == "last_month":
        first_this = today.replace(day=1)
        end = first_this - dt.timedelta(days=1)
        return end.replace(day=1), end, f"{end:%b %Y}"
    if kind == "this_quarter":
        q = (today.month - 1) // 3
        start = dt.date(today.year, 3 * q + 1, 1)
        return start, today - dt.timedelta(days=1), f"Q{q + 1} {today.year} to date"
    if kind == "last_quarter":
        q = (today.month - 1) // 3
        start = dt.date(today.year, 3 * q + 1, 1)
        end = start - dt.timedelta(days=1)
        qs = dt.date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
        return qs, end, f"Q{(end.month - 1) // 3 + 1} {end.year}"
    if kind == "ytd":
        return dt.date(today.year, 1, 1), today - dt.timedelta(days=1), f"{today.year} YTD"
    if kind == "last_12m":
        return today - dt.timedelta(days=365), today - dt.timedelta(days=1), "last 12 months"
    raise ValueError(kind)


# --------------------------------------------------------------------------------------
# organic
# --------------------------------------------------------------------------------------
ORGANIC_COLS = [
    "brand",
    "platform",
    "account",
    "followers",
    "new_followers",
    "new_followers_days",
    "follower_growth_pct",
    "views",
    "reach",
    "n_posts",
    "source",
]


def organic_kpis(
    ig_daily: pd.DataFrame, monthly_wide: pd.DataFrame, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """Per account: follower growth and views in the period. Instagram from the daily API frame (new followers
    exist for the last 30 days only), TikTok from the sheet's monthly organic blocks."""
    out: list[dict[str, object]] = []
    if not ig_daily.empty:
        d = ig_daily.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date
        sel = d[(d["date"] >= start) & (d["date"] <= end)]
        latest_f = d.dropna(subset=["followers"]).sort_values("date").groupby("account")["followers"].last()
        for acc, g in sel.groupby("account"):
            nf = g["new_followers"]
            followers = latest_f.get(acc, np.nan)
            new_f = float(nf.sum()) if nf.notna().any() else np.nan
            out.append(
                {
                    "brand": g["brand"].iloc[0],
                    "platform": "instagram",
                    "account": acc,
                    "followers": followers,
                    "new_followers": new_f,
                    "new_followers_days": int(nf.notna().sum()),
                    "follower_growth_pct": new_f / (followers - new_f)
                    if followers == followers and followers > new_f
                    else np.nan,
                    "views": float(g["views"].sum()) if g["views"].notna().any() else np.nan,
                    "reach": float(g["reach"].sum()) if g["reach"].notna().any() else np.nan,
                    "n_posts": np.nan,
                    "source": "api",
                }
            )
    if not monthly_wide.empty:
        m = monthly_wide[monthly_wide["period_type"].eq("month") & monthly_wide["kind"].eq("organic")].copy()
        m["first_day"] = [dt.date(int(y), int(p), 1) for y, p in zip(m["year"], m["period"], strict=True)]
        sel = m[(m["first_day"] >= start.replace(day=1)) & (m["first_day"] <= end)]
        sel = sel[sel["platform"].eq("tiktok")]
        for acc, g in sel.groupby("account"):
            g = g.sort_values("first_day")
            followers = pd.to_numeric(g["followers"], errors="coerce").dropna()
            net = pd.to_numeric(g.get("net_follows"), errors="coerce")
            new_f = float(net.sum()) if net.notna().any() else np.nan
            last_f = float(followers.iloc[-1]) if len(followers) else np.nan
            out.append(
                {
                    "brand": g["brand"].iloc[0],
                    "platform": "tiktok",
                    "account": acc,
                    "followers": last_f,
                    "new_followers": new_f,
                    "new_followers_days": int(g["first_day"].nunique()),
                    "follower_growth_pct": new_f / (last_f - new_f)
                    if last_f == last_f and last_f > new_f
                    else np.nan,
                    "views": float(pd.to_numeric(g["views"], errors="coerce").sum())
                    if "views" in g
                    else np.nan,
                    "reach": float(pd.to_numeric(g["reach"], errors="coerce").sum())
                    if "reach" in g
                    else np.nan,
                    "n_posts": float(pd.to_numeric(g.get("n_posts"), errors="coerce").sum()),
                    "source": "sheet",
                }
            )
    return pd.DataFrame(out, columns=ORGANIC_COLS)


# --------------------------------------------------------------------------------------
# influencer
# --------------------------------------------------------------------------------------
INF_COLS = [
    "brand",
    "costs",
    "orders",
    "net_revenue",
    "new_customers",
    "roas",
    "cac",
    "n_creators",
    "n_campaigns",
    "reach",
    "costs_with_reach",
    "reach_coverage",
    "cpm",
    "costs_performance",
    "costs_awareness",
    "roas_performance",
    "roas_awareness",
    "share_performance",
]
BREAKDOWN_COLS = [
    "brand",
    "dimension",
    "value",
    "costs",
    "share",
    "orders",
    "net_revenue",
    "roas",
    "n_creators",
    "reach",
    "cpm",
]


def _prep(
    klar: pd.DataFrame, attrs: pd.DataFrame, reach_rows: pd.DataFrame, start: dt.date, end: dt.date
) -> pd.DataFrame:
    k = klar.copy()
    if k.empty:
        return k
    k["posting_date"] = pd.to_datetime(k["posting_date"], errors="coerce")
    k = k[(k["posting_date"].dt.date >= start) & (k["posting_date"].dt.date <= end)]
    k = k[~k["platform"].astype("string").str.lower().eq("affiliate")]
    if "brand" not in k.columns:
        k["brand"] = "unknown"
    k["handle"] = k["influencer_name"].astype("string").str.strip().str.lstrip("@").str.lower()
    if not attrs.empty:
        a = attrs.drop_duplicates("handle").set_index("handle")
        alias = a["alias"].dropna().to_dict() if "alias" in a.columns else {}
        k["handle"] = k["handle"].map(lambda h: alias.get(h, h))
        for c in ("tier", "category_ws", "goal_ws", "followers_ws"):
            if c in a.columns:
                k[c] = k["handle"].map(a[c])
    k["goal"] = [
        normalise_goal(g) if normalise_goal(g) != "Unknown" else normalise_goal(gw)
        for g, gw in zip(
            k["campaign_name"], k.get("goal_ws", pd.Series(index=k.index, dtype=object)), strict=True
        )
    ]
    k["industry"] = k["category"].where(k["category"].notna(), k.get("category_ws")).fillna("Unknown")
    k["tier"] = k.get("tier", pd.Series(index=k.index, dtype=object)).fillna("Unknown")
    # reach per campaign: Klar reach, else sheet/worksheet reach on (handle, posting_date), else by handle+month
    k["reach_c"] = pd.to_numeric(k["reach"], errors="coerce").where(lambda s: s > 0)
    if not reach_rows.empty:
        r = reach_rows.dropna(subset=["reach"]).copy()
        r["date"] = pd.to_datetime(r["date"], errors="coerce")
        exact = r.dropna(subset=["date"]).groupby(["handle", "date"])["reach"].sum()
        key = list(zip(k["handle"], k["posting_date"], strict=True))
        k["reach_c"] = k["reach_c"].where(
            k["reach_c"].notna(), pd.Series([exact.get(x, np.nan) for x in key], index=k.index)
        )
        r["ym"] = r["date"].dt.to_period("M")
        monthly = r.dropna(subset=["ym"]).groupby(["handle", "ym"])["reach"].sum()
        key_m = list(zip(k["handle"], k["posting_date"].dt.to_period("M"), strict=True))
        k["reach_c"] = k["reach_c"].where(
            k["reach_c"].notna(), pd.Series([monthly.get(x, np.nan) for x in key_m], index=k.index)
        )
    return k


def influencer_kpis(
    klar: pd.DataFrame, attrs: pd.DataFrame, reach_rows: pd.DataFrame, start: dt.date, end: dt.date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-brand KPIs, breakdowns by goal / tier / industry) for Klar rows posted in the period."""
    k = _prep(klar, attrs, reach_rows, start, end)
    if k.empty:
        return pd.DataFrame(columns=INF_COLS), pd.DataFrame(columns=BREAKDOWN_COLS)

    def _agg(g: pd.DataFrame) -> dict[str, object]:
        with_reach = g[g["reach_c"].notna()]
        costs = float(g["costs"].sum())
        perf = g[g["goal"].eq("Performance")]
        aware = g[g["goal"].eq("Brand (awareness)")]
        return {
            "costs": costs,
            "orders": float(g["orders"].sum()),
            "net_revenue": float(g["net_revenue"].sum()),
            "new_customers": float(g["new_customers"].sum()),
            "roas": _safe_div(pd.Series([g["net_revenue"].sum()]), pd.Series([costs])).iloc[0],
            "cac": _safe_div(pd.Series([costs]), pd.Series([g["new_customers"].sum()])).iloc[0],
            "n_creators": int(g["handle"].nunique()),
            "n_campaigns": int(len(g)),
            "reach": float(with_reach["reach_c"].sum()) if len(with_reach) else np.nan,
            "costs_with_reach": float(with_reach["costs"].sum()),
            "reach_coverage": float(with_reach["costs"].sum()) / costs if costs else np.nan,
            "cpm": (float(with_reach["costs"].sum()) / float(with_reach["reach_c"].sum()) * 1000)
            if len(with_reach) and with_reach["reach_c"].sum() > 0
            else np.nan,
            "costs_performance": float(perf["costs"].sum()),
            "costs_awareness": float(aware["costs"].sum()),
            "roas_performance": _safe_div(
                pd.Series([perf["net_revenue"].sum()]), pd.Series([perf["costs"].sum()])
            ).iloc[0],
            "roas_awareness": _safe_div(
                pd.Series([aware["net_revenue"].sum()]), pd.Series([aware["costs"].sum()])
            ).iloc[0],
            "share_performance": float(perf["costs"].sum()) / costs if costs else np.nan,
        }

    per_brand = pd.DataFrame([{"brand": b, **_agg(g)} for b, g in k.groupby("brand")], columns=INF_COLS)
    rows = []
    for dim in ("goal", "tier", "industry"):
        for (b, v), g in k.groupby(["brand", dim]):
            tot = float(k[k["brand"].eq(b)]["costs"].sum())
            wr = g[g["reach_c"].notna()]
            rows.append(
                {
                    "brand": b,
                    "dimension": dim,
                    "value": v,
                    "costs": float(g["costs"].sum()),
                    "share": float(g["costs"].sum()) / tot if tot else np.nan,
                    "orders": float(g["orders"].sum()),
                    "net_revenue": float(g["net_revenue"].sum()),
                    "roas": _safe_div(
                        pd.Series([g["net_revenue"].sum()]), pd.Series([g["costs"].sum()])
                    ).iloc[0],
                    "n_creators": int(g["handle"].nunique()),
                    "reach": float(wr["reach_c"].sum()) if len(wr) else np.nan,
                    "cpm": (float(wr["costs"].sum()) / float(wr["reach_c"].sum()) * 1000)
                    if len(wr) and wr["reach_c"].sum() > 0
                    else np.nan,
                }
            )
    breakdown = pd.DataFrame(rows, columns=BREAKDOWN_COLS)
    return per_brand, breakdown
