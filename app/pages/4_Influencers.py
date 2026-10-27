"""Page 4 — Influencers: one row per creator, CPM primary (never followers-based), ROAS, benchmark vs own boosted CPM."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (  # noqa: E402
    PALETTE,
    STATUS,
    apply_layout,
    fmt_eur,
    page_setup,
    quarter_filter,
    section,
    show_table,
    source_line,
)

b = page_setup("Influencers")
section("Creators on Instagram", "instagram")
source_line(
    f"Creator master = Klar influencer_flex ({b.status.get('klar')}), last 400 days: handle, deal type, category, code, "
    f"followers, costs, orders, revenue. Public post counts: Windsor instagram_public ({b.status.get('windsor')}).",
    f"Campaign master: Klar influencer Google Sheets ({b.status.get('klar_sheet')}); Influencer/Affiliate Name = handle.",
    "CPM = Klar costs (fixed + variable) / reach × 1000. reach_source: klar → Reach column of the Klar sheet → "
    "manual CSV → n/a. Never followers- or likes-based.",
)
inf = b.influencers.copy()
if inf.empty:
    st.info("No Klar rows / creators.")
    st.stop()

own = b.boost_weekly["cpm_boosted"].dropna()
bench = float(own.median()) if len(own) else float("nan")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Creators (Klar, period)", len(inf))
c2.metric("Klar costs", fmt_eur(inf["costs"].sum()))
c3.metric("Attributed net revenue", fmt_eur(inf["net_revenue"].sum()))
c4.metric(
    "Own boosted-post CPM (median, weekly)",
    fmt_eur(bench, 2),
    help="cost_per_boosted_reach from weekly Boosting blocks; benchmark for influencer CPM",
)

rank = st.radio("Rank by", ["CPM (asc, primary)", "ROAS (desc)"], horizontal=True)
inf = (
    inf.sort_values("cpm", na_position="last")
    if rank.startswith("CPM")
    else inf.sort_values("roas", ascending=False, na_position="last")
)
inf["flag"] = ""
inf.loc[(inf["costs"] > 0) & (inf["orders"].fillna(0) == 0), "flag"] += "⚠ cost, no orders "
inf.loc[inf["reach_source"].eq("n/a"), "flag"] += "⚠ no reach "
inf.loc[inf["creator_handle"].isna(), "flag"] += "⚠ not in Creators "
if "in_klar_sheet" in inf.columns:
    inf.loc[~inf["in_klar_sheet"].fillna(False).astype(bool), "flag"] += "⚠ not in Klar sheet "
inf["cpm_vs_own_boost"] = inf["cpm"] / bench if bench == bench and bench > 0 else float("nan")
show_cols = [
    "influencer_name",
    "creator_handle",
    "platform",
    "type_of_partnership",
    "category",
    "markets",
    "post_types",
    "n_campaigns",
    "n_campaigns_with_reach",
    "creator_followers",
    "creator_deal",
    "discount_codes",
    "costs",
    "orders",
    "net_revenue",
    "roas",
    "cac",
    "n_posting_dates",
    "avg_reach_per_post",
    "cpm",
    "cpm_vs_own_boost",
    "reach_source",
    "interactions_per_post",
    "posts_per_30d",
    "scannable",
    "match_method",
    "flag",
]
show_cols = [c for c in show_cols if c in inf.columns]


def _badge(v: object) -> str:
    return {
        "klar": f"background-color: {STATUS['good']}33",
        "klar_sheet": f"background-color: {STATUS['good']}33",
        "manual": f"background-color: {STATUS['warning']}33",
        "n/a": f"background-color: {STATUS['critical']}33",
    }.get(str(v), "")


view = inf[show_cols]
show_table(
    view,
    eur_cols=["costs", "net_revenue", "cac", "cpm"],
    num_cols=[
        "creator_followers",
        "orders",
        "n_campaigns",
        "n_campaigns_with_reach",
        "n_posting_dates",
        "avg_reach_per_post",
        "interactions_per_post",
    ],
    extra={"roas": "%.2f", "cpm_vs_own_boost": "%.2f×", "posts_per_30d": "%.1f"},
    styler=view.style.map(_badge, subset=["reach_source"]),
    height=440,
)

st.subheader("CPM benchmark: creators vs own boosted posts")
d = inf[inf["cpm"].notna()].sort_values("cpm")
if d.empty:
    st.caption(
        "No creator has reach data → no CPM. Fill data/manual/influencer_reach.csv from creator-provided insights."
    )
else:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=d["influencer_name"],
            y=d["cpm"],
            name="Creator CPM (€)",
            marker={"color": PALETTE[0]},
            customdata=d[["reach_source", "reach"]].to_numpy(),
            hovertemplate="%{x}<br>CPM €%{y:.2f}<br>reach %{customdata[1]:,.0f} (%{customdata[0]})<extra></extra>",
        )
    )
    if bench == bench:
        fig.add_hline(
            y=bench,
            line={"color": PALETTE[1], "width": 2, "dash": "dash"},
            annotation_text=f"own boosted CPM median €{bench:.2f}",
            annotation_position="top right",
        )
    fig.update_layout(
        title="CPM per creator (€ per 1,000 reach) vs own paid boosting", hovermode="closest", bargap=0.4
    )
    st.plotly_chart(apply_layout(fig, 360), use_container_width=True)

section("Collab posts (creator-owned, co-authored by an own account)", "instagram")
source_line(
    "Instagram Collab posts appear on the creator's profile with the own account as co-author. Meta exposes "
    "likes/comments/saves/shares but no reach, so ER stays n/a; reach comes from the creator's insights (Klar sheet)."
)
if b.collab_posts.empty:
    st.caption("No Collab posts in the Windsor media pull.")
else:
    cp = b.collab_posts.copy()
    cp["date"] = pd.to_datetime(cp["timestamp"]).dt.date
    cp["handle"] = cp["owner_username"]
    km = b.klar_sheet_master.set_index("handle") if not b.klar_sheet_master.empty else None
    if km is not None:
        cp["in_klar_sheet"] = cp["handle"].isin(km.index)
        cp["type_of_partnership"] = cp["handle"].map(km["type_of_partnership"])
        cp["fixed_costs_sheet"] = cp["handle"].map(km["fixed_costs_sheet"])
    ccols = [
        c
        for c in [
            "date",
            "handle",
            "account",
            "permalink",
            "media_product_type",
            "like_count",
            "comments_count",
            "saved",
            "shares",
            "engagements",
            "in_klar_sheet",
            "type_of_partnership",
            "fixed_costs_sheet",
            "caption",
        ]
        if c in cp.columns
    ]
    show_table(
        cp[ccols].sort_values("date", ascending=False),
        num_cols=["like_count", "comments_count", "saved", "shares", "engagements"],
        eur_cols=["fixed_costs_sheet"],
        height=320,
    )

section("Klar sheet campaigns", "instagram")
if b.klar_sheet.empty:
    st.caption("No Klar influencer sheets cached (data/raw/klar_sheets or KLAR_SHEET_CSV_URLS).")
else:
    ksh = b.klar_sheet.copy()
    ksh = quarter_filter(ksh.rename(columns={"posting_date": "date"}), key="inf_sheet_quarter").rename(
        columns={"date": "posting_date"}
    )
    kcols = [
        "brand",
        "market",
        "influencer_name",
        "campaign_name",
        "type_of_partnership",
        "category",
        "post_type",
        "posting_date",
        "fixed_costs",
        "reach",
        "link_to_post",
        "discount_codes",
        "status_ok",
        "row",
    ]
    show_table(
        ksh[kcols].sort_values("posting_date", ascending=False),
        eur_cols=["fixed_costs"],
        num_cols=["reach", "row"],
        height=360,
    )

st.subheader("Per-post CPM (Klar sheet / manual reach)")
if b.influencer_posts.empty:
    st.caption(
        "No per-post reach rows matched (handle + posting_date must match data/manual/influencer_reach.csv)."
    )
else:
    show_table(b.influencer_posts, eur_cols=["costs", "cpm"], num_cols=["reach"], pct_cols=["er_by_reach"])

st.subheader("Not scannable / unmatched")
col1, col2 = st.columns(2)
with col1:
    st.markdown("**Klar influencers not in Creators sheet**")
    show_table(
        b.creator_join["unmatched_klar"][
            ["influencer_name", "platform", "discount_codes", "costs", "orders"]
        ],
        eur_cols=["costs"],
        num_cols=["orders"],
    )
with col2:
    st.markdown("**Creators without Klar rows (period)**")
    show_table(b.creator_join["unmatched_creators"][["name", "handle", "platform", "code", "deal"]])
ns = b.ig_scan[~b.ig_scan["scannable"]] if not b.ig_scan.empty else pd.DataFrame()
if not ns.empty:
    st.markdown("**Not scannable via Business Discovery** (not a Business/Creator account or unknown handle)")
    show_table(ns[["handle", "error"]])

pub_only = (
    sorted(set(b.ig_scan["handle"]) - set(b.influencers["creator_handle"].dropna()))
    if not b.ig_scan.empty
    else []
)
if pub_only:
    st.markdown("**Handles with public metrics but no Klar partnership** (connected in Windsor, not in Klar)")
    show_table(
        b.ig_scan[b.ig_scan["handle"].isin(pub_only)][
            ["handle", "followers_count", "n_media_fetched", "interactions_per_post", "posts_per_30d"]
        ],
        num_cols=["followers_count", "n_media_fetched", "interactions_per_post"],
        extra={"posts_per_30d": "%.1f"},
    )
