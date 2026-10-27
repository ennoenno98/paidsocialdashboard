"""Metric layer. Hard rules (see config/metric_definitions.md):

* ER = engagements / reach (Instagram) or / video views (TikTok, ``er_basis='views'``). Never followers.
* engagements = likes + comments + saves + shares(reposts). Post follows are a separate column.
* Account-level ER is reported twice: mean of per-post ER and reach-weighted (sum eng / sum reach).
* Missing reach -> ER is NaN. All ERs are recomputed from raw columns; the sheet ER is only reconciled.
* Weekly and monthly are separate sources; weekly sums are labelled ``scope='weekly_rollup'``.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from src.ingest.labels import normalise_er
from src.ingest.xlsx import ACCOUNT_COLS

ENGAGEMENT_COMPONENTS = ["likes", "comments", "saves", "shares", "reposts"]
FLOW_METRICS = [
    "reach",
    "views",
    "follows",
    "unfollows",
    "net_follows",
    "new_followers",
    "boost_spend",
    "n_posts",
    "n_igs",
    "likes",
    "comments",
    "shares",
    "website_visits",
    "engagement",
    "link_clicks",
]
STOCK_METRICS = ["followers"]


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    den = pd.to_numeric(den, errors="coerce")
    return pd.to_numeric(num, errors="coerce") / den.where(den > 0)


# --------------------------------------------------------------------------------------
# per-post
# --------------------------------------------------------------------------------------
def add_post_metrics(posts: pd.DataFrame) -> pd.DataFrame:
    """Add engagements, er_basis, er_denominator, er, er_sheet_frac, er_diff_pp."""
    df = posts.copy()
    for c in ENGAGEMENT_COMPONENTS + ["reach", "views", "video_views", "er_sheet"]:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["engagements"] = df[ENGAGEMENT_COMPONENTS].sum(axis=1, min_count=1)
    is_tt = df["platform"].eq("tiktok")
    df["er_basis"] = np.where(is_tt, "views", "reach")
    tt_denom = df["video_views"].fillna(df["views"])
    df["er_denominator"] = np.where(is_tt, tt_denom, df["reach"])
    df["er"] = _safe_div(df["engagements"], df["er_denominator"])
    df["er_sheet_frac"] = df["er_sheet"].map(normalise_er)
    df["er_diff_pp"] = (df["er"] - df["er_sheet_frac"]) * 100
    return df


def account_er(posts_m: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Account-level ER: mean of per-post ER *and* reach-weighted, both labelled."""
    by = by or ACCOUNT_COLS + ["year", "cw"]
    if posts_m.empty:
        return pd.DataFrame(
            columns=by
            + [
                "n_posts",
                "n_posts_with_er",
                "er_mean",
                "er_weighted",
                "sum_reach",
                "sum_engagements",
                "er_basis",
            ]
        )
    df = posts_m.copy()
    has = df["er"].notna()
    df["_eng_ok"] = df["engagements"].where(has)
    df["_den_ok"] = df["er_denominator"].where(has)
    g = df.groupby(by, dropna=False)
    out = g.agg(
        n_posts=("post_name", "size"),
        n_posts_with_er=("er", "count"),
        er_mean=("er", "mean"),
        sum_engagements=("_eng_ok", "sum"),
        sum_denominator=("_den_ok", "sum"),
        sum_reach=("reach", lambda s: s.sum(min_count=1)),
        er_basis=("er_basis", "first"),
    ).reset_index()
    out["er_weighted"] = _safe_div(out["sum_engagements"], out["sum_denominator"])
    out.loc[out["n_posts_with_er"].eq(0), ["er_mean", "er_weighted"]] = np.nan
    return out


def er_reconciliation(posts_m: pd.DataFrame, threshold_pp: float = 0.5) -> pd.DataFrame:
    """Per-post rows where the sheet's own ER differs from the recomputed ER by > threshold (pp)."""
    cols = ACCOUNT_COLS + [
        "year",
        "cw",
        "slot",
        "post_name",
        "reach",
        "er_denominator",
        "engagements",
        "er",
        "er_sheet_frac",
        "er_diff_pp",
        "src_rows",
    ]
    if posts_m.empty:
        return pd.DataFrame(columns=cols)
    both = posts_m["er"].notna() & posts_m["er_sheet_frac"].notna()
    hit = posts_m[both & (posts_m["er_diff_pp"].abs() > threshold_pp)]
    return hit[cols].sort_values("er_diff_pp", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def weekly_er_vs_sheet(
    weekly_wide: pd.DataFrame, acc_er_week: pd.DataFrame, threshold_pp: float = 0.5
) -> pd.DataFrame:
    """Weekly block ER row (sheet) vs mean per-post ER from Post by Post for the same account/CW."""
    cols = ACCOUNT_COLS + ["year", "cw", "er_sheet_frac", "er_mean_posts", "er_weighted_posts", "diff_pp"]
    if weekly_wide.empty or acc_er_week.empty or "er_sheet" not in weekly_wide.columns:
        return pd.DataFrame(columns=cols)
    w = weekly_wide[weekly_wide["kind"].eq("organic") & weekly_wide["period_type"].eq("cw")]
    w = w[ACCOUNT_COLS + ["year", "period", "er_sheet"]].rename(columns={"period": "cw"})
    w["er_sheet_frac"] = w["er_sheet"].map(normalise_er)
    m = w.merge(
        acc_er_week[ACCOUNT_COLS + ["year", "cw", "er_mean", "er_weighted"]], on=ACCOUNT_COLS + ["year", "cw"]
    )
    m = m.rename(columns={"er_mean": "er_mean_posts", "er_weighted": "er_weighted_posts"})
    m["diff_pp"] = (m["er_mean_posts"] - m["er_sheet_frac"]) * 100
    m = m[m["er_sheet_frac"].notna() & m["er_mean_posts"].notna() & (m["diff_pp"].abs() > threshold_pp)]
    return m[cols].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# boosting (paid)
# --------------------------------------------------------------------------------------
BOOST_COLS = ACCOUNT_COLS[:3] + [
    "account",
    "year",
    "period_type",
    "period",
    "boost_spend",
    "boosted_reach",
    "boosted_views",
    "new_followers_boosted",
    "organic_reach",
    "organic_net_follows",
    "cost_per_new_follower",
    "cost_per_net_follow",
    "cpm_boosted",
    "boosted_reach_share",
    "spend_source",
]


def boosting_metrics(wide: pd.DataFrame) -> pd.DataFrame:
    """Join boosting blocks to organic blocks of the same account/period and derive cost efficiency.

    * cost_per_new_follower: spend / new followers *of the boosted posts* (boosting block)
    * cost_per_net_follow: spend / organic block net follows (account-level, incl. organic effect)
    * cpm_boosted = spend / boosted reach * 1000; boosted_reach_share = boosted / (organic + boosted)
    """
    if wide.empty:
        return pd.DataFrame(columns=BOOST_COLS)
    key = ["brand", "platform", "market", "account", "year", "period_type", "period"]
    w = wide.copy()
    for c in ["boost_spend", "reach", "views", "new_followers", "net_follows", "follows"]:
        if c not in w.columns:
            w[c] = np.nan
    boost = w[w["kind"].eq("boosting")][
        key + ["boost_spend", "reach", "views", "new_followers", "follows"]
    ].rename(
        columns={
            "reach": "boosted_reach",
            "views": "boosted_views",
            "new_followers": "new_followers_boosted",
            "follows": "follows_boosted",
        }
    )
    boost["new_followers_boosted"] = boost["new_followers_boosted"].fillna(boost["follows_boosted"])
    boost["spend_source"] = "boosting_block"
    org = w[w["kind"].eq("organic")][key + ["reach", "net_follows", "boost_spend"]].rename(
        columns={
            "reach": "organic_reach",
            "net_follows": "organic_net_follows",
            "boost_spend": "boost_spend_org",
        }
    )
    m = boost.merge(org, on=key, how="outer")
    # monthly sheet carries spend inside the organic block ("Boosting Spent" / "Ad cost")
    no_block = m["boost_spend"].isna() & m["boost_spend_org"].notna()
    m.loc[no_block, "boost_spend"] = m.loc[no_block, "boost_spend_org"]
    m.loc[no_block, "spend_source"] = "organic_block_spend_row"
    m = m[m["boost_spend"].notna() | m["boosted_reach"].notna()]
    m["cost_per_new_follower"] = _safe_div(m["boost_spend"], m["new_followers_boosted"])
    m["cost_per_net_follow"] = _safe_div(m["boost_spend"], m["organic_net_follows"])
    m["cpm_boosted"] = _safe_div(m["boost_spend"], m["boosted_reach"]) * 1000
    tot = m["organic_reach"].fillna(0) + m["boosted_reach"].fillna(0)
    m["boosted_reach_share"] = _safe_div(m["boosted_reach"], tot)
    m.loc[m["boosted_reach"].isna(), "boosted_reach_share"] = np.nan
    return m[BOOST_COLS].sort_values(key).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# weekly rollup (explicitly labelled) and spend reconciliation
# --------------------------------------------------------------------------------------
def iso_week_month(year: int, cw: int) -> int:
    """Month of the ISO week's Thursday (ISO convention)."""
    return dt.date.fromisocalendar(int(year), int(cw), 4).month


def weekly_rollup(weekly_wide: pd.DataFrame) -> pd.DataFrame:
    """Sum weekly flows to months. Output is labelled scope='weekly_rollup'; never compare silently."""
    if weekly_wide.empty:
        return pd.DataFrame(columns=ACCOUNT_COLS + ["year", "month", "scope"])
    w = weekly_wide[weekly_wide["period_type"].eq("cw")].copy()
    w["month"] = [iso_week_month(y, c) for y, c in zip(w["year"], w["period"], strict=True)]
    flows = [c for c in FLOW_METRICS if c in w.columns]
    stocks = [c for c in STOCK_METRICS if c in w.columns]
    g = w.sort_values("period").groupby(ACCOUNT_COLS + ["year", "month"], dropna=False)
    agg: dict[str, tuple[str, str]] = {c: (c, "sum") for c in flows}
    agg.update({c: (c, "last") for c in stocks})
    agg["n_weeks"] = ("period", "nunique")
    out = g.agg(**agg).reset_index()
    for c in flows:
        allna = g[c].apply(lambda s: s.isna().all()).reset_index(drop=True)
        out.loc[allna.values, c] = np.nan
    out["scope"] = "weekly_rollup"
    return out


def reconcile_boost_spend(
    monthly_wide: pd.DataFrame, susy: pd.DataFrame, budget: pd.DataFrame
) -> pd.DataFrame:
    """Monthly-sheet boost_spend vs Boosting Susy vs budget, per account/month. Shows deltas, picks nothing."""
    key = ["brand", "platform", "market", "account", "year", "month"]
    cols = key + [
        "boost_spend_monthly_sheet",
        "boost_spend_susy",
        "delta_susy_minus_sheet",
        "boost_budget",
        "agree",
    ]
    ms = pd.DataFrame(columns=key + ["boost_spend_monthly_sheet"])
    if not monthly_wide.empty and "boost_spend" in monthly_wide.columns:
        ms = monthly_wide[monthly_wide["period_type"].eq("month")].copy()
        ms = ms.groupby(["brand", "platform", "market", "account", "year", "period"], as_index=False)[
            "boost_spend"
        ].sum(min_count=1)
        ms = ms.rename(columns={"period": "month", "boost_spend": "boost_spend_monthly_sheet"})
    s = (
        susy[key + ["boost_spend_susy"]]
        if not susy.empty
        else pd.DataFrame(columns=key + ["boost_spend_susy"])
    )
    m = ms.merge(s, on=key, how="outer")
    if not budget.empty:
        b = budget.groupby(["account", "year"], as_index=False)["boost_budget"].first()
        m = m.merge(b, on=["account", "year"], how="left")
    else:
        m["boost_budget"] = np.nan
    m = m[m["boost_spend_monthly_sheet"].notna() | m["boost_spend_susy"].notna()]
    m["delta_susy_minus_sheet"] = m["boost_spend_susy"] - m["boost_spend_monthly_sheet"]
    m["agree"] = m["delta_susy_minus_sheet"].abs().lt(0.01)
    m.loc[m["boost_spend_monthly_sheet"].isna() | m["boost_spend_susy"].isna(), "agree"] = False
    return m[cols].sort_values(key).reset_index(drop=True)


def latest_period(wide: pd.DataFrame, period_type: str) -> tuple[int, int] | None:
    """(year, period) of the latest period that has any numeric data."""
    if wide.empty:
        return None
    w = wide[wide["period_type"].eq(period_type)]
    num = w.select_dtypes("number").drop(columns=["year", "period"], errors="ignore")
    w = w[num.notna().any(axis=1)]
    if w.empty:
        return None
    r = w.sort_values(["year", "period"]).iloc[-1]
    return int(r["year"]), int(r["period"])
