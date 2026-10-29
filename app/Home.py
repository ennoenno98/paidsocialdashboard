"""Page 1 — Overview: KPI tiles per account for the latest complete period. Scopes are never mixed:
API weekly/monthly (Windsor: Instagram organic + Meta boosts) or the sheet's weekly/monthly blocks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root: `streamlit run` only adds app/

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.branding import brand_html, platform_html  # noqa: E402
from app.common import (  # noqa: E402
    ACCOUNT_COLORS,
    ACCOUNT_ORDER,
    account_filter,
    account_header,
    account_label,
    apply_layout,
    delta_str,
    fmt_compact,
    fmt_eur,
    fmt_num,
    fmt_pct,
    metric_label,
    page_setup,
    period_control,
    period_label,
    section,
    show_table,
    source_line,
)
from src.ingest.klar_sheet import sheet_reach, worksheet_reach  # noqa: E402
from src.transform import periods as pr  # noqa: E402
from src.transform.api_metrics import latest_complete_period  # noqa: E402
from src.transform.metrics import iso_week_month, latest_period  # noqa: E402
from src.transform.scorecard import influencer_kpis, organic_kpis  # noqa: E402

b = page_setup("Overview")

# ------------------------------------------------------------------ Scorecard (brand x platform tiles)
section("Scorecard", None)
sel_p = period_control()
p_start, p_end, p_label = sel_p.start, sel_p.end, sel_p.label
source_line(
    f"{p_label} ({p_start:%d.%m.%Y} – {p_end:%d.%m.%Y}); change period and granularity in the sidebar.",
    "Organic Instagram from the Windsor API (new followers exist for the last 30 days only; the tile says how many "
    "days it covers), TikTok from the weekly sheet (week view) or the monthly sheet.",
    "Influencer: Klar influencer_flex per brand shop, campaigns by posting date, affiliates excluded. ROAS = net "
    "revenue / costs; CPM = costs / reach × 1000 over campaigns with reach (Klar sheet or planning tab).",
)
org = organic_kpis(b.ig_daily, b.monthly_wide, p_start, p_end, b.weekly_wide, sel_p.granularity)
reach_rows = pd.concat([sheet_reach(b.klar_sheet), worksheet_reach(b.klar_worksheet)], ignore_index=True)
inf_kpi, inf_break = influencer_kpis(b.klar, b.creator_attrs, reach_rows, p_start, p_end)
cmp_p = sel_p.compare
if cmp_p is not None:
    org_c = organic_kpis(b.ig_daily, b.monthly_wide, cmp_p.start, cmp_p.end, b.weekly_wide, sel_p.granularity)
    inf_kpi_c, _ = influencer_kpis(b.klar, b.creator_attrs, reach_rows, cmp_p.start, cmp_p.end)
    org_c = org_c.set_index("account") if not org_c.empty else org_c
    inf_kpi_c = inf_kpi_c.set_index("brand") if not inf_kpi_c.empty else inf_kpi_c
    st.caption(f"Deltas on the tiles: vs {cmp_p.label} ({cmp_p.start:%d.%m.%Y} – {cmp_p.end:%d.%m.%Y}).")
else:
    org_c = inf_kpi_c = pd.DataFrame()


def _cmp_row(frame: pd.DataFrame, key: str) -> pd.Series | None:
    return frame.loc[key] if not frame.empty and key in frame.index else None


brands = [
    x
    for x in ("vegavero", "wowtamins", "jasnum", "vanatari")
    if x in set(org["brand"]) | set(inf_kpi["brand"])
]


def _vs(label: str, cmp_row: pd.Series | None, col: str, fmt=fmt_num) -> str:  # noqa: ANN001
    if cmp_row is None:
        return ""
    return f" · {label}: {fmt(cmp_row[col])}"


def _tile_organic(row: pd.Series | None, platform: str, cmp_row: pd.Series | None = None) -> None:
    if row is None:
        st.caption("no data in period")
        return
    c1, c2 = st.columns(2)
    nf = row["new_followers"]
    growth = fmt_pct(row["follower_growth_pct"], 1) if pd.notna(row["follower_growth_pct"]) else None
    days = int(row["new_followers_days"]) if pd.notna(row["new_followers_days"]) else 0
    unit = (
        "days"
        if platform == "instagram"
        else ("weeks" if "weekly" in str(row.get("source", "")) else "months")
    )
    vs = cmp_p.label if cmp_p is not None else ""
    c1.metric(
        "Follower growth",
        ("+" if nf >= 0 else "") + fmt_compact(nf) if pd.notna(nf) else "n/a",
        delta=delta_str(nf, cmp_row["new_followers"], "abs") if cmp_row is not None else growth,
        help=f"{days} {unit} with data in the period · followers now {fmt_num(row['followers'])}"
        + (f" · growth {growth}" if growth and cmp_row is not None else "")
        + _vs(vs, cmp_row, "new_followers"),
    )
    c2.metric(
        "Views",
        fmt_compact(row["views"]),
        delta=delta_str(row["views"], cmp_row["views"]) if cmp_row is not None else None,
        help=f"views {fmt_num(row['views'])} · reach (daily sum) {fmt_num(row['reach'])}"
        + _vs(vs, cmp_row, "views")
        + (
            f" · reach {vs}: {fmt_num(cmp_row['reach'])} ({delta_str(row['reach'], cmp_row['reach']) or 'n/a'})"
            if cmp_row is not None
            else ""
        ),
    )


def _tile_influencer(row: pd.Series | None, cmp_row: pd.Series | None = None) -> None:
    if row is None:
        st.caption("no campaigns in period")
        return
    vs = cmp_p.label if cmp_p is not None else ""
    c1, c2 = st.columns(2)  # two per row: three tiles truncate inside the brand card
    c1.metric(
        "Spend",
        fmt_compact(row["costs"], "€"),
        delta=delta_str(row["costs"], cmp_row["costs"]) if cmp_row is not None else None,
        delta_color="off",
        help=f"{fmt_eur(row['costs'])} · {int(row['n_campaigns'])} campaigns · {int(row['n_creators'])} creators"
        + _vs(vs, cmp_row, "costs", fmt_eur),
    )
    c2.metric(
        "ROAS",
        f"{row['roas']:.2f}" if pd.notna(row["roas"]) else "n/a",
        delta=delta_str(row["roas"], cmp_row["roas"]) if cmp_row is not None else None,
        help=f"net revenue {fmt_eur(row['net_revenue'])} · {int(row['orders'])} orders · CAC {fmt_eur(row['cac'], 0)}"
        + _vs(vs, cmp_row, "roas", lambda x: f"{x:.2f}" if pd.notna(x) else "n/a"),
    )
    c3, _ = st.columns(2)
    c3.metric(
        "CPM",
        fmt_eur(row["cpm"], 2) if pd.notna(row["cpm"]) else "n/a",
        delta=delta_str(row["cpm"], cmp_row["cpm"]) if cmp_row is not None else None,
        delta_color="inverse",
        help=f"reach known for {fmt_pct(row['reach_coverage'], 0)} of spend ({fmt_eur(row['costs_with_reach'])})"
        + _vs(vs, cmp_row, "cpm", lambda x: fmt_eur(x, 2)),
    )
    st.caption(
        f"Performance {fmt_pct(row['share_performance'], 0)} of spend, ROAS "
        f"{row['roas_performance']:.2f} · Awareness {fmt_pct(1 - row['share_performance'], 0)}, ROAS "
        f"{row['roas_awareness']:.2f}"
        if pd.notna(row["share_performance"])
        else "goal split n/a"
    )


for brand in brands:
    with st.container(border=True):
        st.markdown(brand_html(brand, 24), unsafe_allow_html=True)
        cols = st.columns(3)
        with cols[0]:
            st.markdown(platform_html("instagram") + " **Instagram organic**", unsafe_allow_html=True)
            ig_rows = org[org["brand"].eq(brand) & org["platform"].eq("instagram")]
            if ig_rows.empty:
                st.caption("no Instagram account in the API data")
            for _, r in ig_rows.iterrows():
                st.caption(account_label(r["account"]))
                _tile_organic(r, "instagram", _cmp_row(org_c, r["account"]))
        with cols[1]:
            st.markdown(platform_html("tiktok") + " **TikTok organic**", unsafe_allow_html=True)
            tt_rows = org[org["brand"].eq(brand) & org["platform"].eq("tiktok")]
            if tt_rows.empty:
                st.caption("no TikTok block in the sheet for this period")
            for _, r in tt_rows.iterrows():
                st.caption(account_label(r["account"]))
                _tile_organic(r, "tiktok", _cmp_row(org_c, r["account"]))
        with cols[2]:
            st.markdown("🤝 **Influencer (Klar)**")
            ir = inf_kpi[inf_kpi["brand"].eq(brand)]
            _tile_influencer(ir.iloc[0] if not ir.empty else None, _cmp_row(inf_kpi_c, brand))

with st.expander(
    "Influencer budget breakdown: goal (performance vs awareness), tier, industry", expanded=False
):
    if inf_break.empty:
        st.caption("No Klar campaigns in the period.")
    else:
        bsel = st.multiselect(
            "Brand",
            sorted(inf_break["brand"].unique()),
            default=sorted(inf_break["brand"].unique()),
            key="sc_brands",
        )
        bb = inf_break[inf_break["brand"].isin(bsel)]
        t1, t2, t3 = st.columns(3)
        for col, dim, title in ((t1, "goal", "Goal"), (t2, "tier", "Tier"), (t3, "industry", "Industry")):
            with col:
                st.markdown(f"**{title}**")
                d = (
                    bb[bb["dimension"].eq(dim)]
                    .drop(columns=["dimension"])
                    .sort_values(["brand", "costs"], ascending=[True, False])
                )
                show_table(
                    d.rename(columns={"value": dim}),
                    eur_cols=["costs", "net_revenue", "cpm"],
                    pct_cols=["share"],
                    num_cols=["orders", "n_creators", "reach"],
                    extra={"roas": "%.2f"},
                    height=min(400, 60 + 36 * len(d)),
                )
        st.caption(
            "Tier = planning-tab label (Micro/Mid/Macro/Mega), else derived from followers (<25k Micro, 25–100k Mid, "
            "100–500k Macro, ≥500k Mega); 'Unknown' = no tier and no follower count in the workbooks. Industry = "
            "Klar category, else the planning tab's category."
        )

st.divider()
options = (["API (Windsor)"] if b.has_api else []) + ["Sheet (2026 SM Weekly / Monthly Report)"]
scope = st.radio("Scope", options, horizontal=True)
weekly = sel_p.granularity == "Week"
ptype = sel_p.ptype
api = scope.startswith("API")
st.caption(f"Granularity: {sel_p.granularity.lower()} (sidebar). Quarter = monthly figures summed.")


def order(accs: list[str]) -> list[str]:
    return [a for a in ACCOUNT_ORDER if a in accs] + sorted(set(accs) - set(ACCOUNT_ORDER))


# ------------------------------------------------------------------ API scope
if api:
    frame = pr.frame_for(b.api_weekly, b.api_monthly, sel_p.granularity)
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
        format_func=metric_label,
    )
    fig = go.Figure()
    d_all = pr.in_range(frame[frame["account"].isin(accounts)], sel_p)
    for acc in accounts:
        d = d_all[d_all["account"].eq(acc)].sort_values(["year", "period"])
        if d[metric].notna().sum() == 0:
            continue
        fig.add_trace(
            go.Scatter(
                x=[period_label(ptype, int(y), int(p)) for y, p in zip(d["year"], d["period"], strict=True)],
                y=d[metric],
                mode="lines+markers",
                name=account_label(acc),
                line={"width": 2, "color": ACCOUNT_COLORS.get(acc)},
                marker={"size": 7},
            )
        )
    fig.update_layout(title=f"{metric_label(metric)} per {'ISO week' if weekly else 'month'} (API)")
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
    section("Stories", "instagram")
    source_line(
        "Source: Windsor instagram stories, collected daily (Meta exposes a story for 24 h only; history starts "
        "with the first daily refresh). Reach is per story; exit rate = exits / views."
    )
    if b.ig_stories.empty:
        st.info("No stories collected yet. The daily refresh accumulates them from now on.")
    else:
        stc = [
            "account",
            "period",
            "n_stories",
            "story_reach_sum",
            "story_reach_per_story",
            "story_views_sum",
            "story_replies",
            "story_shares",
            "story_interactions",
            "story_exit_rate",
            "story_taps_forward",
            "story_taps_back",
        ]
        st_tbl = tbl[tbl["n_stories"].fillna(0) > 0][[c for c in stc if c in tbl.columns]]
        show_table(
            st_tbl.sort_values(["account", "period"]),
            num_cols=stc[2:9] + ["story_taps_forward", "story_taps_back"],
            pct_cols=["story_exit_rate"],
            height=260,
        )
        st.markdown("**Latest stories (per story)**")
        sl = b.ig_stories[b.ig_stories["account"].isin(accounts)].sort_values("timestamp", ascending=False)
        show_table(
            sl[
                [
                    "account",
                    "timestamp",
                    "permalink",
                    "reach",
                    "views",
                    "replies",
                    "shares",
                    "exits",
                    "taps_forward",
                    "taps_back",
                ]
            ].head(60),
            num_cols=["reach", "views", "replies", "shares", "exits", "taps_forward", "taps_back"],
            height=300,
        )
    st.stop()

# ------------------------------------------------------------------ Sheet scope (unchanged logic)
wide = pr.frame_for(b.weekly_wide, b.monthly_wide, sel_p.granularity)
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
    "Metric",
    ["reach", "views", "net_follows", "followers", "follows", "unfollows", "n_posts"],
    index=0,
    format_func=metric_label,
)
wide = pr.in_range(wide, sel_p)
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
            name=account_label(acc),
            line={"width": 2, "color": ACCOUNT_COLORS.get(acc)},
            marker={"size": 8},
        )
    )
fig.update_layout(title=f"{metric_label(metric)} per {'CW' if weekly else 'month'}, {year} (sheet)")
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
