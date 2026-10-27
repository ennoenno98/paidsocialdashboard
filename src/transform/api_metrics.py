"""Period aggregates from API data (Windsor): weekly (ISO) and monthly frames per own account.

Scope labels: everything here is ``scope='api'``. Reach per period is the **sum of daily unique reach**
(``reach_daily_sum``), which overstates true period reach; it is labelled as such and never mixed with the
sheet's weekly reach figure. ER per period = mean of per-post ER (reach basis) over posts published in the
period, plus the reach-weighted variant, exactly as for the sheet posts.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from src.transform.metrics import _safe_div, account_er

KEY = ["account", "brand", "platform", "market"]
FLOWS = [
    "reach",
    "views",
    "likes",
    "comments",
    "saves",
    "shares",
    "total_interactions",
    "accounts_engaged",
    "new_followers",
]
BOOST_FLOWS = ["spend", "reach", "impressions", "clicks", "post_engagement", "link_clicks", "video_views"]


def _period_cols(dates: pd.Series, period_type: str) -> tuple[pd.Series, pd.Series]:
    d = pd.to_datetime(dates)
    if period_type == "cw":
        iso = d.dt.isocalendar()
        return iso["year"].astype(int), iso["week"].astype(int)
    return d.dt.year.astype(int), d.dt.month.astype(int)


def organic_periods(daily: pd.DataFrame, posts_m: pd.DataFrame, period_type: str) -> pd.DataFrame:
    """Daily account insights + per-post ER -> one row per account/period."""
    cols = KEY + [
        "year",
        "period_type",
        "period",
        "n_days",
        "reach_daily_sum",
        "views",
        "likes",
        "comments",
        "saves",
        "shares",
        "total_interactions",
        "accounts_engaged",
        "new_followers",
        "new_followers_days",
        "followers",
        "n_posts",
        "n_posts_with_er",
        "er_mean",
        "er_weighted",
        "er_basis",
        "scope",
    ]
    if daily.empty:
        return pd.DataFrame(columns=cols)
    d = daily.copy()
    d["year"], d["period"] = _period_cols(d["date"], period_type)
    d = d.sort_values("date")
    g = d.groupby(KEY + ["year", "period"], dropna=False)
    out = g.agg(
        n_days=("date", "nunique"),
        reach_daily_sum=("reach", lambda s: s.sum(min_count=1)),
        views=("views", lambda s: s.sum(min_count=1)),
        likes=("likes", lambda s: s.sum(min_count=1)),
        comments=("comments", lambda s: s.sum(min_count=1)),
        saves=("saves", lambda s: s.sum(min_count=1)),
        shares=("shares", lambda s: s.sum(min_count=1)),
        total_interactions=("total_interactions", lambda s: s.sum(min_count=1)),
        accounts_engaged=("accounts_engaged", lambda s: s.sum(min_count=1)),
        new_followers=("new_followers", lambda s: s.sum(min_count=1)),
        new_followers_days=("new_followers", "count"),
        followers=("followers", "last"),
    ).reset_index()
    # posts published in the period -> ER (reach basis) mean + weighted
    if not posts_m.empty:
        p = posts_m.copy()
        p["year"], p["period"] = _period_cols(p["timestamp"], period_type)
        p["post_name"] = p["media_id"]
        er = account_er(p, by=KEY + ["year", "period"])
        out = out.merge(
            er[KEY + ["year", "period", "n_posts", "n_posts_with_er", "er_mean", "er_weighted", "er_basis"]],
            on=KEY + ["year", "period"],
            how="left",
        )
        out["n_posts"] = out["n_posts"].fillna(0).astype(int)
    else:
        out["n_posts"], out["n_posts_with_er"], out["er_mean"], out["er_weighted"], out["er_basis"] = (
            0,
            0,
            np.nan,
            np.nan,
            "reach",
        )
    out["period_type"] = period_type
    out["scope"] = "api"
    return out[cols].sort_values(KEY + ["year", "period"]).reset_index(drop=True)


def boosted_periods(boosted: pd.DataFrame, period_type: str) -> pd.DataFrame:
    """Meta boosted-post rows -> spend/reach per account/period (unmapped rows aggregate under market NaN)."""
    cols = KEY + [
        "year",
        "period_type",
        "period",
        "boost_spend",
        "boosted_reach_daily_sum",
        "boosted_impressions",
        "boosted_clicks",
        "boosted_post_engagement",
        "boosted_link_clicks",
        "boosted_video_views",
        "n_boosted_posts",
        "n_unmapped_rows",
        "scope",
    ]
    if boosted.empty:
        return pd.DataFrame(columns=cols)
    b = boosted.copy()
    b["year"], b["period"] = _period_cols(b["date"], period_type)
    g = b.groupby(KEY + ["year", "period"], dropna=False)
    out = g.agg(
        boost_spend=("spend", "sum"),
        boosted_reach_daily_sum=("reach", lambda s: s.sum(min_count=1)),
        boosted_impressions=("impressions", "sum"),
        boosted_clicks=("clicks", "sum"),
        boosted_post_engagement=("post_engagement", lambda s: s.sum(min_count=1)),
        boosted_link_clicks=("link_clicks", lambda s: s.sum(min_count=1)),
        boosted_video_views=("video_views", lambda s: s.sum(min_count=1)),
        n_boosted_posts=("shortcode", "nunique"),
        n_unmapped_rows=("mapped", lambda s: int((~s).sum())),
    ).reset_index()
    out["period_type"] = period_type
    out["scope"] = "api"
    return out[cols].sort_values(KEY + ["year", "period"]).reset_index(drop=True)


def combined_periods(organic: pd.DataFrame, boosted: pd.DataFrame) -> pd.DataFrame:
    """Organic + boosted per account/period with derived cost metrics (API scope)."""
    if organic.empty and boosted.empty:
        return pd.DataFrame(columns=KEY + ["year", "period_type", "period"])
    on = KEY + ["year", "period_type", "period"]
    m = (
        organic.merge(boosted.drop(columns=["scope"]), on=on, how="outer")
        if not boosted.empty
        else organic.copy()
    )
    for c in ["boost_spend", "boosted_reach_daily_sum", "new_followers", "reach_daily_sum", "n_posts"]:
        if c not in m.columns:
            m[c] = np.nan
    m["cpm_boosted"] = _safe_div(m["boost_spend"], m["boosted_reach_daily_sum"]) * 1000
    m["cost_per_new_follower"] = _safe_div(m["boost_spend"], m["new_followers"])
    tot = m["reach_daily_sum"].fillna(0) + m["boosted_reach_daily_sum"].fillna(0)
    m["boosted_reach_share"] = _safe_div(m["boosted_reach_daily_sum"], tot)
    m["scope"] = "api"
    return m.sort_values(on).reset_index(drop=True)


def latest_complete_period(
    frame: pd.DataFrame, period_type: str, today: dt.date | None = None
) -> tuple[int, int] | None:
    """Latest period that has ended before today (so KPIs are not read off a partial week/month)."""
    if frame.empty:
        return None
    today = today or dt.date.today()
    if period_type == "cw":
        iso = (today - dt.timedelta(days=7)).isocalendar()
        y, p = iso[0], iso[1]
    else:
        first = today.replace(day=1) - dt.timedelta(days=1)
        y, p = first.year, first.month
    f = frame[(frame["year"] < y) | ((frame["year"] == y) & (frame["period"] <= p))]
    if f.empty:
        return None
    r = f.sort_values(["year", "period"]).iloc[-1]
    return int(r["year"]), int(r["period"])


def spend_recon_with_meta(spend_recon: pd.DataFrame, boosted_monthly: pd.DataFrame) -> pd.DataFrame:
    """Add Meta Ads boosted spend (API) next to the monthly sheet and Boosting Susy figures."""
    if boosted_monthly.empty:
        out = spend_recon.copy()
        out["boost_spend_meta"] = np.nan
        out["delta_meta_minus_sheet"] = np.nan
        return out
    bm = boosted_monthly[boosted_monthly["account"].notna()][
        ["account", "year", "period", "boost_spend"]
    ].rename(columns={"period": "month", "boost_spend": "boost_spend_meta"})
    keys = ["account", "year", "month"]
    out = spend_recon.merge(bm, on=keys, how="outer")
    for c in ("brand", "platform", "market"):
        missing = out[c].isna()
        if missing.any():
            parts = out.loc[missing, "account"].astype("string").str.split("/", expand=True)
            out.loc[missing, c] = parts[{"brand": 0, "platform": 1, "market": 2}[c]]
    out["delta_meta_minus_sheet"] = out["boost_spend_meta"] - out["boost_spend_monthly_sheet"]
    return out.sort_values(keys).reset_index(drop=True)
