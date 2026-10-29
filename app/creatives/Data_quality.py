"""Paid creatives app — Data quality: excluded spend, naming, funnel-stage rules, Klar coverage, thumbnails, tags."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import streamlit as st  # noqa: E402

from app.common import creatives_page_setup, show_table, source_line  # noqa: E402
from src.ingest import windsor as wz  # noqa: E402
from src.transform import creatives as cr  # noqa: E402

b = creatives_page_setup("Data quality")

st.subheader("Fetch status")
for k, v in b.status.items():
    st.markdown(f"- **{k}**: {v}")

st.subheader("Issues")
iss = b.issues_df()
show_table(iss, height=min(80 + 36 * max(len(iss), 1), 360))

if b.ads.empty:
    st.info("No Meta ad-level data yet.")
    st.stop()

st.subheader("Paid creatives (Meta ad feed + Klar attribution)")
source_line(
    b.status.get("creatives", ""),
    b.status.get("klar_marketing", ""),
    "Unparseable ad names keep their spend but lose product / concept / tags; unknown funnel stages need a rule in "
    "config/creatives.yaml; thumbnails are cached by `make refresh`.",
)
ads = b.ads
if b.ads_excluded:
    st.markdown(
        "**Excluded from the asset model (organic / not creatives):** "
        + " · ".join(f"{k.replace('_', ' ')} €{v:,.0f}" for k, v in b.ads_excluded.items())
    )
un = ads[~ads["parsed"].astype(bool)]
st.markdown(f"**Ad names outside the naming convention: {un['asset_id'].nunique()}**")
if not un.empty:
    show_table(
        un.groupby(["asset_id", "campaign"], as_index=False).agg(
            spend=("spend", "sum"), first_day=("date", "min")
        ),
        eur_cols=["spend"],
        height=200,
    )
unk = ads[ads["funnel_stage"].eq("unknown")]
st.markdown(f"**Ad sets with unknown funnel stage: {unk['adset_name'].nunique()}**")
if not unk.empty:
    show_table(
        unk.groupby(["campaign", "adset_name", "objective", "event"], as_index=False).agg(
            spend=("spend", "sum")
        ),
        eur_cols=["spend"],
        height=200,
    )
st.markdown("**Klar attribution coverage**")
tot = ads["spend"].sum()
nk = ads.loc[~ads["klar_matched"].astype(bool), "spend"].sum()
st.caption(
    f"€{tot - nk:,.0f} of €{tot:,.0f} Meta spend has a Klar marketing_flex row (campaign + ad name); "
    f"€{nk:,.0f} falls back to Meta 7d click / 1d view attribution. "
    f"{len(b.klar_unmatched)} Klar Meta rows have no feed row (renamed ads, other accounts)."
)
if nk > 0:
    show_table(
        ads[~ads["klar_matched"].astype(bool)]
        .groupby(["campaign", "asset_id"], as_index=False)
        .agg(spend=("spend", "sum"), first_day=("date", "min"), last_day=("date", "max"))
        .sort_values("spend", ascending=False),
        eur_cols=["spend"],
        height=220,
    )
if not b.klar_unmatched.empty:
    show_table(
        b.klar_unmatched.groupby(["campaign", "ad_name"], as_index=False).agg(
            klar_cost=("klar_cost", "sum"), klar_orders=("klar_orders", "sum")
        ),
        eur_cols=["klar_cost"],
        height=200,
    )
assets = cr.merge_tags(cr.aggregate_assets(ads, by=["asset_id"]), b.creative_tags_llm, b.creative_tags_manual)
no_thumb = [
    aid
    for aid, cids in zip(assets["asset_id"], assets["creative_ids"], strict=True)
    if not any(wz.thumbnail_path(c.strip()) for c in str(cids or "").split(",") if c.strip())
]
no_tags = assets[assets["tag_source"].eq("none")]["asset_id"].tolist()
st.markdown(
    f"**Assets without a cached thumbnail: {len(no_thumb)} / {len(assets)}** · "
    f"**without creative tags: {len(no_tags)}** (naming tokens unknown; add a `Creative tags` row or run the LLM pass)"
)
if no_tags:
    show_table(
        assets[assets["asset_id"].isin(no_tags)][["asset_id", "spend", "concept", "style"]],
        eur_cols=["spend"],
        height=160,
    )
rec = cr.reconcile_ads_manager(ads, Path("data/manual/meta_ads_export.csv"))
st.markdown("**Spend: Windsor feed vs Ads Manager export** (drop a CSV at `data/manual/meta_ads_export.csv`)")
if rec.empty:
    st.caption("No export dropped.")
else:
    st.caption(
        f"Feed €{rec['spend_feed'].sum():,.0f} · export €{rec['spend_export'].sum():,.0f} · Δ €{rec['delta'].sum():+,.0f}"
    )
    show_table(rec, eur_cols=["spend_feed", "spend_export", "delta"], height=260)
