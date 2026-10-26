"""Page 3 — Post performance: per-post table, reach-vs-ER scatter, filters, top/bottom decile."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import ACCOUNT_COLORS, account_filter, apply_layout, page_setup, show_table, source_line  # noqa: E402

b = page_setup("Post performance")
source_line(
    "Source: 2026 Post by Post (and 2025 Post by post report).",
    "ER = (likes + comments + saves + reposts/shares) / reach; TikTok: / video views (er_basis). NaN when reach is missing. "
    "The sheet's ER is never used, only reconciled (see Data quality).",
)
p = b.posts.copy()
if p.empty:
    st.info("No posts parsed.")
    st.stop()
c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
with c1:
    sel = account_filter(sorted(p["account"].unique()), key="pp_acc")
with c2:
    year = st.selectbox("Year", sorted(p["year"].unique(), reverse=True))
with c3:
    fmts = sorted(x for x in p["format"].dropna().unique())
    fsel = st.multiselect("Format", fmts, default=fmts)
with c4:
    cw_lo, cw_hi = st.slider("CW range", 1, 53, (1, 53))
d = p[p["account"].isin(sel) & p["year"].eq(year) & p["cw"].between(cw_lo, cw_hi)]
if fsel:
    d = d[d["format"].isin(fsel) | d["format"].isna()]
st.caption(
    f"{len(d)} posts · {int(d['er'].notna().sum())} with ER · {int(d['er'].isna().sum())} without reach/views (ER n/a)"
)

fig = go.Figure()
for acc in sorted(d["account"].unique()):
    dd = d[d["account"].eq(acc) & d["er"].notna()]
    fig.add_trace(
        go.Scatter(
            x=dd["er_denominator"],
            y=dd["er"],
            mode="markers",
            name=acc,
            marker={"size": 9, "color": ACCOUNT_COLORS.get(acc), "line": {"width": 1, "color": "#fcfcfb"}},
            customdata=dd[["post_name", "cw", "format", "engagements", "er_basis"]].to_numpy(),
            hovertemplate=(
                "%{customdata[0]}<br>CW %{customdata[1]} · %{customdata[2]}<br>"
                "denominator (%{customdata[4]}) %{x:,.0f} · eng %{customdata[3]:,.0f}<br>ER %{y:.2%}<extra>"
                + acc
                + "</extra>"
            ),
        )
    )
fig.update_layout(title="Reach (Instagram) or video views (TikTok) vs ER per post", hovermode="closest")
fig.update_xaxes(title="reach / video views (er_basis)")
fig.update_yaxes(title="ER", tickformat=".1%")
st.plotly_chart(apply_layout(fig, 420), use_container_width=True)

cols = [
    "account",
    "cw",
    "slot",
    "post_name",
    "format",
    "reach",
    "views",
    "video_views",
    "likes",
    "comments",
    "saves",
    "reposts",
    "shares",
    "follows",
    "engagements",
    "er",
    "er_basis",
    "play_time_min",
    "er_sheet",
]
cols = [c for c in cols if c in d.columns]
NUM = [
    "reach",
    "views",
    "video_views",
    "likes",
    "comments",
    "saves",
    "reposts",
    "shares",
    "follows",
    "engagements",
    "play_time_min",
]
show_table(
    d[cols].sort_values(["cw", "account", "slot"]), pct_cols=["er", "er_sheet"], num_cols=NUM, height=420
)

st.subheader("Top / bottom decile by ER")
ok = d[d["er"].notna()].sort_values("er", ascending=False)
if len(ok) >= 10:
    n = max(1, len(ok) // 10)
    t1, t2 = st.columns(2)
    short = ["account", "cw", "post_name", "format", "reach", "engagements", "er"]
    with t1:
        st.markdown(f"**Top decile** ({n} posts)")
        show_table(ok.head(n)[short], pct_cols=["er"], num_cols=["reach", "engagements"])
    with t2:
        st.markdown(f"**Bottom decile** ({n} posts)")
        show_table(ok.tail(n)[short], pct_cols=["er"], num_cols=["reach", "engagements"])
else:
    st.caption("fewer than 10 posts with ER in the selection")

if not b.ig_posts.empty:
    st.subheader("Instagram Graph API — own accounts (API data, separate source)")
    source_line(
        f"Source: {b.status.get('instagram')}. ER = (likes + comments + saved + shares) / reach from media insights."
    )
    ig = b.ig_posts.copy()
    ig = ig[ig["account"].isin(sel)] if sel else ig
    cols = [
        "account",
        "timestamp",
        "media_type",
        "media_product_type",
        "reach",
        "views",
        "like_count",
        "comments_count",
        "saved",
        "shares",
        "engagements",
        "er",
        "permalink",
    ]
    show_table(
        ig[cols].sort_values("timestamp", ascending=False),
        pct_cols=["er"],
        num_cols=["reach", "views", "like_count", "comments_count", "saved", "shares", "engagements"],
        height=360,
    )
