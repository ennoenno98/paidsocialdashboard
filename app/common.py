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

# Categorical palette, fixed slot order (never cycled). Entity -> slot is stable across filters.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ACCOUNT_ORDER = [
    "vegavero/instagram/IT",
    "vegavero/instagram/DE",
    "vegavero/tiktok/IT",
    "vegavero/tiktok/DE",
    "vanatari/tiktok/INT",
    "wowtamins/instagram/DE",
    "wowtamins/tiktok/DE",
    "jasnum/instagram/IT",
]
ACCOUNT_COLORS = {a: PALETTE[i] for i, a in enumerate(ACCOUNT_ORDER)}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_resource(ttl=6 * 3600, show_spinner="Loading Windsor, Klar and workbook data…")
def get_bundle() -> Bundle:
    return build_bundle()


def page_setup(title: str) -> Bundle:
    st.set_page_config(page_title=f"Vanatari Social · {title}", layout="wide", page_icon="📊")
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
        font={
            "family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
            "color": INK["secondary"],
            "size": 12,
        },
        legend={"orientation": "h", "y": -0.18, "title": None},
        hovermode="x unified",
        colorway=PALETTE,
    )
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
