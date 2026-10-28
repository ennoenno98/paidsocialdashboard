"""Shared helpers for the Streamlit pages: cached bundle, palette, formatting, chart layout."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.branding import BRAND_LOGOS, account_html, heading_html  # noqa: E402
from src.pipeline import Bundle, CreativesBundle, build_bundle, build_creatives_bundle  # noqa: E402
from src.transform import periods as pr  # noqa: E402

# Vanatari Corporate Design 2026 (brand booklet): plum = text, orange = highlight, beige / light blue = surfaces.
BRAND = {
    "plum": "#3c1826",
    "orange": "#ff5c3e",
    "blue": "#6c91cc",
    "pink": "#f5c0fb",
    "light_blue": "#e3eef6",
    "beige": "#fbf7f2",
}
SURFACE = BRAND["beige"]  # Streamlit background (.streamlit/config.toml) == chart surface
# Categorical palette: the four brand hues (orange, blue, plum, pink) stepped in OKLCH so every slot clears the
# dataviz validator on the beige surface (slots 1-4 all-pairs, slots 1-8 adjacent). Fixed slot order, never cycled;
# entity -> slot is stable across filters. Validated: `node .../dataviz/scripts/validate_palette.js --surface #fbf7f2`.
PALETTE = ["#f05a3e", "#2f66be", "#872c53", "#b16fba", "#a11e02", "#6ca4fe", "#c9688d", "#73357b"]
ACCOUNT_ORDER = [  # API-backed Instagram accounts first (they share charts), sheet-only TikTok accounts after
    "vegavero/instagram/IT",
    "vegavero/instagram/DE",
    "wowtamins/instagram/DE",
    "jasnum/instagram/IT",
    "vegavero/tiktok/IT",
    "vegavero/tiktok/DE",
    "wowtamins/tiktok/DE",
    "vanatari/tiktok/INT",
]
ACCOUNT_COLORS = {a: PALETTE[i] for i, a in enumerate(ACCOUNT_ORDER)}
NEUTRAL_FILL = "#ae9ea0"  # plum 40 % on beige: the non-identity segment (e.g. boosted reach) in stacked bars
# Status colours stay reserved (never a series colour) and always ship with a label/icon, never colour alone.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
# Ink = plum tints on beige (100 / 80 / 60 % for text, 25 % axis, 10 % grid).
INK = {
    "primary": BRAND["plum"],
    "secondary": "#624549",
    "muted": "#887178",
    "grid": "#e8e1de",
    "axis": "#cbbfbf",
}
FONT_BODY = 'Satoshi, system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_HEAD = "Literata, Georgia, serif"
FONT_CSS = """
<style>
@import url('https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Literata:wght@500;600&display=swap');
</style>
"""
# Readable labels for metric / column keys (charts, selectors, table headers). Unknown keys fall back to
# "snake_case" -> "Snake case".
METRIC_LABELS: dict[str, str] = {
    "account": "Account",
    "date": "Date",
    "period": "Period",
    "year": "Year",
    "month": "Month",
    "n_days": "Days",
    "reach": "Reach",
    "reach_daily_sum": "Reach (daily sum)",
    "views": "Views",
    "video_views": "Video views",
    "likes": "Likes",
    "like_count": "Likes",
    "comments": "Comments",
    "comments_count": "Comments",
    "saves": "Saves",
    "saved": "Saves",
    "shares": "Shares",
    "reposts": "Reposts",
    "follows": "Follows",
    "unfollows": "Unfollows",
    "net_follows": "Net follows",
    "followers": "Followers",
    "new_followers": "New followers",
    "new_followers_days": "Days with follower data",
    "total_interactions": "Interactions",
    "accounts_engaged": "Accounts engaged",
    "engagements": "Engagements",
    "er": "ER",
    "er_sheet": "ER (sheet)",
    "er_sheet_frac": "ER (sheet)",
    "er_diff_pp": "ER diff (pp)",
    "er_mean": "ER (mean per post)",
    "er_weighted": "ER (reach-weighted)",
    "er_basis": "ER basis",
    "er_denominator": "ER denominator",
    "n_posts": "Posts",
    "n_posts_with_er": "Posts with ER",
    "post_name": "Post",
    "caption": "Caption",
    "permalink": "Post",
    "media_product_type": "Type",
    "media_type": "Media",
    "media_id": "Media ID",
    "format": "Format",
    "pillar": "Pillar",
    "cw": "CW",
    "boost_spend": "Boost spend (€)",
    "ad_spent": "Ad spend (€)",
    "boost_total_cost": "Boost cost (€)",
    "spend": "Spend (€)",
    "spend_source": "Spend source",
    "n_boosted_posts": "Boosted posts",
    "boosted_reach": "Boosted reach",
    "boosted_reach_daily_sum": "Boosted reach (daily sum)",
    "boosted_reach_share": "Boosted reach share",
    "boosted_impressions": "Boosted impressions",
    "boosted_clicks": "Boosted clicks",
    "boosted_link_clicks": "Boosted link clicks",
    "boosted_post_engagement": "Boosted post engagement",
    "boosted_video_views": "Boosted video views",
    "organic_reach": "Organic reach",
    "organic_net_follows": "Organic net follows",
    "new_followers_boosted": "New followers (boosted posts)",
    "cpm": "CPM (€)",
    "cpm_boosted": "Boosted CPM (€)",
    "cpm_klar": "CPM (Klar, €)",
    "cost_per_new_follower": "Cost per new follower (€)",
    "cost_per_net_follow": "Cost per net follow (€)",
    "impressions": "Impressions",
    "clicks": "Clicks",
    "link_clicks": "Link clicks",
    "post_engagement": "Post engagement",
    "campaign": "Campaign",
    "first_day": "First day",
    "last_day": "Last day",
    "days": "Days",
    "mapped": "Mapped",
    "boost_spend_monthly_sheet": "Boost spend, monthly sheet (€)",
    "boost_spend_susy": "Boost spend, Susy (€)",
    "delta_susy_minus_sheet": "Δ Susy − sheet (€)",
    "boost_spend_meta": "Boost spend, Meta API (€)",
    "delta_meta_minus_sheet": "Δ Meta − sheet (€)",
    "boost_budget": "Budget (€)",
    "agree": "Agree",
    "influencer_name": "Creator",
    "creator_handle": "Handle",
    "handle": "Handle",
    "platform": "Platform",
    "type_of_partnership": "Deal type",
    "category": "Category",
    "discount_codes": "Codes",
    "discount_code": "Code",
    "costs": "Costs (€)",
    "fixed_costs": "Fixed costs (€)",
    "var_costs": "Variable costs (€)",
    "orders": "Orders",
    "net_revenue": "Net revenue (€)",
    "gross_revenue": "Gross revenue (€)",
    "new_customers": "New customers",
    "roas": "ROAS",
    "cac": "CAC (€)",
    "cpo": "CPO (€)",
    "reach_klar": "Reach (Klar)",
    "reach_source": "Reach source",
    "reach_used": "Reach used",
    "followers_klar": "Followers (Klar)",
    "followers_ig": "Followers (Instagram)",
    "creator_followers": "Followers",
    "creator_deal": "Deal",
    "interactions_per_post": "Interactions per post",
    "posts_per_30d": "Posts per 30 days",
    "last_post": "Last post",
    "scannable": "Scannable",
    "active_recent": "Active recently",
    "relationship": "Relationship",
    "owner_username": "Owner",
    "collaborators": "Collaborators",
    "n_stories": "Stories",
    "story_reach_sum": "Story reach (sum)",
    "story_views_sum": "Story views (sum)",
    "story_replies": "Story replies",
    "story_shares": "Story shares",
    "story_interactions": "Story interactions",
    "story_exits": "Story exits",
    "story_taps_forward": "Taps forward",
    "story_taps_back": "Taps back",
    "story_swipe_forward": "Swipes forward",
    "story_exit_rate": "Exit rate",
    "story_reach_per_story": "Reach per story",
    "story_id": "Story",
    "exits": "Exits",
    "taps_forward": "Taps forward",
    "taps_back": "Taps back",
    "swipe_forward": "Swipes forward",
    "interactions": "Interactions",
    "replies": "Replies",
    "markets": "Markets",
    "post_types": "Post types",
    "post_type": "Post type",
    "n_campaigns": "Campaigns (sheet)",
    "n_campaigns_with_reach": "Campaigns with reach",
    "n_campaigns_with_link": "Campaigns with post link",
    "in_klar_sheet": "In Klar sheet",
    "link_to_profile": "Profile",
    "link_to_post": "Post link",
    "fixed_costs_sheet": "Fixed costs, sheet (€)",
    "reach_sheet": "Reach (sheet)",
    "followers_sheet": "Followers (sheet)",
    "brands": "Brands",
    "brand": "Brand",
    "campaign_name": "Campaign",
    "posting_date": "Posting date",
    "end_date": "End date",
    "row": "Sheet row",
    "status_ok": "Imported",
    "quarter": "Quarter",
    "goal": "Goal",
    "tier": "Tier",
    "tier_source": "Tier source",
    "industry": "Industry",
    "category_ws": "Industry (worksheet)",
    "goal_ws": "Goal (worksheet)",
    "followers_ws": "Followers (worksheet)",
    "dimension": "Breakdown",
    "value": "Value",
    "share": "Share of spend",
    "n_creators": "Creators",
    "costs_with_reach": "Spend with reach (€)",
    "reach_coverage": "Spend with reach",
    "costs_performance": "Performance spend (€)",
    "costs_awareness": "Awareness spend (€)",
    "roas_performance": "ROAS performance",
    "roas_awareness": "ROAS awareness",
    "share_performance": "Performance share",
    "follower_growth_pct": "Follower growth",
    "source": "Source",
    # paid creatives
    "asset_id": "Asset (ad name)",
    "ad_name": "Ad name",
    "funnel_stage": "Funnel stage",
    "goal_mix": "Optimisation goals (spend share)",
    "n_adsets": "Ad sets",
    "adsets": "Ad set names",
    "adset_name": "Ad set",
    "creative_ids": "Creative IDs",
    "thumbnail": "Creative",
    "product": "Product",
    "concept": "Concept",
    "style": "Style",
    "version": "Version",
    "launch_month": "Launch month",
    "variant": "Variant",
    "asset_type": "Asset type",
    "visual_subject": "Visual subject",
    "claim": "Claim / hook",
    "offer": "Offer",
    "hook": "Hook (first 3 s)",
    "tag_source": "Tag source",
    "lpv": "Landing page views",
    "outbound_clicks": "Outbound clicks",
    "purchases": "Purchases",
    "purchase_value": "Purchase value (€)",
    "ctr_link": "CTR (link)",
    "cpc": "CPC (€)",
    "cpa": "CPA (€)",
    "lpv_rate": "LPV rate",
    "cvr": "CVR (LPV → purchase)",
    "hook_rate": "Hook rate (3 s)",
    "thruplay_rate": "ThruPlay rate",
    "video_plays": "Video plays",
    "thruplays": "ThruPlays",
    "judge_kpi": "Judged on",
    "target": "Target",
    "kpi_value": "KPI value",
    "verdict": "Verdict",
    "active": "Active",
    "n_assets": "Assets",
    "test_id": "Test",
    "test_name": "Test name",
    "variable": "Variable",
    "hypothesis": "Hypothesis",
    "primary_kpi": "Primary KPI",
    "rank": "Rank",
    "result": "Result",
    "learning": "Learning / next step",
    "spend_feed": "Spend, Windsor feed (€)",
    "spend_export": "Spend, Ads Manager export (€)",
    "delta": "Δ feed − export (€)",
    "body": "Primary text",
    "title": "Headline",
}
PLATFORM_SHORT = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}


def metric_label(key: object) -> str:
    k = str(key)
    return METRIC_LABELS.get(k, k.replace("_", " ").capitalize())


def quarter_of(period_type: str, year: int, period: int) -> str:
    """``Q4 2026`` for a month or ISO week (week -> month of its Thursday)."""
    month = (
        int(period) if period_type == "month" else dt.date.fromisocalendar(int(year), int(period), 4).month
    )
    return f"Q{(month - 1) // 3 + 1} {int(year)}"


def with_quarter(df: pd.DataFrame, period_type: str | None = None) -> pd.DataFrame:
    """Add a ``quarter`` column from (year, period[, period_type]) or from a ``date``/``timestamp`` column."""
    d = df.copy()
    if d.empty:
        d["quarter"] = pd.Series(dtype=str)
        return d
    if "period" in d.columns and "year" in d.columns:
        pt = d["period_type"] if "period_type" in d.columns else pd.Series(period_type, index=d.index)
        d["quarter"] = [
            quarter_of(str(t), int(y), int(q)) for t, y, q in zip(pt, d["year"], d["period"], strict=True)
        ]
        return d
    col = "timestamp" if "timestamp" in d.columns else "date"
    ts = pd.to_datetime(d[col], utc=True, errors="coerce")
    d["quarter"] = [
        f"Q{(int(m) - 1) // 3 + 1} {int(y)}" if pd.notna(y) else None
        for y, m in zip(ts.dt.year, ts.dt.month, strict=True)
    ]
    return d


def quarter_filter(
    df: pd.DataFrame, key: str, period_type: str | None = None, label: str = "Period"
) -> pd.DataFrame:
    """Selectbox 'All periods / Q4 2026 / Q3 2026 …' (newest first); returns the filtered frame."""
    d = with_quarter(df, period_type)
    quarters = sorted(
        {q for q in d["quarter"].dropna().unique()}, key=lambda q: (int(q[3:]), int(q[1])), reverse=True
    )
    choice = st.selectbox(label, ["All periods", *quarters], index=0, key=key)
    return d if choice == "All periods" else d[d["quarter"].eq(choice)]


def account_label(account: object) -> str:
    """``vegavero/instagram/IT`` -> ``Vegavero · Instagram · IT``."""
    parts = str(account).split("/")
    if len(parts) != 3:
        return str(account)
    brand, platform, market = parts
    return f"{brand.capitalize()} · {PLATFORM_SHORT.get(platform, platform.capitalize())} · {market}"


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_resource(ttl=6 * 3600, show_spinner="Loading Windsor, Klar and workbook data…")
def get_bundle() -> Bundle:
    return build_bundle()


def page_setup(title: str) -> Bundle:
    st.set_page_config(page_title=f"Vanatari Social · {title}", layout="wide", page_icon="📊")
    st.html(
        FONT_CSS
    )  # loads Satoshi (body) + Literata (headings); families are set in .streamlit/config.toml
    st.logo(BRAND_LOGOS["vanatari"], size="large", link="https://vanatari.com")
    b = get_bundle()
    st.title(title)
    if b.is_fixture:
        st.warning(
            "Showing **synthetic fixture data**. Drop the real workbook at `data/Social_Media.xlsx` "
            "(or set `SOCIAL_XLSX`) and run `make refresh`.",
            icon="⚠️",
        )
    return b


@st.cache_resource(ttl=6 * 3600, show_spinner="Loading Meta ads and Klar attribution…")
def get_creatives_bundle() -> CreativesBundle:
    return build_creatives_bundle()


def creatives_page_setup(title: str) -> CreativesBundle:
    """Standalone Paid creatives app: same chrome, lighter bundle (no workbook / organic / influencer sources)."""
    st.set_page_config(page_title=f"Vegavero Paid Creatives · {title}", layout="wide", page_icon="🎨")
    st.html(FONT_CSS)
    st.logo(BRAND_LOGOS["vegavero"], size="large", link="https://vegavero.it")
    b = get_creatives_bundle()
    st.title(title)
    if b.is_fixture:
        st.warning(
            "Showing **synthetic fixture data**. Run `make refresh` with `WINDSOR_API_KEY` (and drop Klar "
            "marketing_flex exports into `data/raw/klar_marketing/`).",
            icon="⚠️",
        )
    return b


def account_header(account: str) -> None:
    """Brand logo + platform glyph + market instead of the raw ``brand/platform/market`` key."""
    st.markdown(account_html(account), unsafe_allow_html=True)


def section(text: str, platform: str | None = None) -> None:
    """Subheader with a platform glyph (Instagram / TikTok / Meta) in front."""
    st.markdown(heading_html(text, platform), unsafe_allow_html=True)


PERIOD_MODES = {
    "latest": "Latest complete",
    "previous": "The one before",
    "last_n": "Last 4 weeks / 3 months / 4 quarters",
    "ytd": "Year to date",
    "last_12m": "Last 12 months",
    "specific": "Pick one",
    "custom": "Custom range",
}


def period_control() -> pr.PeriodSel:
    """Sidebar control shared by every page: granularity (week / month / quarter) and the date range.
    Stored in session_state so it carries across pages."""
    with st.sidebar:
        st.markdown("**Period**")
        gran = st.radio("Granularity", list(pr.GRANULARITIES), horizontal=True, key="g_gran", index=1)
        mode = st.selectbox("Range", list(PERIOD_MODES), format_func=PERIOD_MODES.get, key="g_mode", index=0)
        today = dt.date.today()
        year = number = None
        custom = None
        if mode == "specific":
            ptype = pr.PTYPE[gran]
            ly, lp = pr.latest_complete(ptype, today)
            year = st.selectbox(
                "Year", list(range(today.year, today.year - 3, -1)), key="g_year", index=today.year - ly
            )
            maxn = {"cw": 53, "month": 12, "quarter": 4}[ptype]
            number = st.selectbox(
                {"cw": "ISO week", "month": "Month", "quarter": "Quarter"}[ptype],
                list(range(1, maxn + 1)),
                index=min(lp, maxn) - 1,
                key=f"g_num_{ptype}",
                format_func=lambda n, pt=ptype, y=year: pr.label_of(pt, y, n),
            )
        elif mode == "custom":
            c = st.date_input(
                "From / to", (today - dt.timedelta(days=90), today - dt.timedelta(days=1)), key="g_custom"
            )
            if isinstance(c, tuple) and len(c) == 2:
                custom = (c[0], c[1])
            else:
                custom = (today - dt.timedelta(days=90), today - dt.timedelta(days=1))
        sel = pr.resolve_period(gran, mode, today, year=year, number=number, custom=custom)
        st.caption(f"{sel.label} · {sel.start:%d.%m.%Y} – {sel.end:%d.%m.%Y}")
    return sel


def source_line(*parts: str) -> None:
    st.caption(" · ".join(p for p in parts if p))


def fmt_num(x: float | None, decimals: int = 0) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    return f"{x:,.{decimals}f}"


def fmt_pct(x: float | None, decimals: int = 2) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    return f"{x * 100:.{decimals}f}%"


def fmt_compact(x: float | None, prefix: str = "", decimals_small: int = 0) -> str:
    """82.6k / 1.59M style for metric tiles (st.metric truncates long values)."""
    if x is None or pd.isna(x):
        return "n/a"
    ax = abs(float(x))
    if ax >= 1_000_000:
        return f"{prefix}{x / 1_000_000:.2f}M"
    if ax >= 10_000:
        return f"{prefix}{x / 1_000:.1f}k"
    return f"{prefix}{x:,.{decimals_small}f}"


def fmt_eur(x: float | None, decimals: int = 0) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    return f"€{x:,.{decimals}f}"


def period_label(period_type: str, year: int, period: int) -> str:
    return pr.label_of(period_type, year, period)


def apply_layout(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 8, "r": 8, "t": 72, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT_BODY, "color": INK["secondary"], "size": 12},
        title={
            "font": {"family": FONT_HEAD, "color": INK["primary"], "size": 15},
            "yref": "container",
            "y": 0.99,
            "yanchor": "top",
            "x": 0,
            "xref": "paper",
        },
        # legend sits between title and plot, never under the (rotated) tick labels
        legend={"orientation": "h", "y": 1.0, "yanchor": "bottom", "x": 0, "xanchor": "left", "title": None},
        hovermode="x unified",
        hoverlabel={"namelength": -1},
        colorway=PALETTE,
    )
    # 1px surface-coloured ring on bars = the gap between stacked segments / adjacent bars (dataviz mark spec).
    fig.update_traces(marker_line={"color": SURFACE, "width": 1}, selector={"type": "bar"})
    fig.update_xaxes(showgrid=False, linecolor=INK["axis"], tickcolor=INK["axis"], tickangle=-45, nticks=18)
    fig.update_yaxes(gridcolor=INK["grid"], zerolinecolor=INK["axis"], linecolor="rgba(0,0,0,0)")
    return fig


def account_filter(options: list[str], key: str, default_all: bool = True) -> list[str]:
    opts = [a for a in ACCOUNT_ORDER if a in options] + sorted(set(options) - set(ACCOUNT_ORDER))
    return st.multiselect(
        "Account", opts, default=opts if default_all else opts[:1], key=key, format_func=account_label
    )


def table_config(
    df: pd.DataFrame,
    pct_cols: list[str] | None = None,
    eur_cols: list[str] | None = None,
    num_cols: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, object]:
    """Streamlit column_config for consistent number formats (nulls render empty, not 'None')."""
    cfg: dict[str, object] = {c: st.column_config.Column(metric_label(c)) for c in df.columns}
    for c in pct_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(metric_label(c), format="percent")
    for c in eur_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(metric_label(c), format="euro")
    for c in num_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(metric_label(c), format="localized")
    for c, f in (extra or {}).items():
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(metric_label(c), format=f)
    for c in df.columns:  # permalinks become clickable "open post" links
        if c == "permalink" or str(c).endswith("_url"):
            cfg[c] = st.column_config.LinkColumn(metric_label(c), display_text="open ↗", width="small")
    return cfg


def show_table(
    df: pd.DataFrame,
    pct_cols: list[str] | None = None,
    eur_cols: list[str] | None = None,
    num_cols: list[str] | None = None,
    extra: dict[str, str] | None = None,
    styler=None,  # noqa: ANN001
    **kwargs: object,
) -> None:
    """st.dataframe with number formats; optional Styler (for cell colours) is rendered on top."""
    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("use_container_width", True)
    if styler is None and "account" in df.columns:  # readable account names (Styler input is left untouched)
        df = df.assign(account=df["account"].map(account_label))
    st.dataframe(
        styler if styler is not None else df,
        column_config=table_config(df, pct_cols, eur_cols, num_cols, extra),
        **kwargs,
    )
