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
    account_label,
    apply_layout,
    metric_label,
    page_setup,
    period_control,
    period_label,
    section,
    show_table,
    source_line,
)
from src.transform import periods as pr  # noqa: E402

b = page_setup("Organic vs Boosted")
sel_p = period_control()
st.caption(
    f"Period {sel_p.label} ({sel_p.start:%d.%m.%Y} – {sel_p.end:%d.%m.%Y}), granularity {sel_p.granularity.lower()} "
    "(sidebar). Quarter = monthly figures summed."
)

if sel_p.compare is not None:
    cp = sel_p.compare
    section(f"{sel_p.label} vs {cp.label}", None)
    source_line(
        f"Current {sel_p.start:%d.%m.%Y} – {sel_p.end:%d.%m.%Y}, comparison {cp.start:%d.%m.%Y} – {cp.end:%d.%m.%Y}; "
        "flows summed over the periods, followers = last value, Δ% = (current − comparison) / comparison."
    )
    api_metrics = [
        "reach_daily_sum",
        "views",
        "new_followers",
        "unfollows",
        "net_follows",
        "boost_spend",
        "boosted_reach_daily_sum",
        "n_boosted_posts",
        "story_views_sum",
        "n_stories",
    ]
    sheet_metrics = ["reach", "views", "net_follows", "followers", "boost_spend", "boosted_reach", "n_posts"]
    tabs = st.tabs(["API (Windsor)", "Sheet"]) if b.has_api else [st.container()]
    frames = (
        [(tabs[0], pr.frame_for(b.api_weekly, b.api_monthly, sel_p.granularity), api_metrics)]
        if b.has_api
        else []
    ) + [(tabs[-1], pr.frame_for(b.weekly_wide, b.monthly_wide, sel_p.granularity), sheet_metrics)]
    for tab, frame, mets in frames:
        with tab:
            frame = frame[frame["account"].notna()] if "account" in frame.columns else frame
            if "kind" in frame.columns:
                frame = frame[frame["kind"].eq("organic")]
            cf = pr.compare_frame(frame, sel_p, mets)
            if cf.empty:
                st.caption("No rows in one of the periods.")
                continue
            cf["metric"] = cf["metric"].astype(str).map(metric_label)
            cf = cf[cf["current"].notna() | cf["compare"].notna()]
            show_table(
                cf.rename(columns={"current": sel_p.label, "compare": cp.label}),
                num_cols=[sel_p.label, cp.label, "delta_abs"],
                pct_cols=["delta_pct"],
                height=min(520, 60 + 36 * len(cf)),
            )

if b.has_api:
    section("Meta Ads boosted posts (API, Windsor facebook connector)", "meta")
    source_line(
        f"Source: {b.status.get('windsor')}. Boosts are campaigns named 'Instagram post: …', mapped to the promoted own post "
        "(caption prefix) and therefore to brand/market. CPM = spend / boosted reach (daily sum) × 1000."
    )
    am = pr.frame_for(b.api_weekly, b.api_monthly, sel_p.granularity)
    am = pr.in_range(am[am["account"].notna() & am["boost_spend"].notna()].copy(), sel_p)
    if not am.empty:
        am["month"] = [
            period_label(sel_p.ptype, int(y), int(m)) for y, m in zip(am["year"], am["period"], strict=True)
        ]
        am = am.sort_values(["year", "period"])
        piv = am.pivot_table(index="account", columns="month", values="boost_spend", aggfunc="sum")
        piv["Total"] = piv.sum(axis=1, min_count=1)
        show_table(piv.reset_index(), eur_cols=list(piv.columns))
        fig = go.Figure()
        cpf = am[am["cost_per_follow"].notna()] if "cost_per_follow" in am.columns else am.iloc[0:0]
        order = [a for a in ACCOUNT_COLORS if a in set(am["account"])] + sorted(
            set(am["account"]) - set(ACCOUNT_COLORS)
        )
        for acc in order:
            d = cpf[cpf["account"].eq(acc)].sort_values(["year", "period"])
            if d.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=d["month"],
                    y=d["cost_per_follow"],
                    mode="lines+markers",
                    name=account_label(acc),
                    line={"color": ACCOUNT_COLORS.get(acc), "width": 2},
                    marker={"size": 8},
                    customdata=d[["boost_spend", "boosted_follows"]].to_numpy(),
                    hovertemplate="%{x}<br>€%{y:.2f} per follow<br>spend €%{customdata[0]:,.0f} · "
                    "follows from ads %{customdata[1]:,.0f}<extra>%{fullData.name}</extra>",
                )
            )
        fig.update_layout(
            title=f"Cost per follow per {sel_p.granularity.lower()} (€, boost spend / follows from ads)"
        )
        if cpf.empty:
            st.caption(
                "Cost per follow needs the follows Meta attributes to the ads; they arrive with the next refresh."
            )
        else:
            st.plotly_chart(apply_layout(fig, 320), use_container_width=True)
            st.caption(
                "Boost spend of the 'Instagram post' campaigns divided by the follows Meta attributes to those ads "
                "('Follows from ads' in Business Suite), per account of the promoted post. Same definition as the "
                "report sheet's boosting block."
            )
        cols = [
            "account",
            "month",
            "boost_spend",
            "n_boosted_posts",
            "boosted_reach_daily_sum",
            "boosted_impressions",
            "boosted_clicks",
            "cpm_boosted",
            "boosted_follows",
            "cost_per_follow",
        ]
        show_table(
            am[cols].sort_values(["account", "month"]),
            eur_cols=["boost_spend", "cpm_boosted", "cost_per_follow"],
            num_cols=[
                "n_boosted_posts",
                "boosted_reach_daily_sum",
                "boosted_impressions",
                "boosted_clicks",
                "boosted_follows",
            ],
            pct_cols=["boosted_reach_share"],
            height=360,
        )
    aw = pr.frame_for(b.api_weekly, b.api_monthly, sel_p.granularity)
    aw = pr.in_range(aw[aw["account"].notna()].copy(), sel_p)
    if not aw.empty:
        st.markdown(f"**Organic vs boosted reach per {sel_p.granularity.lower()} (daily sums)**")
        d = aw
        for acc in sorted(d["account"].unique()):
            dd = d[d["account"].eq(acc)].sort_values("period")
            if dd["boost_spend"].fillna(0).sum() == 0:
                continue
            fig = go.Figure()
            x = [
                period_label(sel_p.ptype, int(y), int(p))
                for y, p in zip(dd["year"], dd["period"], strict=True)
            ]
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=dd["reach_daily_sum"],
                    name="Organic reach (daily sum)",
                    marker={"color": ACCOUNT_COLORS.get(acc, PALETTE[0])},
                )
            )
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=dd["boosted_reach_daily_sum"],
                    name="Boosted reach (daily sum)",
                    marker={"color": NEUTRAL_FILL},
                )
            )
            fig.update_layout(
                barmode="stack",
                bargap=0.3,
                title=f"{account_label(acc)}: organic vs boosted reach, {sel_p.label} (API)",
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
        lead = ["account", "campaign", "permalink", "media_id"]
        show_table(
            bp[lead + [c for c in bp.columns if c not in lead]].sort_values("first_day", ascending=False),
            eur_cols=["spend", "cpm"],
            num_cols=["days", "reach_daily_sum", "impressions", "clicks", "post_engagement", "link_clicks"],
            height=360,
        )


st.subheader(f"Boost spend by account and {sel_p.granularity.lower()} (sheet)")
source_line("Source: 2026 SM Weekly / Monthly Report ('Boosting Spent' / 'Ad cost' rows). Boosting = paid.")
bm = pr.in_range(pr.frame_for(b.boost_weekly, b.boost_monthly, sel_p.granularity).copy(), sel_p)
sel = account_filter(sorted(set(bm["account"]) | set(b.boost_weekly["account"])), key="ob_acc")
bm = bm[bm["account"].isin(sel)]
if bm.empty:
    st.info("No monthly boost spend.")
else:
    bm["plabel"] = [
        period_label(sel_p.ptype, int(y), int(p)) for y, p in zip(bm["year"], bm["period"], strict=True)
    ]
    order_lbl = list(bm.sort_values(["year", "period"])["plabel"].unique())
    piv = bm.pivot_table(index="account", columns="plabel", values="boost_spend", aggfunc="sum")[order_lbl]
    piv["Total"] = piv.sum(axis=1, min_count=1)
    show_table(piv.reset_index(), eur_cols=list(piv.columns))
    fig = go.Figure()
    order = [a for a in ACCOUNT_COLORS if a in set(bm["account"])] + sorted(
        set(bm["account"]) - set(ACCOUNT_COLORS)
    )
    for acc in order:
        d = bm[bm["account"].eq(acc)].sort_values(["year", "period"])
        fig.add_trace(
            go.Bar(
                x=d["plabel"],
                y=d["boost_spend"],
                name=account_label(acc),
                marker={"color": ACCOUNT_COLORS.get(acc)},
            )
        )
    fig.update_layout(
        barmode="stack", bargap=0.35, title=f"Boost spend per {sel_p.granularity.lower()} (€, sheet)"
    )
    st.plotly_chart(apply_layout(fig, 320), use_container_width=True)

st.subheader(f"Cost per net follow ({sel_p.granularity.lower()})")
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
        period_label(sel_p.ptype, int(y), int(p)) for y, p in zip(show["year"], show["period"], strict=True)
    ]
    show_table(
        show.drop(columns="year"),
        eur_cols=["boost_spend", "cost_per_net_follow"],
        num_cols=["organic_net_follows"],
    )

st.subheader(f"Boosted vs organic reach ({sel_p.granularity.lower()}, sheet)")
source_line(
    "Source: 2026 SM Weekly Report, boosting blocks (reach of boosted posts) vs organic blocks. "
    "CPM = spend / boosted reach × 1000; share = boosted / (organic + boosted)."
)
bw = pr.in_range(pr.frame_for(b.boost_weekly, b.boost_monthly, sel_p.granularity), sel_p)
bw = bw[bw["account"].isin(sel)].copy()
if bw.empty:
    st.info("No boosting blocks in the period.")
else:
    bw["period_lbl"] = [
        period_label(sel_p.ptype, int(y), int(p)) for y, p in zip(bw["year"], bw["period"], strict=True)
    ]
    d = bw.sort_values(["year", "period"])
    for acc in sorted(d["account"].unique()):
        dd = d[d["account"].eq(acc)].sort_values("period")
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=dd["period_lbl"],
                y=dd["organic_reach"],
                name="Organic reach",
                marker={"color": ACCOUNT_COLORS.get(acc, PALETTE[0])},
            )
        )
        fig.add_trace(
            go.Bar(
                x=dd["period_lbl"],
                y=dd["boosted_reach"],
                name="Boosted reach",
                marker={"color": NEUTRAL_FILL},
            )
        )
        fig.update_layout(
            barmode="stack",
            bargap=0.3,
            title=f"{account_label(acc)}: organic vs boosted reach, {sel_p.label}",
        )
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
