"""Shared helpers for the Streamlit pages: cached bundle, palette, formatting, chart layout."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline import Bundle, build_bundle  # noqa: E402

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
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_resource(ttl=6 * 3600, show_spinner="Loading Windsor, Klar and workbook data…")
def get_bundle() -> Bundle:
    return build_bundle()


def page_setup(title: str) -> Bundle:
    st.set_page_config(page_title=f"Vanatari Social · {title}", layout="wide", page_icon="📊")
    st.html(
        FONT_CSS
    )  # loads Satoshi (body) + Literata (headings); families are set in .streamlit/config.toml
    b = get_bundle()
    st.title(title)
    if b.is_fixture:
        st.warning(
            "Showing **synthetic fixture data**. Drop the real workbook at `data/Social_Media.xlsx` "
            "(or set `SOCIAL_XLSX`) and run `make refresh`.",
            icon="⚠️",
        )
    return b


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


def fmt_eur(x: float | None, decimals: int = 0) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    return f"€{x:,.{decimals}f}"


def period_label(period_type: str, year: int, period: int) -> str:
    return f"CW {period:02d}/{year}" if period_type == "cw" else f"{MONTHS[period - 1]} {year}"


def apply_layout(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT_BODY, "color": INK["secondary"], "size": 12},
        title={"font": {"family": FONT_HEAD, "color": INK["primary"], "size": 15}},
        legend={"orientation": "h", "y": -0.18, "title": None},
        hovermode="x unified",
        colorway=PALETTE,
    )
    # 1px surface-coloured ring on bars = the gap between stacked segments / adjacent bars (dataviz mark spec).
    fig.update_traces(marker_line={"color": SURFACE, "width": 1}, selector={"type": "bar"})
    fig.update_xaxes(showgrid=False, linecolor=INK["axis"], tickcolor=INK["axis"])
    fig.update_yaxes(gridcolor=INK["grid"], zerolinecolor=INK["axis"], linecolor="rgba(0,0,0,0)")
    return fig


def account_filter(options: list[str], key: str, default_all: bool = True) -> list[str]:
    opts = [a for a in ACCOUNT_ORDER if a in options] + sorted(set(options) - set(ACCOUNT_ORDER))
    return st.multiselect("Account", opts, default=opts if default_all else opts[:1], key=key)


def table_config(
    df: pd.DataFrame,
    pct_cols: list[str] | None = None,
    eur_cols: list[str] | None = None,
    num_cols: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, object]:
    """Streamlit column_config for consistent number formats (nulls render empty, not 'None')."""
    cfg: dict[str, object] = {}
    for c in pct_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(c, format="percent")
    for c in eur_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(c, format="euro")
    for c in num_cols or []:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(c, format="localized")
    for c, f in (extra or {}).items():
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(c, format=f)
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
    st.dataframe(
        styler if styler is not None else df,
        column_config=table_config(df, pct_cols, eur_cols, num_cols, extra),
        **kwargs,
    )
