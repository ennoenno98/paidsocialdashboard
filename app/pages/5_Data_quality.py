"""Page 5 — Data quality: block coverage, issues, unmatched influencers, missing reach, ER discrepancies, fetch status."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import streamlit as st  # noqa: E402

from app.common import STATUS, page_setup, show_table, source_line  # noqa: E402

b = page_setup("Data quality")

st.subheader("Fetch status")
for k, v in b.status.items():
    st.markdown(f"- **{k}**: {v}")

st.subheader("Workbook block coverage")
source_line(f"Workbook: {b.xlsx.source}. One row per detected block; verify row ranges against the sheet.")
cov = b.xlsx.coverage()


def _status(v: object) -> str:
    return {
        "ok": f"color: {STATUS['good']}",
        "no_data": "color: #898781",
        "unmapped_title": f"color: {STATUS['critical']}",
        "unparsed": f"color: {STATUS['critical']}",
    }.get(str(v), "")


if not cov.empty:
    show_table(cov, styler=cov.style.map(_status, subset=["status"]), height=520)
    bad = cov[cov["status"].isin(["unmapped_title", "unparsed"])]
    if not bad.empty:
        st.error(
            f"{len(bad)} block(s) could not be mapped/parsed — add the title to config/accounts.yaml or fix the layout."
        )

st.subheader("Issues")
iss = b.issues_df()
sev = st.multiselect("Severity", ["error", "warn", "info"], default=["error", "warn"])
show_table(iss[iss["severity"].isin(sev)], height=360)

st.subheader("ER discrepancies vs sheet (> 0.5 pp)")
source_line(
    "Per post: recomputed ER vs the sheet's ER row. Typical cause: sheet divides by followers or omits saves/reposts."
)
show_table(
    b.er_recon,
    pct_cols=["er", "er_sheet_frac"],
    num_cols=["reach", "er_denominator", "engagements"],
    extra={"er_diff_pp": "%+.2f pp"},
    height=300,
)
st.markdown("**Weekly block ER row vs mean per-post ER (Post by Post), > 0.5 pp**")
show_table(
    b.weekly_er_recon,
    pct_cols=["er_sheet_frac", "er_mean_posts", "er_weighted_posts"],
    extra={"diff_pp": "%+.2f pp"},
    height=260,
)

st.subheader("Influencers: unmatched and missing reach")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Klar → Creators unmatched**")
    show_table(b.creator_join["unmatched_klar"], eur_cols=["costs", "net_revenue"])
with c2:
    st.markdown("**Creators → Klar unmatched**")
    show_table(b.creator_join["unmatched_creators"])
if not b.influencers.empty:
    miss = b.influencers[b.influencers["reach_source"].eq("n/a")][
        ["influencer_name", "creator_handle", "costs", "orders", "reach_source"]
    ]
    st.markdown(
        f"**Creators without reach (CPM n/a): {len(miss)}** — Klar reach is 0 for this account; "
        "add rows to data/manual/influencer_reach.csv"
    )
    show_table(miss, eur_cols=["costs"], num_cols=["orders"])

st.subheader("Posts without reach (ER n/a)")
nr = b.posts[b.posts["er"].isna()][
    ["account", "year", "cw", "slot", "post_name", "reach", "video_views", "er_basis", "src_rows"]
]
show_table(nr, height=240)

if not b.boosted.empty:
    st.subheader("Meta boosts (API): mapping to own posts")
    bb = b.boosted
    st.markdown(
        f"{int(bb['mapped'].sum())}/{len(bb)} ad-days mapped · match by {bb['match'].value_counts(dropna=False).to_dict()} · "
        f"unmapped spend €{bb.loc[~bb['mapped'], 'spend'].sum():,.0f}"
    )
    un = (
        bb[~bb["mapped"]]
        .groupby(["ad_account_name", "campaign"], as_index=False)
        .agg(first=("date", "min"), spend=("spend", "sum"))
    )
    if not un.empty:
        show_table(un.sort_values("spend", ascending=False), eur_cols=["spend"], height=240)
