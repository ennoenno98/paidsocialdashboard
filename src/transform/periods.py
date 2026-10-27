"""Period granularity (week / month / quarter) and date ranges shared by every page.

Frames carry ``year, period_type, period`` (``cw`` = ISO week, ``month``). A quarter view is derived from the
monthly frame: flows are summed, stocks (followers) take the last month, ratios are recomputed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.transform.metrics import _safe_div

GRANULARITIES = ("Week", "Month", "Quarter")
PTYPE = {"Week": "cw", "Month": "month", "Quarter": "quarter"}
STOCK_COLS = {"followers"}
RATIO_RULES: dict[str, tuple[str, str, float]] = {  # col -> (numerator, denominator, factor)
    "cpm_boosted": ("boost_spend", "boosted_reach_daily_sum", 1000.0),
    "cost_per_new_follower": ("boost_spend", "new_followers", 1.0),
    "story_exit_rate": ("story_exits", "story_views_sum", 1.0),
    "story_reach_per_story": ("story_reach_sum", "n_stories", 1.0),
    "cost_per_net_follow": ("boost_spend", "organic_net_follows", 1.0),
}
TEXT_COLS = {
    "er_basis",
    "scope",
    "spend_source",
    "audience",
    "boosted_post",
    "goal",
    "kind",
    "brand",
    "platform",
    "market",
    "account",
}


@dataclass(frozen=True)
class PeriodSel:
    granularity: str  # Week | Month | Quarter
    start: dt.date
    end: dt.date  # inclusive
    label: str
    mode: str

    @property
    def ptype(self) -> str:
        return PTYPE[self.granularity]


def period_start(ptype: str, year: int, period: int) -> dt.date:
    if ptype == "cw":
        return dt.date.fromisocalendar(int(year), int(period), 1)
    if ptype == "month":
        return dt.date(int(year), int(period), 1)
    return dt.date(int(year), 3 * (int(period) - 1) + 1, 1)


def period_end(ptype: str, year: int, period: int) -> dt.date:
    if ptype == "cw":
        return period_start(ptype, year, period) + dt.timedelta(days=6)
    if ptype == "month":
        nxt = dt.date(int(year) + (int(period) == 12), int(period) % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    q_end_month = 3 * int(period)
    return period_end("month", year, q_end_month)


def period_of(ptype: str, day: dt.date) -> tuple[int, int]:
    if ptype == "cw":
        iso = day.isocalendar()
        return iso[0], iso[1]
    if ptype == "month":
        return day.year, day.month
    return day.year, (day.month - 1) // 3 + 1


def shift_period(ptype: str, year: int, period: int, n: int) -> tuple[int, int]:
    """Move n periods (negative = back)."""
    d = period_start(ptype, year, period)
    if ptype == "cw":
        return period_of("cw", d + dt.timedelta(weeks=n))
    months = (d.year * 12 + d.month - 1) + n * (3 if ptype == "quarter" else 1)
    return period_of(ptype, dt.date(months // 12, months % 12 + 1, 1))


def label_of(ptype: str, year: int, period: int) -> str:
    if ptype == "cw":
        return f"CW {int(period):02d}/{int(year)}"
    if ptype == "month":
        return f"{period_start(ptype, year, period):%b %Y}"
    return f"Q{int(period)} {int(year)}"


def latest_complete(ptype: str, today: dt.date | None = None) -> tuple[int, int]:
    today = today or dt.date.today()
    y, p = period_of(ptype, today)
    return shift_period(ptype, y, p, -1)


def resolve_period(
    granularity: str,
    mode: str,
    today: dt.date | None = None,
    year: int | None = None,
    number: int | None = None,
    custom: tuple[dt.date, dt.date] | None = None,
) -> PeriodSel:
    """mode: latest | previous | last_n | ytd | last_12m | specific | custom."""
    today = today or dt.date.today()
    ptype = PTYPE[granularity]
    ly, lp = latest_complete(ptype, today)
    if mode == "latest":
        return PeriodSel(
            granularity, period_start(ptype, ly, lp), period_end(ptype, ly, lp), label_of(ptype, ly, lp), mode
        )
    if mode == "previous":
        y, p = shift_period(ptype, ly, lp, -1)
        return PeriodSel(
            granularity, period_start(ptype, y, p), period_end(ptype, y, p), label_of(ptype, y, p), mode
        )
    if mode == "last_n":
        n = {"cw": 4, "month": 3, "quarter": 4}[ptype]
        y, p = shift_period(ptype, ly, lp, -(n - 1))
        return PeriodSel(
            granularity,
            period_start(ptype, y, p),
            period_end(ptype, ly, lp),
            f"last {n} {granularity.lower()}s ({label_of(ptype, y, p)} – {label_of(ptype, ly, lp)})",
            mode,
        )
    if mode == "ytd":
        return PeriodSel(
            granularity, dt.date(today.year, 1, 1), today - dt.timedelta(days=1), f"{today.year} YTD", mode
        )
    if mode == "last_12m":
        return PeriodSel(
            granularity, today - dt.timedelta(days=365), today - dt.timedelta(days=1), "last 12 months", mode
        )
    if mode == "specific" and year is not None and number is not None:
        return PeriodSel(
            granularity,
            period_start(ptype, year, number),
            period_end(ptype, year, number),
            label_of(ptype, year, number),
            mode,
        )
    if mode == "custom" and custom:
        return PeriodSel(
            granularity, custom[0], custom[1], f"{custom[0]:%d.%m.%Y} – {custom[1]:%d.%m.%Y}", mode
        )
    raise ValueError(f"unsupported period mode {mode}")


def to_quarters(monthly: pd.DataFrame) -> pd.DataFrame:
    """Monthly (year, period_type='month', period) rows -> quarterly rows; flows summed, followers last, ratios recomputed."""
    if monthly.empty:
        out = monthly.copy()
        out["period_type"] = "quarter"
        return out
    m = monthly[monthly["period_type"].eq("month")].copy()
    m["period"] = ((m["period"].astype(int) - 1) // 3 + 1).astype(int)
    keys = [c for c in ("account", "brand", "platform", "market", "kind", "year", "period") if c in m.columns]
    num = [
        c for c in m.columns if c not in keys and c not in TEXT_COLS and pd.api.types.is_numeric_dtype(m[c])
    ]
    agg: dict[str, object] = {}
    for c in num:
        if c in STOCK_COLS:
            agg[c] = "last"
        elif c in RATIO_RULES or c in ("er_mean", "er_weighted", "er_sheet", "boosted_reach_share"):
            continue
        else:
            agg[c] = lambda s: s.sum(min_count=1)
    text = [c for c in m.columns if c in TEXT_COLS and c not in keys]
    for c in text:
        agg[c] = "first"
    m = m.sort_values(keys)
    out = m.groupby(keys, dropna=False).agg(agg).reset_index()
    out["period_type"] = "quarter"
    if "er_mean" in m.columns and "n_posts" in m.columns:
        w = (
            m.assign(_w=m["er_mean"] * m["n_posts"])
            .groupby(keys, dropna=False)[["_w"]]
            .sum(min_count=1)
            .reset_index()
        )
        out = out.merge(w, on=keys, how="left")
        out["er_mean"] = _safe_div(out["_w"], out["n_posts"])
        out = out.drop(columns="_w")
    if "er_weighted" in m.columns:
        out["er_weighted"] = np.nan  # needs per-post sums; not recoverable from monthly aggregates
    for col, (numer, denom, factor) in RATIO_RULES.items():
        if numer in out.columns and denom in out.columns:
            out[col] = _safe_div(out[numer], out[denom]) * factor
    if "boosted_reach_daily_sum" in out.columns and "reach_daily_sum" in out.columns:
        tot = out["reach_daily_sum"].fillna(0) + out["boosted_reach_daily_sum"].fillna(0)
        out["boosted_reach_share"] = _safe_div(out["boosted_reach_daily_sum"], tot)
    elif "boosted_reach" in out.columns and "organic_reach" in out.columns:
        tot = out["organic_reach"].fillna(0) + out["boosted_reach"].fillna(0)
        out["boosted_reach_share"] = _safe_div(out["boosted_reach"], tot)
    return out[[*keys, "period_type", *[c for c in out.columns if c not in keys and c != "period_type"]]]


def frame_for(weekly: pd.DataFrame, monthly: pd.DataFrame, granularity: str) -> pd.DataFrame:
    if granularity == "Week":
        return weekly
    if granularity == "Month":
        return monthly
    return to_quarters(monthly)


def in_range(df: pd.DataFrame, sel: PeriodSel) -> pd.DataFrame:
    """Rows whose period overlaps [sel.start, sel.end] (period_type per row)."""
    if df.empty or "period" not in df.columns:
        return df
    pt = df["period_type"] if "period_type" in df.columns else pd.Series(sel.ptype, index=df.index)
    starts = [
        period_start(str(t), int(y), int(p)) for t, y, p in zip(pt, df["year"], df["period"], strict=True)
    ]
    ends = [period_end(str(t), int(y), int(p)) for t, y, p in zip(pt, df["year"], df["period"], strict=True)]
    mask = [(s <= sel.end) and (e >= sel.start) for s, e in zip(starts, ends, strict=True)]
    return df[mask]


def dates_in_range(dates: pd.Series, sel: PeriodSel) -> pd.Series:
    d = pd.to_datetime(dates, utc=True, errors="coerce").dt.tz_convert(None).dt.date
    return pd.Series([(x is not None and x == x and sel.start <= x <= sel.end) for x in d], index=dates.index)
