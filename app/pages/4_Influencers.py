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
    delta_str,
    fmt_eur,
    page_setup,
    period_control,
    period_label,
    quarter_filter,
    section,
    show_table,
    source_line,
)
from src.ingest.klar_sheet import sheet_reach, worksheet_reach  # noqa: E402
from src.transform.scorecard import influencer_timeseries  # noqa: E402

b = page_setup("Influencers")
section("Creators on Instagram", "instagram")
source_line(
    f"Creator master = Klar influencer_flex ({b.status.get('klar')}), last 400 days: handle, deal type, category, code, "
    f"followers, costs, orders, revenue. Public post counts: Windsor instagram_public ({b.status.get('windsor')}).",
    f"Campaign master: Klar influencer Google Sheets ({b.status.get('klar_sheet')}); Influencer/Affiliate Name = handle.",
    "CPM = Klar costs (fixed + variable) / reach × 1000. reach_source: klar → Reach column of the Klar sheet → "
    "manual CSV → n/a. Never followers- or likes-based.",
)
sel_p = period_control()
st.caption(
    f"Period {sel_p.label} ({sel_p.start:%d.%m.%Y} – {sel_p.end:%d.%m.%Y}) from the sidebar: creators with a campaign "
    "posted or orders in the period."
)
inf = b.influencers_for(sel_p.start, sel_p.end)
if str(b.status.get("klar", "")).startswith("sheet-only"):
    st.warning(
        "No Klar API cache on this machine: campaigns, spend, reach and CPM come from the Klar sheets; orders, "
        "revenue and ROAS show 0 until the Klar pull runs here or DATA_SNAPSHOT_B64 is set (see README → Deploy)."
    )
if inf.empty:
    st.info("No Klar creators in this period.")
    st.stop()
fc1, fc2, fc3 = st.columns([1, 1, 2])
all_brands = sorted(inf["brand"].dropna().unique())
all_platforms = sorted(inf["platform"].dropna().unique())
with fc1:
    bsel = st.multiselect("Brand", all_brands, default=all_brands, key="inf_brand")
with fc2:
    psel = st.multiselect(
        "Platform", all_platforms, default=[p for p in all_platforms if p != "affiliate"], key="inf_platform"
    )
with fc3:
    source_line(
        "Klar carries two influencer datasources: the Google-sheet source behind the brand shops (source klar) and an "
        "older one behind the DE/IT and all-brands views (source legacy, Sep 2025 – Mar 2026). Both are listed; a legacy "
        "row the sheet source repeats within 3 days is dropped. Affiliates are hidden by default."
    )
inf = inf[inf["brand"].isin(bsel) & inf["platform"].isin(psel)]

own = b.boost_weekly["cpm_boosted"].dropna()
bench = float(own.median()) if len(own) else float("nan")
inf_c = None
if sel_p.compare is not None:
    inf_c = b.influencers_for(sel_p.compare.start, sel_p.compare.end)
    inf_c = inf_c[inf_c["brand"].isin(bsel) & inf_c["platform"].isin(psel)] if not inf_c.empty else inf_c
    st.caption(
        f"Deltas vs {sel_p.compare.label} ({sel_p.compare.start:%d.%m.%Y} – {sel_p.compare.end:%d.%m.%Y}): "
        f"{len(inf_c)} creators, costs {fmt_eur(inf_c['costs'].sum() if not inf_c.empty else 0)}, "
        f"net revenue {fmt_eur(inf_c['net_revenue'].sum() if not inf_c.empty else 0)}."
    )
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Creators (Klar, period)",
    len(inf),
    delta=delta_str(len(inf), len(inf_c), "abs") if inf_c is not None else None,
)
c2.metric(
    "Klar costs",
    fmt_eur(inf["costs"].sum()),
    delta=delta_str(inf["costs"].sum(), inf_c["costs"].sum() if not inf_c.empty else 0)
    if inf_c is not None
    else None,
    delta_color="off",
)
c3.metric(
    "Attributed net revenue",
    fmt_eur(inf["net_revenue"].sum()),
    delta=delta_str(inf["net_revenue"].sum(), inf_c["net_revenue"].sum() if not inf_c.empty else 0)
    if inf_c is not None
    else None,
)
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
    "brand",
    "source",
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

section(f"Influencer spend, ROAS and CPM per {sel_p.granularity.lower()}", None)
source_line(
    "Klar rows by posting date, affiliates excluded; CPM over campaigns with reach (Klar sheet / planning tab)."
)
reach_rows = pd.concat([sheet_reach(b.klar_sheet), worksheet_reach(b.klar_worksheet)], ignore_index=True)
ts = influencer_timeseries(b.klar, b.creator_attrs, reach_rows, sel_p.start, sel_p.end, sel_p.ptype)
ts = ts[ts["brand"].isin(bsel)]
if ts.empty:
    st.caption("No campaigns in the period.")
else:
    ts["period"] = [
        period_label(sel_p.ptype, int(y), int(p)) for y, p in zip(ts["year"], ts["period"], strict=True)
    ]
    show_table(
        ts.drop(columns=["year", "period_type"]),
        eur_cols=["costs", "net_revenue", "cpm"],
        num_cols=["orders", "n_creators", "reach"],
        extra={"roas": "%.2f"},
        height=min(420, 60 + 36 * len(ts)),
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
