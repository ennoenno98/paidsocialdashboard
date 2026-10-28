"""Page 6 — Paid creatives: which asset / hook works for which goal (prospecting vs retargeting).

Source: Meta ad-level feed (Windsor ``facebook``), 7-day click / 1-day view attribution. Grain: asset x funnel
stage inside the sidebar period. Instagram post boosts live on Organic vs Boosted; page promotions are listed
but never ranked. Tags: naming convention -> LLM vision pass -> manual overrides (team input sheet).
"""

from __future__ import annotations

import base64
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: `streamlit run` only adds app/

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.common import (  # noqa: E402
    BRAND,
    INK,
    NEUTRAL_FILL,
    PALETTE,
    STATUS,
    SURFACE,
    apply_layout,
    fmt_compact,
    fmt_eur,
    fmt_num,
    fmt_pct,
    metric_label,
    page_setup,
    period_control,
    section,
    show_table,
    source_line,
)
from src.ingest import windsor as wz  # noqa: E402
from src.transform import creatives as cr  # noqa: E402

b = page_setup("Paid creatives")
section("Which asset works for which goal", "meta")
sel_p = period_control()
source_line(
    f"{sel_p.label} ({sel_p.start:%d.%m.%Y} – {sel_p.end:%d.%m.%Y}); change period and granularity in the sidebar.",
    b.status.get("creatives", ""),
    "ROAS, CPA and purchases are Meta-attributed (7-day click / 1-day view) and recomputed from daily sums; "
    "never compare with Klar ROAS on the Influencers page.",
)
if b.ads.empty:
    st.info(
        "No Meta ad-level data: the `facebook__ads` Windsor pull is missing. Run `make refresh` with WINDSOR_API_KEY."
    )
    st.stop()

cfg = cr.load_creatives_config()
STAGE_COLOR = {
    "prospecting": PALETTE[1],
    "retargeting": PALETTE[0],
    "unknown": NEUTRAL_FILL,
    "n/a": INK["axis"],
}
VERDICT_COLOR = {
    "Performing": STATUS["good"],
    "Underperforming": STATUS["critical"],
    "Low data": INK["muted"],
    "n/a": INK["axis"],
}
VERDICT_ICON = {
    "Performing": "▲ Performing",
    "Underperforming": "▼ Underperforming",
    "Low data": "· Low data",
    "n/a": "–",
}


# ------------------------------------------------------------------ filters
def _opts(col: str) -> list[str]:
    return sorted(x for x in b.ads[col].dropna().astype(str).unique())


with st.sidebar:
    st.markdown("**Creatives**")
    grain = st.radio(
        "Grain", ["Asset × funnel stage", "Asset (all stages)"], key="cr_grain", horizontal=False
    )
    f_stage = st.multiselect("Funnel stage", cr.STAGES, default=cr.STAGES[:2], key="cr_stage")
    f_format = st.multiselect(
        "Format", [f for f in cr.FORMATS if f in set(_opts("asset_type"))], key="cr_fmt"
    )
    f_product = st.multiselect("Product", _opts("product"), key="cr_prod")
    f_launch = st.multiselect("Launch month", _opts("launch_month"), key="cr_launch")
    f_status = st.radio("Status", ["All", "Active (served in the last 3 days)", "Off"], key="cr_status")
    min_spend = st.number_input(
        "Min spend per row (€)",
        min_value=0.0,
        value=float(cfg["targets"].get("min_spend_for_verdict", 100)),
        step=50.0,
        key="cr_min",
    )
    show_promo = st.checkbox("Show page promotions", value=False, key="cr_promo")

by = cr.ASSET_KEY if grain.startswith("Asset ×") else ["asset_id"]
ads = b.ads
if f_stage and grain.startswith("Asset ×"):
    ads = ads[ads["funnel_stage"].isin([*f_stage, "n/a"])]
if f_format:
    ads = ads[ads["asset_type"].isin(f_format)]
if f_product:
    ads = ads[ads["product"].isin(f_product)]
if f_launch:
    ads = ads[ads["launch_month"].isin(f_launch)]
if not show_promo:
    ads = ads[ads["asset_type"].ne("boost_page_promo")]


def _assets(start: dt.date, end: dt.date) -> pd.DataFrame:
    a = cr.aggregate_assets(ads, start, end, by=by)
    if "funnel_stage" not in a.columns:
        a["funnel_stage"] = "all"
    a = cr.merge_tags(a, b.creative_tags_llm, b.creative_tags_manual)
    return cr.judge_and_verdict(a, cfg)


assets = _assets(sel_p.start, sel_p.end)
n_days = (sel_p.end - sel_p.start).days + 1
prev = _assets(sel_p.start - dt.timedelta(days=n_days), sel_p.start - dt.timedelta(days=1))

# tag filters (after aggregation: tags are per asset)
c1, c2, c3 = st.columns(3)
with c1:
    f_vis = st.multiselect("Visual subject", cr.TAG_VOCAB["visual_subject"] + ["untagged"], key="cr_vis")
with c2:
    f_claim = st.multiselect("Claim / hook", cr.TAG_VOCAB["claim"] + ["untagged"], key="cr_claim")
with c3:
    f_offer = st.multiselect("Offer", cr.TAG_VOCAB["offer"], key="cr_offer")
for col, chosen in (("visual_subject", f_vis), ("claim", f_claim), ("offer", f_offer)):
    if chosen:
        v = assets[col].fillna("untagged")
        assets = assets[v.isin(chosen)]
if f_status.startswith("Active"):
    assets = assets[assets["active"]]
elif f_status == "Off":
    assets = assets[~assets["active"]]
assets = assets[assets["spend"].fillna(0) >= min_spend]
if assets.empty:
    st.info("No assets in this period with these filters.")
    st.stop()

# ------------------------------------------------------------------ tiles
sc = assets[assets["asset_type"].ne("boost_page_promo")]
pv = prev[prev["asset_type"].ne("boost_page_promo")]


def _tot(d: pd.DataFrame) -> dict[str, float]:
    s = d[["spend", "purchases", "purchase_value", "link_clicks", "impressions"]].sum()
    return {
        "spend": s["spend"],
        "purchases": s["purchases"],
        "roas": s["purchase_value"] / s["spend"] if s["spend"] else float("nan"),
        "cpa": s["spend"] / s["purchases"] if s["purchases"] else float("nan"),
        "ctr": s["link_clicks"] / s["impressions"] if s["impressions"] else float("nan"),
    }


cur, old = _tot(sc), _tot(pv)


def _delta(k: str, pct: bool = False, inverse: bool = False) -> str | None:
    a, o = cur[k], old[k]
    if pd.isna(a) or pd.isna(o) or o == 0:
        return None
    d = (a - o) / o
    return f"{d:+.0%} vs previous {n_days} days"


t = st.columns(6)
t[0].metric("Spend", fmt_compact(cur["spend"], "€"), _delta("spend"))
t[1].metric("Purchases", fmt_num(cur["purchases"]), _delta("purchases"))
t[2].metric("ROAS", fmt_num(cur["roas"], 2), _delta("roas"))
t[3].metric("CPA", fmt_eur(cur["cpa"], 2), _delta("cpa"), delta_color="inverse")
t[4].metric("CTR (link)", fmt_pct(cur["ctr"]), _delta("ctr"))
vc = sc["verdict"].value_counts()
t[5].metric(
    "Performing / under / low data",
    f"{int(vc.get('Performing', 0))} / {int(vc.get('Underperforming', 0))} / {int(vc.get('Low data', 0))}",
)
tg = assets.attrs.get("targets", {})
st.caption(
    f"Verdict targets (account average over the period and filters, pin them in config/creatives.yaml): "
    f"ROAS {fmt_num(tg.get('roas'), 2)} · CTR {fmt_pct(tg.get('ctr_link'))} · CPA {fmt_eur(tg.get('cpa'), 2)} · "
    f"min spend for a verdict €{assets.attrs.get('min_spend', 100):,.0f}. Judged on ROAS when ≥ 50 % of the row's spend "
    "sat in conversion / value ad sets, else on CTR."
)


# ------------------------------------------------------------------ asset table
section("Assets", None)


def _s(v: object) -> str | None:
    """Scalar -> str, with pandas NA / NaN -> None (``or`` chains choke on pd.NA)."""
    if v is None or (isinstance(v, float) and v != v) or v is pd.NA:
        return None
    return str(v) if str(v).strip() else None


def _thumb(row: pd.Series) -> str | None:
    for cid in str(_s(row.get("creative_ids")) or "").split(","):
        p = wz.thumbnail_path(cid.strip())
        if p is not None:
            data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
            return f"data:image/jpeg;base64,{data}"
    return _s(row.get("image_url")) or _s(row.get("thumbnail_url"))


tbl = assets.copy()
tbl["thumbnail"] = tbl.apply(_thumb, axis=1)
tbl["verdict"] = tbl["verdict"].map(VERDICT_ICON).fillna(tbl["verdict"])
for c in ("visual_subject", "claim", "offer", "hook", "product", "variant", "launch_month"):
    tbl[c] = tbl[c].astype(object).where(tbl[c].notna(), "")
cols = [
    "thumbnail",
    "asset_id",
    "funnel_stage",
    "product",
    "asset_type",
    "visual_subject",
    "claim",
    "offer",
    "hook",
    "spend",
    "impressions",
    "ctr_link",
    "cpc",
    "cpm",
    "purchases",
    "cpa",
    "roas",
    "hook_rate",
    "judge_kpi",
    "verdict",
    "launch_month",
    "variant",
    "goal_mix",
    "n_adsets",
    "active",
    "tag_source",
]
cols = [c for c in cols if c in tbl.columns]
styler = tbl[cols].style.map(
    lambda v: (
        f"color: {VERDICT_COLOR.get(str(v).split(' ', 1)[-1], '')}; font-weight: 600"
        if isinstance(v, str)
        else ""
    ),
    subset=["verdict"],
)
st.dataframe(
    styler,
    hide_index=True,
    use_container_width=True,
    height=460,
    column_config={
        "thumbnail": st.column_config.ImageColumn("Creative", width="small"),
        "asset_id": st.column_config.TextColumn(metric_label("asset_id"), width="large"),
        "spend": st.column_config.NumberColumn(metric_label("spend"), format="euro"),
        "cpc": st.column_config.NumberColumn(metric_label("cpc"), format="€%.2f"),
        "cpm": st.column_config.NumberColumn(metric_label("cpm"), format="€%.2f"),
        "cpa": st.column_config.NumberColumn(metric_label("cpa"), format="€%.2f"),
        "roas": st.column_config.NumberColumn(metric_label("roas"), format="%.2f"),
        "ctr_link": st.column_config.NumberColumn(metric_label("ctr_link"), format="percent"),
        "hook_rate": st.column_config.NumberColumn(metric_label("hook_rate"), format="%.1f %%"),
        "impressions": st.column_config.NumberColumn(metric_label("impressions"), format="localized"),
        "purchases": st.column_config.NumberColumn(metric_label("purchases"), format="localized"),
        **{
            c: st.column_config.Column(metric_label(c))
            for c in cols
            if c
            not in (
                "thumbnail",
                "asset_id",
                "spend",
                "cpc",
                "cpm",
                "cpa",
                "roas",
                "ctr_link",
                "hook_rate",
                "impressions",
                "purchases",
            )
        },
    },
)
st.download_button(
    "Download CSV",
    assets.drop(columns=["thumbnail"], errors="ignore").to_csv(index=False).encode("utf-8"),
    file_name=f"paid_creatives_{sel_p.start:%Y%m%d}_{sel_p.end:%Y%m%d}.csv",
    mime="text/csv",
)

# ------------------------------------------------------------------ asset detail
with st.expander("Asset detail"):
    pick = st.selectbox("Asset", sorted(assets["asset_id"].unique()), key="cr_pick")
    rows = ads[ads["asset_id"].eq(pick) & (ads["date"] >= sel_p.start) & (ads["date"] <= sel_p.end)]
    meta = assets[assets["asset_id"].eq(pick)].iloc[0]
    d1, d2 = st.columns([1, 2])
    with d1:
        img = _thumb(meta)
        if img:
            st.image(img, caption=pick, use_container_width=True)
        st.markdown(
            f"**Headline:** {_s(meta.get('title')) or '–'}  \n**Primary text:** {(_s(meta.get('body')) or '–')[:300]}  \n"
            f"**Hook:** {_s(meta.get('hook')) or '–'}  \n**Tags:** {_s(meta.get('visual_subject')) or '–'} · "
            f"{_s(meta.get('claim')) or '–'} · {_s(meta.get('offer')) or '–'} ({_s(meta.get('tag_source'))})"
        )
    with d2:
        daily = rows.groupby(["date", "funnel_stage"], as_index=False)[["spend", "purchase_value"]].sum()
        fig = go.Figure()
        for stg in [s for s in cr.STAGES + ["n/a"] if s in set(daily["funnel_stage"])]:
            dd = daily[daily["funnel_stage"].eq(stg)]
            fig.add_trace(
                go.Bar(x=dd["date"], y=dd["spend"], name=f"Spend · {stg}", marker_color=STAGE_COLOR[stg])
            )
        tot = daily.groupby("date", as_index=False)[["spend", "purchase_value"]].sum()
        fig.add_trace(
            go.Scatter(
                x=tot["date"],
                y=tot["purchase_value"] / tot["spend"].where(tot["spend"] > 0),
                name="ROAS (day)",
                yaxis="y2",
                mode="lines+markers",
                line={"color": BRAND["plum"], "width": 2},
                marker={"size": 5},
            )
        )
        fig.update_layout(
            title="Daily spend by funnel stage and ROAS",
            barmode="stack",
            yaxis2={"overlaying": "y", "side": "right", "showgrid": False, "title": "ROAS"},
        )
        apply_layout(fig, 340)
        fig.update_yaxes(title="Spend (€)")
        st.plotly_chart(fig, use_container_width=True)
    per_adset = rows.groupby(["campaign", "adset_name", "funnel_stage", "goal"], as_index=False)[
        cr.SUM_COLS
    ].sum()
    per_adset = cr.add_ratios(per_adset)
    show_table(
        per_adset[
            [
                "campaign",
                "adset_name",
                "funnel_stage",
                "goal",
                "spend",
                "impressions",
                "ctr_link",
                "cpc",
                "purchases",
                "cpa",
                "roas",
            ]
        ],
        pct_cols=["ctr_link"],
        eur_cols=["spend"],
        num_cols=["impressions", "purchases"],
        extra={"cpc": "€%.2f", "cpa": "€%.2f", "roas": "%.2f"},
    )

# ------------------------------------------------------------------ what works for which goal
section("What works for which goal", None)
if grain.startswith("Asset ×"):
    kpi = st.selectbox(
        "KPI in the cells", ["roas", "ctr_link", "cpa", "cpc", "cpm"], format_func=metric_label, key="cr_mkpi"
    )
    mat_src = assets[assets["funnel_stage"].isin(cr.STAGES)]
    mcols = st.columns(3)
    for col, dim in zip(mcols, ("visual_subject", "claim", "product"), strict=True):
        m = cr.kpi_matrix(mat_src, dim, kpi)
        if m.empty:
            continue
        rows_ = [r for r in sorted(m[dim].unique(), key=lambda x: -m[m[dim].eq(x)]["spend"].sum())]
        stages = [s for s in cr.STAGES if s in set(m["funnel_stage"])]
        z, text, hover = [], [], []
        for r in rows_:
            zr, tr, hr = [], [], []
            for s in stages:
                cell = m[m[dim].eq(r) & m["funnel_stage"].eq(s)]
                if cell.empty or cell["spend"].iloc[0] < min_spend or pd.isna(cell[kpi].iloc[0]):
                    zr.append(None)
                    tr.append("")
                    hr.append("below min spend" if not cell.empty else "no data")
                else:
                    v = float(cell[kpi].iloc[0])
                    zr.append(v)
                    label = (
                        fmt_pct(v, 2)
                        if kpi == "ctr_link"
                        else (fmt_eur(v, 2) if kpi in ("cpa", "cpc", "cpm") else f"{v:.2f}")
                    )
                    tr.append(
                        f"<b>{label}</b><br>n={int(cell['n_assets'].iloc[0])} · {fmt_compact(cell['spend'].iloc[0], '€')}"
                    )
                    hr.append(
                        f"{metric_label(kpi)} {label} · {int(cell['n_assets'].iloc[0])} assets · spend {fmt_eur(cell['spend'].iloc[0])}"
                    )
            z.append(zr)
            text.append(tr)
            hover.append(hr)
        inverse = kpi in ("cpa", "cpc", "cpm")
        scale = [[0, BRAND["light_blue"]], [1, BRAND["plum"]]]
        if inverse:
            scale = [[0, BRAND["plum"]], [1, BRAND["light_blue"]]]
        fig = go.Figure(
            go.Heatmap(
                z=z,
                x=[s.capitalize() for s in stages],
                y=[str(r).replace("_", " ") for r in rows_],
                text=text,
                texttemplate="%{text}",
                customdata=hover,
                hovertemplate="%{y} · %{x}<br>%{customdata}<extra></extra>",
                colorscale=scale,
                showscale=False,
                xgap=3,
                ygap=3,
                hoverongaps=False,
                textfont={"size": 11},
            )
        )
        fig.update_layout(title=metric_label(dim), hovermode="closest")
        apply_layout(fig, 100 + 52 * len(rows_))
        fig.update_xaxes(tickangle=0, side="top", showline=False)
        fig.update_yaxes(autorange="reversed", showgrid=False)
        with col:
            st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Rows = tag or product, columns = funnel stage. Cells recompute the KPI from the summed spend / clicks / "
        "purchases of every asset in the group; cells below the min spend are blank. Darker = better. n = assets, "
        "€ = spend in the cell."
    )

    # scatter prospecting vs retargeting
    fig = go.Figure()
    sc2 = mat_src[mat_src["spend"] > 0]
    smax = float(sc2["spend"].max()) if not sc2.empty else 1.0
    for stg in [s for s in cr.STAGES if s in set(sc2["funnel_stage"])]:
        dd = sc2[sc2["funnel_stage"].eq(stg)]
        fig.add_trace(
            go.Scatter(
                x=dd["ctr_link"],
                y=dd["roas"],
                mode="markers",
                name=stg.capitalize(),
                marker={
                    "size": 8 + 30 * (dd["spend"] / smax) ** 0.5,
                    "color": STAGE_COLOR[stg],
                    "opacity": 0.85,
                    "line": {"width": 1, "color": SURFACE},
                },
                customdata=dd[["asset_id", "spend", "purchases", "verdict", "visual_subject", "claim"]]
                .astype(str)
                .to_numpy(),
                hovertemplate=(
                    "%{customdata[0]}<br>spend €%{customdata[1]} · purchases %{customdata[2]} · %{customdata[3]}<br>"
                    "%{customdata[4]} · %{customdata[5]}<br>CTR %{x:.2%} · ROAS %{y:.2f}<extra>"
                    + stg
                    + "</extra>"
                ),
            )
        )
    if tg.get("roas") is not None and not pd.isna(tg.get("roas")):
        fig.add_hline(
            y=tg["roas"],
            line={"color": INK["axis"], "dash": "dot"},
            annotation_text="ROAS target",
            annotation_position="top left",
        )
    if tg.get("ctr_link") is not None and not pd.isna(tg.get("ctr_link")):
        fig.add_vline(
            x=tg["ctr_link"],
            line={"color": INK["axis"], "dash": "dot"},
            annotation_text="CTR target",
            annotation_position="top right",
        )
    fig.update_layout(
        title="CTR (link) vs ROAS per asset and funnel stage · bubble = spend", hovermode="closest"
    )
    fig.update_xaxes(title="CTR (link)", tickformat=".1%", tickangle=0)
    fig.update_yaxes(title="ROAS (Meta attributed)")
    st.plotly_chart(apply_layout(fig, 440), use_container_width=True)
else:
    st.caption(
        "Switch the grain to *Asset × funnel stage* in the sidebar for the goal matrices and the scatter."
    )

# ------------------------------------------------------------------ tests
section("Creative tests", None)
source_line(
    "From the `Tests` tab of the team input sheet (one row per variant). Variants are summed over all funnel stages "
    "inside the period; a winner needs spend ≥ the min spend on both leading variants and a ≥ "
    f"{cfg['targets'].get('test_winner_lead', 0.1):.0%} lead on the primary KPI."
)
if b.creative_tests.empty:
    st.caption("No tests entered yet (INPUT_SHEET_CSV_URLS → tests tab).")
else:
    all_stages = cr.aggregate_assets(
        b.ads[b.ads["asset_type"].ne("boost_page_promo")], sel_p.start, sel_p.end, by=["asset_id"]
    )
    tt = cr.tests_table(b.creative_tests, all_stages, cfg)
    show_table(
        tt,
        pct_cols=["ctr_link"],
        eur_cols=["spend"],
        num_cols=["purchases", "rank"],
        extra={"cpa": "€%.2f", "roas": "%.2f", "kpi_value": "%.4f"},
        height=min(80 + 36 * len(tt), 520),
    )
