"""Page 5 — Data quality: block coverage, issues, unmatched influencers, missing reach, ER discrepancies, fetch status."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import streamlit as st  # noqa: E402

from app.common import INK, STATUS, page_setup, section, show_table, source_line  # noqa: E402

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
        "no_data": f"color: {INK['muted']}",
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

st.subheader("Klar sheet: paid campaigns without Reach")
source_line(
    "Fill the 'Reach' (and 'Link to Post') column in the Klar influencer Google Sheet for these rows; Klar and this "
    "dashboard pick it up on the next refresh (reach_source = klar_sheet)."
)
if b.klar_sheet.empty:
    st.caption("No Klar sheets cached.")
else:
    from src.ingest.klar_sheet import campaigns_missing_reach  # noqa: E402

    mr = campaigns_missing_reach(b.klar_sheet)
    st.markdown(f"**{len(mr)} of {len(b.klar_sheet)} campaigns have costs but no reach**")
    show_table(
        mr.sort_values("posting_date", ascending=False),
        eur_cols=["fixed_costs"],
        num_cols=["row"],
        height=300,
    )

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

if not b.ads.empty:
    from src.ingest import windsor as wz  # noqa: E402
    from src.transform import creatives as cr  # noqa: E402

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
            unk.groupby(["campaign", "adset_name", "goal"], as_index=False).agg(spend=("spend", "sum")),
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
    assets = cr.merge_tags(
        cr.aggregate_assets(ads, by=["asset_id"]), b.creative_tags_llm, b.creative_tags_manual
    )
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
    st.markdown(
        "**Spend: Windsor feed vs Ads Manager export** (drop a CSV at `data/manual/meta_ads_export.csv`)"
    )
    if rec.empty:
        st.caption("No export dropped.")
    else:
        st.caption(
            f"Feed €{rec['spend_feed'].sum():,.0f} · export €{rec['spend_export'].sum():,.0f} · Δ €{rec['delta'].sum():+,.0f}"
        )
        show_table(rec, eur_cols=["spend_feed", "spend_export", "delta"], height=260)


section("Meta boosts: account of the promoted post vs ad-set targeting", "meta")
source_line(
    "Boost spend ('Instagram post' campaigns) is allocated to the account whose post was promoted (caption match "
    "against the own posts; the ad account only decides the brand). The ad set's geo targeting is shown next to it "
    "as a check: an Italian post with DE targeting is worth a look in Ads Manager."
)
bo = b.boosted
if bo.empty or "targeting" not in bo.columns:
    st.caption("No boosted rows, or the ads feed with the targeting is not cached yet.")
else:
    bo = bo.copy()
    bo["targeting"] = bo["targeting"].fillna("n/a")
    bo["account"] = bo["account"].fillna("unmapped (" + bo["brand"].fillna("?") + ")")
    xt = (
        bo.groupby(["account", "targeting"], dropna=False)
        .agg(spend=("spend", "sum"), ads=("ad_id", "nunique"), follows=("follows", "sum"))
        .reset_index()
        .sort_values(["account", "spend"], ascending=[True, False])
    )
    xt["account_market"] = xt["account"].astype(str).str.split("/").str[-1]
    xt["targeting_matches"] = [
        (m in str(t).split(",")) if t != "n/a" and "/" in str(a) else None
        for a, m, t in zip(xt["account"], xt["account_market"], xt["targeting"], strict=True)
    ]
    show_table(
        xt.drop(columns=["account_market"]),
        eur_cols=["spend"],
        num_cols=["ads", "follows"],
        height=min(480, 60 + 36 * len(xt)),
    )
    mism = xt[xt["targeting_matches"].eq(False)]["spend"].sum()
    st.caption(
        f"Spend where the ad-set targeting does not include the post account's market: {mism:,.0f} €. "
        "Posts boosted from the Instagram app often carry the ad account's home country as targeting, so this is a "
        "prompt to check, not an error by itself."
    )
