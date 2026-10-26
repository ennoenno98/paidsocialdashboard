"""Page 1 — Overview: KPI tiles per account (latest period + MTD), weekly/monthly toggle, never mixed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root: `streamlit run` only adds app/

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (  # noqa: E402
    ACCOUNT_COLORS,
    ACCOUNT_ORDER,
    account_filter,
    apply_layout,
    fmt_eur,
    fmt_num,
    fmt_pct,
    page_setup,
    period_label,
    show_table,
    source_line,
)
from src.transform.metrics import iso_week_month, latest_period  # noqa: E402

b = page_setup("Overview")
scope = st.radio(
    "Scope", ["Weekly (2026 SM Weekly Report)", "Monthly (2026 SM Monthly Report)"], horizontal=True
)
weekly = scope.startswith("Weekly")
wide = b.weekly_wide if weekly else b.monthly_wide
ptype = "cw" if weekly else "month"
wide = wide[wide["period_type"].eq(ptype) & wide["kind"].eq("organic")]
if wide.empty:
    st.info("No data in this sheet.")
    st.stop()

year_opts = sorted(wide["year"].unique(), reverse=True)
year = st.selectbox("Year", year_opts, index=0)
wide = wide[wide["year"].eq(year)]
lp = latest_period(wide, ptype)
if lp is None:
    st.info("No data for this year.")
    st.stop()
_, latest = lp
sel = account_filter(sorted(wide["account"].unique()), key="ov_acc")

# ER from Post by Post: mean of per-post ER, by reach (IG) / views (TT). Labelled as a separate source.
posts = b.posts[b.posts["year"].eq(year)].copy()
if weekly:
    er_src = b.account_er_weekly[b.account_er_weekly["year"].eq(year)].rename(columns={"cw": "period"})
else:
    posts["period"] = [iso_week_month(y, c) for y, c in zip(posts["year"], posts["cw"], strict=True)]
    ok = posts[posts["er"].notna()]
    er_src = posts.groupby(["account", "year", "period"], as_index=False).agg(
        er_mean=("er", "mean"), n_posts=("post_name", "size"), er_basis=("er_basis", "first")
    )
    if not ok.empty:
        w = ok.groupby(["account", "year", "period"], as_index=False).agg(
            _e=("engagements", "sum"), _d=("er_denominator", "sum")
        )
        w["er_weighted"] = w["_e"] / w["_d"].where(w["_d"] > 0)
        er_src = er_src.merge(
            w[["account", "year", "period", "er_weighted"]], on=["account", "year", "period"], how="left"
        )
    else:
        er_src["er_weighted"] = float("nan")

st.subheader(f"Latest period: {period_label(ptype, year, latest)}")
source_line(
    f"Source: {'2026 SM Weekly Report' if weekly else '2026 SM Monthly Report'} (sheet values)",
    "ER: Post by Post sheet, recomputed = (likes+comments+saves+shares)/reach (TikTok: /video views), mean of per-post ER",
    "Boost spend: boosting block (weekly) / 'Boosting Spent' row (monthly)",
)

boost = b.boost_weekly if weekly else b.boost_monthly
accounts = [a for a in ACCOUNT_ORDER if a in sel] + [a for a in sel if a not in ACCOUNT_ORDER]
cols = st.columns(min(2, max(1, len(accounts))) or 1)  # 2 cards per row so metric values are not truncated
for i, acc in enumerate(accounts):
    row = wide[wide["account"].eq(acc) & wide["period"].eq(latest)]
    r = row.iloc[0] if not row.empty else pd.Series(dtype=float)
    bo = boost[boost["account"].eq(acc) & boost["period"].eq(latest) & boost["year"].eq(year)]
    er = (
        er_src[er_src["account"].eq(acc) & er_src["period"].eq(latest)]
        if not er_src.empty
        else pd.DataFrame()
    )
    with cols[i % len(cols)], st.container(border=True):
        st.markdown(f"**{acc}**")
        num = row.select_dtypes("number").drop(columns=["year", "period"], errors="ignore")
        if row.empty or num.notna().sum().sum() == 0:
            st.caption("no data")
            continue
        c1, c2, c3 = st.columns(3)
        c1.metric("Reach", fmt_num(r.get("reach")))
        c2.metric("Views", fmt_num(r.get("views")))
        c3.metric("Net follows", fmt_num(r.get("net_follows")))
        c1.metric("Followers", fmt_num(r.get("followers")))
        c2.metric("Boost spend", fmt_eur(bo["boost_spend"].sum() if not bo.empty else None))
        if not er.empty:
            e = er.iloc[0]
            c3.metric(
                f"ER mean/post ({e['er_basis']})",
                fmt_pct(e["er_mean"]),
                help=f"{int(e['n_posts'])} posts; reach-weighted {fmt_pct(e['er_weighted'])}",
            )
        else:
            c3.metric("ER mean/post", "n/a", help="no posts in Post by Post for this period")

# MTD (weekly scope only, explicitly labelled rollup)
if weekly:
    month = iso_week_month(year, latest)
    ru = b.weekly_rollup[
        b.weekly_rollup["year"].eq(year)
        & b.weekly_rollup["month"].eq(month)
        & b.weekly_rollup["kind"].eq("organic")
        & b.weekly_rollup["account"].isin(accounts)
    ]
    st.subheader(f"Month-to-date (weeks of month {month:02d}/{year}) — scope = weekly_rollup")
    source_line(
        "Sum of weekly sheet values for ISO weeks whose Thursday falls in the month; followers = last week. "
        "Not comparable to the monthly sheet without this label."
    )
    if not ru.empty:
        show = ru[
            [
                "account",
                "n_weeks",
                "reach",
                "views",
                "follows",
                "unfollows",
                "net_follows",
                "followers",
                "n_posts",
            ]
        ]
        show_table(show, num_cols=list(show.columns[2:]))

st.subheader("All periods")
metric = st.selectbox(
    "Metric", ["reach", "views", "net_follows", "followers", "follows", "unfollows", "n_posts"], index=0
)
fig = go.Figure()
for acc in accounts:
    d = wide[wide["account"].eq(acc)].sort_values("period")
    if metric not in d.columns or d[metric].notna().sum() == 0:
        continue
    fig.add_trace(
        go.Scatter(
            x=[period_label(ptype, year, int(p)) for p in d["period"]],
            y=d[metric],
            mode="lines+markers",
            name=acc,
            line={"width": 2, "color": ACCOUNT_COLORS.get(acc)},
            marker={"size": 8},
        )
    )
fig.update_layout(title=f"{metric} per {'CW' if weekly else 'month'} — {year}")
st.plotly_chart(apply_layout(fig), use_container_width=True)

tbl = wide[wide["account"].isin(accounts)].copy()
tbl["period"] = [period_label(ptype, int(y), int(p)) for y, p in zip(tbl["year"], tbl["period"], strict=True)]
keep = [
    c
    for c in [
        "account",
        "period",
        "reach",
        "views",
        "follows",
        "unfollows",
        "net_follows",
        "followers",
        "n_posts",
        "n_igs",
        "likes",
        "comments",
        "shares",
        "boost_spend",
        "er_sheet",
    ]
    if c in tbl.columns
]
show_table(tbl[keep], num_cols=keep[2:], eur_cols=["boost_spend"], pct_cols=["er_sheet"], height=420)
source_line("er_sheet = the sheet's own ER row, shown for reference only (not used in any computation).")
