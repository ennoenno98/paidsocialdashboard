"""Page 6 — Paid creatives: which asset / hook works for which goal.

One view per funnel stage (Prospecting / Retargeting), inside it the Meta optimisation event is the primary axis
and the KPI the second. Source: Meta ad-level feed (Windsor ``facebook``) for spend / delivery, Klar
``marketing_flex`` (joined on campaign + ad name) for orders and revenue, Meta 7-day click / 1-day view as the
fallback where Klar has no row. Instagram post boosts, page promotions and organic objectives are excluded.
Tags: naming convention -> LLM vision pass -> manual overrides (team input sheet).
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
    creatives_page_setup,
    fmt_compact,
    fmt_eur,
    fmt_num,
    fmt_pct,
    metric_label,
    period_control,
    section,
    show_table,
    source_line,
)
from src.ingest import windsor as wz  # noqa: E402
from src.transform import creatives as cr  # noqa: E402

b = creatives_page_setup("Paid creatives")
section("Which asset works for which goal", "meta")
sel_p = period_control()
cfg = cr.load_creatives_config()
ROAS_SRC = cfg.get("roas_source", "klar")
source_line(
    f"{sel_p.label} ({sel_p.start:%d.%m.%Y} – {sel_p.end:%d.%m.%Y}); change period and granularity in the sidebar.",
    b.status.get("creatives", ""),
    "Orders, revenue, ROAS and CPA come from Klar (joined on campaign + ad name) where Klar has a row, otherwise "
    "from Meta (7-day click / 1-day view); each row says which (ROAS source). CTR / CPC / CPM are Meta delivery.",
)
if b.ads.empty:
    st.info(
        "No Meta ad-level data: the `facebook__ads` Windsor pull is missing. Run `make refresh` with WINDSOR_API_KEY."
    )
    st.stop()

GOAL_COLOR = {g: PALETTE[i % len(PALETTE)] for i, g in enumerate(cr.GOAL_ORDER)}
GOAL_COLOR["unknown"] = NEUTRAL_FILL
VERDICT_COLOR = {
    "Performing": STATUS["good"],
    "Underperforming": STATUS["critical"],
    "Low data": INK["muted"],
}
VERDICT_ICON = {
    "Performing": "▲ Performing",
    "Underperforming": "▼ Underperforming",
    "Low data": "· Low data",
}
KPI_OPTIONS = ["roas", "cpa", "ctr_link", "cpc", "cpm", "hook_rate"]


def _s(v: object) -> str | None:
    """Scalar -> str, with pandas NA / NaN -> None (``or`` chains choke on pd.NA)."""
    if v is None or (isinstance(v, float) and v != v) or v is pd.NA:
        return None
    return str(v) if str(v).strip() else None


GOAL_SHORT = {
    "conversion": "Conversion",
    "value": "Value",
    "auto": "Auto",
    "landing_page_view": "LPV",
    "link_clicks": "Link clicks",
    "leads": "Leads",
    "thruplay": "ThruPlay",
    "reach": "Reach",
    "impressions": "Impr.",
    "engagement": "Engagement",
}


def _goal_label(g: object) -> str:
    return str(g).replace("_", " ") if _s(g) else "unknown"


def _goal_short(g: object) -> str:
    return GOAL_SHORT.get(str(g), _goal_label(g))


def _fmt_kpi(kpi: str, v: float) -> str:
    if pd.isna(v):
        return "n/a"
    if kpi == "ctr_link":
        return fmt_pct(v, 2)
    if kpi in ("cpa", "cpc", "cpm"):
        return fmt_eur(v, 2)
    if kpi == "hook_rate":
        return f"{v:.1f} %"
    return f"{v:.2f}"


# ------------------------------------------------------------------ sidebar filters
def _opts(col: str) -> list[str]:
    return sorted(x for x in b.ads[col].dropna().astype(str).unique())


with st.sidebar:
    st.markdown("**Creatives**")
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
    kpi_cells = st.selectbox("KPI in the matrices", KPI_OPTIONS, format_func=metric_label, key="cr_mkpi")

ads = b.ads
if f_format:
    ads = ads[ads["asset_type"].isin(f_format)]
if f_product:
    ads = ads[ads["product"].isin(f_product)]
if f_launch:
    ads = ads[ads["launch_month"].isin(f_launch)]


def _assets(start: dt.date, end: dt.date, by: list[str] | None = None) -> pd.DataFrame:
    a = cr.aggregate_assets(ads, start, end, by=by, roas_source=ROAS_SRC)
    a = cr.merge_tags(a, b.creative_tags_llm, b.creative_tags_manual)
    return cr.judge_and_verdict(a, cfg)


n_days = (sel_p.end - sel_p.start).days + 1
assets_all = _assets(sel_p.start, sel_p.end)
prev_all = _assets(sel_p.start - dt.timedelta(days=n_days), sel_p.start - dt.timedelta(days=1))

# tag filters (after aggregation: tags are per asset)
c1, c2, c3 = st.columns(3)
with c1:
    f_vis = st.multiselect("Visual subject", cr.TAG_VOCAB["visual_subject"] + ["untagged"], key="cr_vis")
with c2:
    f_claim = st.multiselect("Claim / hook", cr.TAG_VOCAB["claim"] + ["untagged"], key="cr_claim")
with c3:
    f_offer = st.multiselect("Offer", cr.TAG_VOCAB["offer"], key="cr_offer")


def _apply_row_filters(a: pd.DataFrame) -> pd.DataFrame:
    for col, chosen in (("visual_subject", f_vis), ("claim", f_claim), ("offer", f_offer)):
        if chosen:
            a = a[a[col].fillna("untagged").isin(chosen)]
    if f_status.startswith("Active"):
        a = a[a["active"]]
    elif f_status == "Off":
        a = a[~a["active"]]
    return a[a["spend"].fillna(0) >= min_spend]


assets_all = _apply_row_filters(assets_all)
prev_all = _apply_row_filters(prev_all)
if assets_all.empty:
    st.info("No assets in this period with these filters.")
    st.stop()
tg = assets_all.attrs.get("targets", {})
st.caption(
    f"Verdict: judged on the KPI of the row's optimisation goal (conversion / value → ROAS, traffic / leads → CTR). "
    f"Targets = account average of the selection (pin them in config/creatives.yaml): ROAS {fmt_num(tg.get('roas'), 2)} · "
    f"CTR {fmt_pct(tg.get('ctr_link'))} · CPA {fmt_eur(tg.get('cpa'), 2)} · min spend for a verdict "
    f"€{assets_all.attrs.get('min_spend', 100):,.0f}."
)


# ------------------------------------------------------------------ helpers
def _thumb(row: pd.Series) -> str | None:
    for cid in str(_s(row.get("creative_ids")) or "").split(","):
        p = wz.thumbnail_path(cid.strip())
        if p is not None:
            data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
            return f"data:image/jpeg;base64,{data}"
    return _s(row.get("image_url")) or _s(row.get("thumbnail_url"))


def _tot(d: pd.DataFrame) -> dict[str, float]:
    s = d[["spend", "orders", "link_clicks", "impressions"]].sum()
    rev = d["klar_gross_revenue"].where(d["roas_source"].eq("klar"), d["purchase_value"]).fillna(0).sum()
    return {
        "spend": s["spend"],
        "orders": s["orders"],
        "roas": rev / s["spend"] if s["spend"] else float("nan"),
        "cpa": s["spend"] / s["orders"] if s["orders"] else float("nan"),
        "ctr": s["link_clicks"] / s["impressions"] if s["impressions"] else float("nan"),
    }


def _delta(cur: dict[str, float], old: dict[str, float], k: str) -> str | None:
    a, o = cur[k], old[k]
    if pd.isna(a) or pd.isna(o) or o == 0:
        return None
    return f"{(a - o) / o:+.0%} vs previous {n_days} days"


TABLE_COLS = [
    "thumbnail",
    "asset_id",
    "goal",
    "product",
    "asset_type",
    "visual_subject",
    "claim",
    "offer",
    "hook",
    "spend",
    "orders",
    "roas",
    "cpa",
    "roas_source",
    "ctr_link",
    "cpc",
    "cpm",
    "impressions",
    "hook_rate",
    "roas_meta",
    "judge_kpi",
    "verdict",
    "launch_month",
    "variant",
    "n_adsets",
    "active",
    "tag_source",
]
COL_CFG = {
    "thumbnail": st.column_config.ImageColumn("Creative", width="small"),
    "asset_id": st.column_config.TextColumn(metric_label("asset_id"), width="large"),
    "goal": st.column_config.TextColumn("Optimisation goal"),
    "spend": st.column_config.NumberColumn(metric_label("spend"), format="euro"),
    "orders": st.column_config.NumberColumn("Orders", format="localized"),
    "roas": st.column_config.NumberColumn("ROAS", format="%.2f"),
    "cpa": st.column_config.NumberColumn("CPA (€)", format="€%.2f"),
    "roas_source": st.column_config.TextColumn("ROAS source"),
    "roas_meta": st.column_config.NumberColumn("ROAS (Meta)", format="%.2f"),
    "cpc": st.column_config.NumberColumn(metric_label("cpc"), format="€%.2f"),
    "cpm": st.column_config.NumberColumn(metric_label("cpm"), format="€%.2f"),
    "ctr_link": st.column_config.NumberColumn(metric_label("ctr_link"), format="percent"),
    "hook_rate": st.column_config.NumberColumn(metric_label("hook_rate"), format="%.1f %%"),
    "impressions": st.column_config.NumberColumn(metric_label("impressions"), format="localized"),
}


def _asset_table(a: pd.DataFrame, key: str) -> None:
    tbl = a.copy()
    tbl["thumbnail"] = tbl.apply(_thumb, axis=1)
    tbl["verdict"] = tbl["verdict"].map(VERDICT_ICON).fillna(tbl["verdict"])
    for c in ("visual_subject", "claim", "offer", "hook", "product", "variant", "launch_month"):
        tbl[c] = tbl[c].astype(object).where(tbl[c].notna(), "")
    tbl["goal"] = tbl["goal"].map(_goal_label)
    order = {g: i for i, g in enumerate(cr.GOAL_ORDER)}
    tbl["_o"] = tbl["goal"].str.replace(" ", "_").map(order).fillna(99)
    tbl = tbl.sort_values(["_o", "spend"], ascending=[True, False]).drop(columns="_o")
    cols = [c for c in TABLE_COLS if c in tbl.columns]
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
        height=min(90 + 36 * len(tbl), 520),
        column_config={**{c: st.column_config.Column(metric_label(c)) for c in cols}, **COL_CFG},
        key=f"tbl_{key}",
    )
    st.download_button(
        "Download CSV",
        a.to_csv(index=False).encode("utf-8"),
        file_name=f"paid_creatives_{key}_{sel_p.start:%Y%m%d}_{sel_p.end:%Y%m%d}.csv",
        mime="text/csv",
        key=f"dl_{key}",
    )


def _matrices(a: pd.DataFrame, key: str) -> None:
    kpi = kpi_cells
    inverse = kpi in ("cpa", "cpc", "cpm")
    top = st.columns(2)
    slots = [top[0], top[1], st.container()]
    for col, dim in zip(slots, ("visual_subject", "claim", "product"), strict=True):
        m = cr.kpi_matrix(a, dim, kpi, col_dim="goal", roas_source=ROAS_SRC)
        if m.empty:
            continue
        rows_ = sorted(m[dim].unique(), key=lambda x: -m[m[dim].eq(x)]["spend"].sum())
        goals = [g for g in cr.GOAL_ORDER if g in set(m["goal"])] + sorted(
            set(m["goal"].dropna()) - set(cr.GOAL_ORDER)
        )
        z, text, hover = [], [], []
        for r in rows_:
            zr, tr, hr = [], [], []
            for g in goals:
                cell = m[m[dim].eq(r) & m["goal"].eq(g)]
                if cell.empty or cell["spend"].iloc[0] < min_spend or pd.isna(cell[kpi].iloc[0]):
                    zr.append(None)
                    tr.append("")
                    hr.append("below min spend" if not cell.empty else "no data")
                else:
                    v = float(cell[kpi].iloc[0])
                    zr.append(v)
                    tr.append(
                        f"<b>{_fmt_kpi(kpi, v)}</b><br>n={int(cell['n_assets'].iloc[0])} · {fmt_compact(cell['spend'].iloc[0], '€')}"
                    )
                    hr.append(
                        f"{metric_label(kpi)} {_fmt_kpi(kpi, v)} · {int(cell['n_assets'].iloc[0])} assets · spend {fmt_eur(cell['spend'].iloc[0])}"
                    )
            z.append(zr)
            text.append(tr)
            hover.append(hr)
        scale = [[0, BRAND["light_blue"]], [1, BRAND["plum"]]]
        if inverse:
            scale = [[0, BRAND["plum"]], [1, BRAND["light_blue"]]]
        fig = go.Figure(
            go.Heatmap(
                z=z,
                x=[_goal_short(g) for g in goals],
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
            st.plotly_chart(fig, use_container_width=True, key=f"mx_{key}_{dim}")
    st.caption(
        "Rows = tag or product, columns = Meta optimisation goal. Cells recompute the KPI from the summed spend / "
        "clicks / orders of every asset in the group; cells below the min spend are blank. Darker = better. "
        "n = assets, € = spend in the cell."
    )


def _scatter(a: pd.DataFrame, key: str) -> None:
    fig = go.Figure()
    sc2 = a[a["spend"] > 0]
    smax = float(sc2["spend"].max()) if not sc2.empty else 1.0
    goals = [g for g in cr.GOAL_ORDER if g in set(sc2["goal"])] + sorted(
        set(sc2["goal"].dropna()) - set(cr.GOAL_ORDER)
    )
    for g in goals:
        dd = sc2[sc2["goal"].eq(g)]
        fig.add_trace(
            go.Scatter(
                x=dd["ctr_link"],
                y=dd["roas"],
                mode="markers",
                name=_goal_label(g),
                marker={
                    "size": 8 + 30 * (dd["spend"] / smax) ** 0.5,
                    "color": GOAL_COLOR.get(g, NEUTRAL_FILL),
                    "opacity": 0.85,
                    "line": {"width": 1, "color": SURFACE},
                },
                customdata=dd[
                    ["asset_id", "spend", "orders", "verdict", "visual_subject", "claim", "roas_source"]
                ]
                .astype(str)
                .to_numpy(),
                hovertemplate=(
                    "%{customdata[0]}<br>spend €%{customdata[1]} · orders %{customdata[2]} · %{customdata[3]}<br>"
                    "%{customdata[4]} · %{customdata[5]}<br>CTR %{x:.2%} · ROAS %{y:.2f} (%{customdata[6]})<extra></extra>"
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
        title="CTR (link) vs ROAS per asset and optimisation goal · bubble = spend", hovermode="closest"
    )
    apply_layout(fig, 420)
    fig.update_xaxes(title="CTR (link)", tickformat=".1%", tickangle=0)
    fig.update_yaxes(title=f"ROAS ({'Klar, Meta fallback' if ROAS_SRC == 'klar' else 'Meta attributed'})")
    st.plotly_chart(fig, use_container_width=True, key=f"sc_{key}")


def _detail(a: pd.DataFrame, stage: str, key: str) -> None:
    with st.expander("Asset detail"):
        pick = st.selectbox("Asset", sorted(a["asset_id"].unique()), key=f"pick_{key}")
        rows = ads[
            ads["asset_id"].eq(pick)
            & ads["funnel_stage"].eq(stage)
            & (ads["date"] >= sel_p.start)
            & (ads["date"] <= sel_p.end)
        ]
        meta = a[a["asset_id"].eq(pick)].iloc[0]
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
            daily = rows.groupby(["date", "goal"], as_index=False)[
                ["spend", "purchase_value", "klar_gross_revenue", "klar_cost"]
            ].sum(min_count=1)
            fig = go.Figure()
            for g in [g for g in cr.GOAL_ORDER if g in set(daily["goal"])]:
                dd = daily[daily["goal"].eq(g)]
                fig.add_trace(
                    go.Bar(
                        x=dd["date"],
                        y=dd["spend"],
                        name=f"Spend · {_goal_label(g)}",
                        marker_color=GOAL_COLOR.get(g),
                    )
                )
            tot = daily.groupby("date", as_index=False)[
                ["spend", "purchase_value", "klar_gross_revenue", "klar_cost"]
            ].sum(min_count=1)
            rev = (
                tot["klar_gross_revenue"].where(tot["klar_cost"].fillna(0) > 0, tot["purchase_value"])
                if ROAS_SRC == "klar"
                else tot["purchase_value"]
            )
            fig.add_trace(
                go.Scatter(
                    x=tot["date"],
                    y=rev / tot["spend"].where(tot["spend"] > 0),
                    name="ROAS (day)",
                    yaxis="y2",
                    mode="lines+markers",
                    line={"color": BRAND["plum"], "width": 2},
                    marker={"size": 5},
                )
            )
            fig.update_layout(
                title="Daily spend by optimisation goal and ROAS",
                barmode="stack",
                yaxis2={"overlaying": "y", "side": "right", "showgrid": False, "title": "ROAS"},
            )
            apply_layout(fig, 340)
            fig.update_yaxes(title="Spend (€)")
            st.plotly_chart(fig, use_container_width=True, key=f"daily_{key}")
        per_adset = rows.groupby(["campaign", "adset_name", "goal"], as_index=False)[cr.SUM_COLS].sum(
            min_count=1
        )
        per_adset = cr.add_ratios(per_adset, ROAS_SRC)
        show_table(
            per_adset[
                [
                    "campaign",
                    "adset_name",
                    "goal",
                    "spend",
                    "impressions",
                    "ctr_link",
                    "cpc",
                    "orders",
                    "cpa",
                    "roas",
                    "roas_source",
                ]
            ],
            pct_cols=["ctr_link"],
            eur_cols=["spend"],
            num_cols=["impressions", "orders"],
            extra={"cpc": "€%.2f", "cpa": "€%.2f", "roas": "%.2f"},
        )


def _stage_view(stage: str) -> None:
    a = assets_all[assets_all["funnel_stage"].eq(stage)]
    p = prev_all[prev_all["funnel_stage"].eq(stage)]
    if a.empty:
        st.info(f"No {stage} assets in this period with these filters.")
        return
    cur, old = _tot(a), _tot(p)
    t = st.columns(6)
    t[0].metric("Spend", fmt_compact(cur["spend"], "€"), _delta(cur, old, "spend"))
    t[1].metric("Orders", fmt_num(cur["orders"]), _delta(cur, old, "orders"))
    t[2].metric("ROAS", fmt_num(cur["roas"], 2), _delta(cur, old, "roas"))
    t[3].metric("CPA", fmt_eur(cur["cpa"], 2), _delta(cur, old, "cpa"), delta_color="inverse")
    t[4].metric("CTR (link)", fmt_pct(cur["ctr"]), _delta(cur, old, "ctr"))
    vc = a["verdict"].value_counts()
    t[5].metric(
        "Performing / under / low data",
        f"{int(vc.get('Performing', 0))} / {int(vc.get('Underperforming', 0))} / {int(vc.get('Low data', 0))}",
    )
    goals_here = [g for g in cr.GOAL_ORDER if g in set(a["goal"])] + sorted(
        set(a["goal"].dropna()) - set(cr.GOAL_ORDER)
    )
    st.caption(
        "Optimisation goals in this view: "
        + " · ".join(
            f"{_goal_label(g)} {fmt_compact(a.loc[a['goal'].eq(g), 'spend'].sum(), '€')}" for g in goals_here
        )
        + f" · ROAS from Klar on {a.loc[a['roas_source'].eq('klar'), 'spend'].sum() / a['spend'].sum():.0%} of spend."
    )
    f_goal = st.multiselect("Optimisation goal", goals_here, format_func=_goal_label, key=f"goal_{stage}")
    if f_goal:
        a = a[a["goal"].isin(f_goal)]
    section("Assets by optimisation goal", None)
    _asset_table(a, stage)
    _detail(a, stage, stage)
    section("What works for which goal", None)
    _matrices(a, stage)
    _scatter(a, stage)


stages = [s for s in cr.STAGES if s in set(assets_all["funnel_stage"])]
tabs = st.tabs([s.capitalize() if s != "unknown" else "Unknown stage" for s in stages])
for tab, stage in zip(tabs, stages, strict=True):
    with tab:
        if stage == "unknown":
            st.caption(
                "Ad sets no funnel-stage rule matched; add a rule to config/creatives.yaml (see Data quality)."
            )
        _stage_view(stage)

# ------------------------------------------------------------------ tests
section("Creative tests", None)
source_line(
    "From the `Tests` tab of the team input sheet (one row per variant). Variants are summed over all funnel stages "
    "and goals inside the period; a winner needs spend ≥ the min spend on both leading variants and a ≥ "
    f"{cfg['targets'].get('test_winner_lead', 0.1):.0%} lead on the primary KPI."
)
if b.creative_tests.empty:
    st.caption("No tests entered yet (INPUT_SHEET_CSV_URLS → tests tab).")
else:
    all_stages = cr.aggregate_assets(b.ads, sel_p.start, sel_p.end, by=["asset_id"], roas_source=ROAS_SRC)
    tt = cr.tests_table(b.creative_tests, all_stages, cfg)
    show_table(
        tt,
        pct_cols=["ctr_link"],
        eur_cols=["spend"],
        num_cols=["purchases", "rank"],
        extra={"cpa": "€%.2f", "roas": "%.2f", "kpi_value": "%.4f"},
        height=min(80 + 36 * len(tt), 520),
    )
