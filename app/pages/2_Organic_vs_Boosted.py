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
    STATUS,
    account_filter,
    apply_layout,
    page_setup,
    period_label,
    show_table,
    source_line,
)

b = page_setup("Organic vs Boosted")

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
                marker={"color": ACCOUNT_COLORS.get(acc), "line": {"width": 0}},
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
                marker={"color": ACCOUNT_COLORS.get(acc, "#2a78d6")},
            )
        )
        fig.add_trace(
            go.Bar(
                x=dd["period_lbl"], y=dd["boosted_reach"], name="boosted reach", marker={"color": "#898781"}
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

st.subheader("Reconciliation: monthly sheet vs Boosting Susy vs budget")
source_line(
    "Two manual sources disagree in places (e.g. Vegavero DE IG Sept). Neither is picked; delta = Susy − monthly sheet. "
    "Budget = col E of Boosting Susy (NaN where the cell is a name)."
)
rec = b.spend_recon.copy()
if rec.empty:
    st.info("Nothing to reconcile.")
else:
    rec["month"] = [MONTHS[int(m) - 1] for m in rec["month"]]
    show = rec[
        [
            "account",
            "year",
            "month",
            "boost_spend_monthly_sheet",
            "boost_spend_susy",
            "delta_susy_minus_sheet",
            "boost_budget",
            "agree",
        ]
    ]

    def _flag(v: object) -> str:
        return f"color: {STATUS['good']}" if v is True else f"color: {STATUS['critical']}"

    show_table(
        show,
        eur_cols=["boost_spend_monthly_sheet", "boost_spend_susy", "delta_susy_minus_sheet", "boost_budget"],
        styler=show.style.map(_flag, subset=["agree"]),
        height=480,
    )
    tot = rec.groupby("account", as_index=False).agg(
        sheet=("boost_spend_monthly_sheet", "sum"),
        susy=("boost_spend_susy", "sum"),
        budget=("boost_budget", "first"),
    )
    tot["delta"] = tot["susy"] - tot["sheet"]
    st.markdown("**YTD by account** (sums over months present in either source)")
    show_table(tot, eur_cols=["sheet", "susy", "budget", "delta"])
