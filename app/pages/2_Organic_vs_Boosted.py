"""Page 2 — Organic vs Boosted: spend, cost per net follow, boosted vs organic reach, spend reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (  # noqa: E402
    ACCOUNT_COLORS,
    MONTHS,
    NEUTRAL_FILL,
    PALETTE,
    STATUS,
    account_filter,
    apply_layout,
    page_setup,
    period_label,
    section,
    show_table,
    source_line,
)

b = page_setup("Organic vs Boosted")

if b.has_api:
    section("Meta Ads boosted posts (API, Windsor facebook connector)", "meta")
    source_line(
        f"Source: {b.status.get('windsor')}. Boosts are campaigns named 'Instagram post: …', mapped to the promoted own post "
        "(caption prefix) and therefore to brand/market. CPM = spend / boosted reach (daily sum) × 1000."
    )
    am = b.api_monthly[b.api_monthly["account"].notna() & b.api_monthly["boost_spend"].notna()].copy()
    if not am.empty:
        am["month"] = [f"{int(y)}-{int(m):02d}" for y, m in zip(am["year"], am["period"], strict=True)]
        piv = am.pivot_table(index="account", columns="month", values="boost_spend", aggfunc="sum")
        piv["Total"] = piv.sum(axis=1, min_count=1)
        show_table(piv.reset_index(), eur_cols=list(piv.columns))
        fig = go.Figure()
        for acc in [a for a in ACCOUNT_COLORS if a in set(am["account"])] + sorted(
            set(am["account"]) - set(ACCOUNT_COLORS)
        ):
            d = am[am["account"].eq(acc)].sort_values("month")
            fig.add_trace(
                go.Bar(
                    x=d["month"],
                    y=d["boost_spend"],
                    name=acc,
                    marker={"color": ACCOUNT_COLORS.get(acc)},
                )
            )
        fig.update_layout(barmode="stack", bargap=0.35, title="Meta boost spend per month (€)")
        st.plotly_chart(apply_layout(fig, 320), use_container_width=True)
        cols = [
            "account",
            "month",
            "boost_spend",
            "n_boosted_posts",
            "boosted_reach_daily_sum",
            "boosted_impressions",
            "boosted_clicks",
            "boosted_link_clicks",
            "cpm_boosted",
            "reach_daily_sum",
            "boosted_reach_share",
            "new_followers",
            "cost_per_new_follower",
        ]
        show_table(
            am[cols].sort_values(["account", "month"]),
            eur_cols=["boost_spend", "cpm_boosted", "cost_per_new_follower"],
            num_cols=[
                "n_boosted_posts",
                "boosted_reach_daily_sum",
                "boosted_impressions",
                "boosted_clicks",
                "boosted_link_clicks",
                "reach_daily_sum",
                "new_followers",
            ],
            pct_cols=["boosted_reach_share"],
            height=360,
        )
    aw = b.api_weekly[b.api_weekly["account"].notna()].copy()
    if not aw.empty:
        st.markdown("**Organic vs boosted reach per ISO week (daily sums)**")
        yr = st.selectbox("Year (API)", sorted(aw["year"].unique(), reverse=True), key="ob_api_year")
        d = aw[aw["year"].eq(yr)]
        for acc in sorted(d["account"].unique()):
            dd = d[d["account"].eq(acc)].sort_values("period")
            if dd["boost_spend"].fillna(0).sum() == 0:
                continue
            fig = go.Figure()
            x = [period_label("cw", int(y), int(p)) for y, p in zip(dd["year"], dd["period"], strict=True)]
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=dd["reach_daily_sum"],
                    name="organic reach (daily sum)",
                    marker={"color": ACCOUNT_COLORS.get(acc, PALETTE[0])},
                )
            )
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=dd["boosted_reach_daily_sum"],
                    name="boosted reach (daily sum)",
                    marker={"color": NEUTRAL_FILL},
                )
            )
            fig.update_layout(
                barmode="stack", bargap=0.3, title=f"{acc}: organic vs boosted reach, {yr} (API)"
            )
            st.plotly_chart(apply_layout(fig, 280), use_container_width=True)
    if not b.boosted.empty:
        st.markdown("**Boosted posts (API, per post)**")
        bp = (
            b.boosted.groupby(["account", "media_id", "campaign"], dropna=False)
            .agg(
                first_day=("date", "min"),
                last_day=("date", "max"),
                days=("date", "nunique"),
                spend=("spend", "sum"),
                reach_daily_sum=("reach", "sum"),
                impressions=("impressions", "sum"),
                clicks=("clicks", "sum"),
                post_engagement=("post_engagement", "sum"),
                link_clicks=("link_clicks", "sum"),
                permalink=("permalink", "first"),
                mapped=("mapped", "first"),
            )
            .reset_index()
        )
        bp["cpm"] = bp["spend"] / bp["reach_daily_sum"].where(bp["reach_daily_sum"] > 0) * 1000
        show_table(
            bp.sort_values("first_day", ascending=False),
            eur_cols=["spend", "cpm"],
            num_cols=["days", "reach_daily_sum", "impressions", "clicks", "post_engagement", "link_clicks"],
            height=360,
        )


st.subheader("Boost spend by account and month")
source_line("Source: 2026 SM Monthly Report ('Boosting Spent' / 'Ad cost' rows). Boosting = paid.")
bm = b.boost_monthly.copy()
sel = account_filter(sorted(set(bm["account"]) | set(b.boost_weekly["account"])), key="ob_acc")
bm = bm[bm["account"].isin(sel)]
if bm.empty:
    st.info("No monthly boost spend.")
else:
    piv = bm.pivot_table(index="account", columns="period", values="boost_spend", aggfunc="sum")
    piv.columns = [MONTHS[int(c) - 1] for c in piv.columns]
    piv["Total"] = piv.sum(axis=1, min_count=1)
    show_table(piv.reset_index(), eur_cols=list(piv.columns))
    fig = go.Figure()
    order = [a for a in ACCOUNT_COLORS if a in set(bm["account"])] + sorted(
        set(bm["account"]) - set(ACCOUNT_COLORS)
    )
    for acc in order:
        d = bm[bm["account"].eq(acc)].sort_values("period")
        fig.add_trace(
            go.Bar(
                x=[MONTHS[int(p) - 1] for p in d["period"]],
                y=d["boost_spend"],
                name=acc,
                marker={"color": ACCOUNT_COLORS.get(acc)},
            )
        )
    fig.update_layout(barmode="stack", bargap=0.35, title="Monthly boost spend (€)")
    st.plotly_chart(apply_layout(fig, 320), use_container_width=True)

st.subheader("Cost per net follow (monthly)")
source_line(
    "cost_per_net_follow = boost spend / organic block net follows (same account & month). "
    "Attribution caveat: net follows include organic effect; cost_per_new_follower (weekly) uses boosted-post followers only."
)
if not bm.empty:
    show = bm[
        [
            "account",
            "year",
            "period",
            "boost_spend",
            "organic_net_follows",
            "cost_per_net_follow",
            "spend_source",
        ]
    ].copy()
    show["period"] = [
        period_label("month", int(y), int(p)) for y, p in zip(show["year"], show["period"], strict=True)
    ]
    show_table(
        show.drop(columns="year"),
        eur_cols=["boost_spend", "cost_per_net_follow"],
        num_cols=["organic_net_follows"],
    )

st.subheader("Boosted vs organic reach (weekly)")
source_line(
    "Source: 2026 SM Weekly Report, boosting blocks (reach of boosted posts) vs organic blocks. "
    "CPM = spend / boosted reach × 1000; share = boosted / (organic + boosted)."
)
bw = b.boost_weekly[b.boost_weekly["account"].isin(sel)].copy()
if bw.empty:
    st.info("No weekly boosting blocks.")
else:
    bw["period_lbl"] = [
        period_label("cw", int(y), int(p)) for y, p in zip(bw["year"], bw["period"], strict=True)
    ]
    yr = st.selectbox("Year", sorted(bw["year"].unique(), reverse=True))
    d = bw[bw["year"].eq(yr)]
    for acc in sorted(d["account"].unique()):
        dd = d[d["account"].eq(acc)].sort_values("period")
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=dd["period_lbl"],
                y=dd["organic_reach"],
                name="organic reach",
                marker={"color": ACCOUNT_COLORS.get(acc, PALETTE[0])},
            )
        )
        fig.add_trace(
            go.Bar(
                x=dd["period_lbl"],
                y=dd["boosted_reach"],
                name="boosted reach",
                marker={"color": NEUTRAL_FILL},
            )
        )
        fig.update_layout(barmode="stack", bargap=0.3, title=f"{acc}: organic vs boosted reach, {yr}")
        st.plotly_chart(apply_layout(fig, 300), use_container_width=True)
    show = d[
        [
            "account",
            "period_lbl",
            "boost_spend",
            "boosted_reach",
            "organic_reach",
            "boosted_reach_share",
            "cpm_boosted",
            "new_followers_boosted",
            "cost_per_new_follower",
        ]
    ].rename(columns={"period_lbl": "period"})
    show_table(
        show,
        eur_cols=["boost_spend", "cpm_boosted", "cost_per_new_follower"],
        num_cols=["boosted_reach", "organic_reach", "new_followers_boosted"],
        pct_cols=["boosted_reach_share"],
    )

st.subheader("Reconciliation: monthly sheet vs Boosting Susy vs Meta Ads vs budget")
source_line(
    "Manual sources disagree in places (e.g. Vegavero DE IG Sept). Nothing is picked: deltas vs the monthly sheet are shown "
    "for Susy and for Meta Ads (API, boosted 'Instagram post' campaigns only). Budget = col E of Boosting Susy."
)
rec = b.spend_recon.copy()
if rec.empty:
    st.info("Nothing to reconcile.")
else:
    rec["month"] = [MONTHS[int(m) - 1] for m in rec["month"]]
    cols_r = [
        "account",
        "year",
        "month",
        "boost_spend_monthly_sheet",
        "boost_spend_susy",
        "delta_susy_minus_sheet",
        "boost_spend_meta",
        "delta_meta_minus_sheet",
        "boost_budget",
        "agree",
    ]
    show = rec[[c for c in cols_r if c in rec.columns]]

    def _flag(v: object) -> str:  # agree is NA for months known to Meta only (nothing manual to compare)
        if v is True:
            return f"color: {STATUS['good']}"
        return f"color: {STATUS['critical']}" if v is False else ""

    show_table(
        show,
        eur_cols=[
            "boost_spend_monthly_sheet",
            "boost_spend_susy",
            "delta_susy_minus_sheet",
            "boost_spend_meta",
            "delta_meta_minus_sheet",
            "boost_budget",
        ],
        styler=show.style.map(_flag, subset=["agree"]),
        height=480,
    )
    tot = rec.groupby(
        "account", as_index=False
    ).agg(  # min_count=1: a source with no figures stays NaN, not 0
        sheet=("boost_spend_monthly_sheet", lambda s: s.sum(min_count=1)),
        susy=("boost_spend_susy", lambda s: s.sum(min_count=1)),
        meta=("boost_spend_meta", lambda s: s.sum(min_count=1)),
        budget=("boost_budget", "first"),
    )
    tot["delta"] = tot["susy"] - tot["sheet"]
    tot["delta_meta"] = tot["meta"] - tot["sheet"]
    st.markdown("**YTD by account** (sums over months present in either source)")
    show_table(tot, eur_cols=["sheet", "susy", "meta", "budget", "delta", "delta_meta"])
