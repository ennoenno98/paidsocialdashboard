"""Page 1 — Overview: KPI tiles per account for the latest complete period. Scopes are never mixed:
API weekly/monthly (Windsor: Instagram organic + Meta boosts) or the sheet's weekly/monthly blocks."""

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
    account_header,
    apply_layout,
    fmt_eur,
    fmt_num,
    fmt_pct,
    page_setup,
    period_label,
    show_table,
    source_line,
)
from src.transform.api_metrics import latest_complete_period  # noqa: E402
from src.transform.metrics import iso_week_month, latest_period  # noqa: E402

b = page_setup("Overview")
options = (["API weekly (Windsor)", "API monthly (Windsor)"] if b.has_api else []) + [
    "Sheet weekly (2026 SM Weekly Report)",
    "Sheet monthly (2026 SM Monthly Report)",
]
scope = st.radio("Scope", options, horizontal=True)
weekly = "weekly" in scope
ptype = "cw" if weekly else "month"
api = scope.startswith("API")


def order(accs: list[str]) -> list[str]:
    return [a for a in ACCOUNT_ORDER if a in accs] + sorted(set(accs) - set(ACCOUNT_ORDER))


# ------------------------------------------------------------------ API scope
if api:
    frame = b.api_weekly if weekly else b.api_monthly
    lp = latest_complete_period(frame, ptype)
    if lp is None:
        st.info("No complete period in the API data yet.")
        st.stop()
    year, latest = lp
    sel = account_filter(sorted(frame["account"].dropna().unique()), key="ov_api_acc")
    accounts = order(sel)
    st.subheader(f"Latest complete period: {period_label(ptype, year, latest)}")
    source_line(
        f"Source: Windsor `instagram` (daily account insights + per-post insights) and `facebook` boosted posts ({b.status.get('windsor')})",
        "Reach = sum of daily unique reach (overstates period reach; not comparable to the sheet's weekly reach)",
        "ER = (likes+comments+saves+shares)/reach per post published in the period, mean of posts (reach-weighted in tooltip)",
        "New followers: Meta exposes the last 30 days only; followers = latest snapshot",
    )
    latest_followers = (
        b.ig_daily.dropna(subset=["followers"]).sort_values("date").groupby("account")["followers"].last()
        if not b.ig_daily.empty
        else pd.Series(dtype=float)
    )
    cols = st.columns(min(2, max(1, len(accounts))) or 1)
    for i, acc in enumerate(accounts):
        row = frame[frame["account"].eq(acc) & frame["year"].eq(year) & frame["period"].eq(latest)]
        with cols[i % len(cols)], st.container(border=True):
            account_header(acc)
            if row.empty:
                st.caption("no data")
                continue
            r = row.iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Reach (daily sum)", fmt_num(r["reach_daily_sum"]))
            c2.metric("Views", fmt_num(r["views"]))
            full = r["new_followers_days"] >= r["n_days"] and r["n_days"] > 0
            c3.metric(
                "New followers" + ("" if full else " (partial)"),
                fmt_num(r["new_followers"]) if r["new_followers_days"] else "n/a",
                help=f"{fmt_num(r['new_followers_days'])}/{fmt_num(r['n_days'])} days with data (Meta: last 30 days only)",
            )
            c1.metric("Followers (latest)", fmt_num(latest_followers.get(acc)))
            c2.metric(
                "Boost spend (Meta)",
                fmt_eur(r["boost_spend"]) if pd.notna(r["boost_spend"]) else "€0",
                help=f"{fmt_num(r['n_boosted_posts'])} boosted posts; boosted reach {fmt_num(r['boosted_reach_daily_sum'])}; CPM {fmt_eur(r['cpm_boosted'], 2)}",
            )
            c3.metric(
                f"ER mean/post ({fmt_num(r['n_posts'])} posts)",
                fmt_pct(r["er_mean"]),
                help=f"reach-weighted {fmt_pct(r['er_weighted'])}; posts with ER {fmt_num(r['n_posts_with_er'])}",
            )
    if weekly:
        month = iso_week_month(year, latest)
        mtd = b.api_monthly[
            b.api_monthly["year"].eq(year)
            & b.api_monthly["period"].eq(month)
            & b.api_monthly["account"].isin(accounts)
        ]
        st.subheader(f"Month to date {month:02d}/{year} (API monthly, same source)")
        if not mtd.empty:
            show = mtd[
                [
                    "account",
                    "n_days",
                    "reach_daily_sum",
                    "views",
                    "new_followers",
                    "n_posts",
                    "er_mean",
                    "boost_spend",
                    "boosted_reach_daily_sum",
                    "cpm_boosted",
                    "boosted_reach_share",
                ]
            ]
            show_table(
                show,
                num_cols=[
                    "n_days",
                    "reach_daily_sum",
                    "views",
                    "new_followers",
                    "n_posts",
                    "boosted_reach_daily_sum",
                ],
                pct_cols=["er_mean", "boosted_reach_share"],
                eur_cols=["boost_spend", "cpm_boosted"],
            )
    st.subheader("All periods")
    metric = st.selectbox(
        "Metric",
        [
            "reach_daily_sum",
            "views",
            "new_followers",
            "n_posts",
            "er_mean",
            "boost_spend",
            "boosted_reach_daily_sum",
            "cpm_boosted",
            "boosted_reach_share",
        ],
        index=0,
    )
    fig = go.Figure()
    d_all = frame[frame["account"].isin(accounts)]
    for acc in accounts:
        d = d_all[d_all["account"].eq(acc)].sort_values(["year", "period"])
        if d[metric].notna().sum() == 0:
            continue
        fig.add_trace(
            go.Scatter(
                x=[period_label(ptype, int(y), int(p)) for y, p in zip(d["year"], d["period"], strict=True)],
                y=d[metric],
                mode="lines+markers",
                name=acc,
                line={"width": 2, "color": ACCOUNT_COLORS.get(acc)},
                marker={"size": 7},
            )
        )
    fig.update_layout(title=f"{metric} per {'ISO week' if weekly else 'month'} — API scope")
    if metric in ("er_mean", "boosted_reach_share"):
        fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(apply_layout(fig), use_container_width=True)
    tbl = d_all.copy()
    tbl["period"] = [
        period_label(ptype, int(y), int(p)) for y, p in zip(tbl["year"], tbl["period"], strict=True)
    ]
    keep = [
        "account",
        "period",
        "n_days",
        "reach_daily_sum",
        "views",
        "likes",
        "comments",
        "saves",
        "shares",
        "new_followers",
        "n_posts",
        "er_mean",
        "er_weighted",
        "boost_spend",
        "boosted_reach_daily_sum",
        "n_boosted_posts",
        "cpm_boosted",
        "boosted_reach_share",
    ]
    show_table(
        tbl[keep].sort_values(["account", "period"]),
        num_cols=keep[2:11] + ["n_boosted_posts", "boosted_reach_daily_sum"],
        pct_cols=["er_mean", "er_weighted", "boosted_reach_share"],
        eur_cols=["boost_spend", "cpm_boosted"],
        height=420,
    )
    st.stop()

# ------------------------------------------------------------------ Sheet scope (unchanged logic)
wide = b.weekly_wide if weekly else b.monthly_wide
wide = wide[wide["period_type"].eq(ptype) & wide["kind"].eq("organic")]
if wide.empty:
    st.info("No data in this sheet.")
    st.stop()
year = st.selectbox("Year", sorted(wide["year"].unique(), reverse=True), index=0)
wide = wide[wide["year"].eq(year)]
lp = latest_period(wide, ptype)
if lp is None:
    st.info("No data for this year.")
    st.stop()
_, latest = lp
sel = account_filter(sorted(wide["account"].unique()), key="ov_acc")
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
accounts = order(sel)
cols = st.columns(min(2, max(1, len(accounts))) or 1)
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
        account_header(acc)
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
fig.update_layout(title=f"{metric} per {'CW' if weekly else 'month'} — {year} (sheet)")
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
