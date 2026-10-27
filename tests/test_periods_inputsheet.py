"""Period maths shared by every page, quarter derivation, and the team input sheet loaders."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from src.ingest import input_sheet as inp
from src.transform import periods as pr

FIX = Path(__file__).parent / "fixtures" / "input_sheet"
TODAY = dt.date(2026, 10, 27)  # a Tuesday in ISO week 44


def test_period_bounds_and_labels():
    assert pr.period_start("cw", 2026, 1) == dt.date(2025, 12, 29)
    assert pr.period_end("cw", 2026, 1) == dt.date(2026, 1, 4)
    assert pr.period_end("month", 2026, 2) == dt.date(2026, 2, 28)
    assert pr.period_start("quarter", 2026, 4) == dt.date(2026, 10, 1)
    assert pr.period_end("quarter", 2026, 4) == dt.date(2026, 12, 31)
    assert pr.period_of("cw", dt.date(2025, 12, 29)) == (2026, 1)
    assert pr.period_of("quarter", dt.date(2026, 5, 15)) == (2026, 2)
    assert pr.shift_period("cw", 2026, 1, -1) == (2025, 52)
    assert pr.shift_period("month", 2026, 1, -1) == (2025, 12)
    assert pr.shift_period("quarter", 2026, 1, -2) == (2025, 3)
    assert pr.label_of("cw", 2026, 3) == "CW 03/2026"
    assert pr.label_of("quarter", 2026, 2) == "Q2 2026"


def test_resolve_period_modes():
    assert pr.latest_complete("cw", TODAY) == (2026, 43)
    assert pr.latest_complete("month", TODAY) == (2026, 9)
    assert pr.latest_complete("quarter", TODAY) == (2026, 3)
    latest = pr.resolve_period("Week", "latest", TODAY)
    assert (latest.start, latest.end) == (dt.date(2026, 10, 19), dt.date(2026, 10, 25))
    assert latest.ptype == "cw"
    prev = pr.resolve_period("Month", "previous", TODAY)
    assert (prev.start, prev.end) == (dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    last_n = pr.resolve_period("Quarter", "last_n", TODAY)
    assert (last_n.start, last_n.end) == (dt.date(2025, 10, 1), dt.date(2026, 9, 30))
    ytd = pr.resolve_period("Month", "ytd", TODAY)
    assert (ytd.start, ytd.end) == (dt.date(2026, 1, 1), dt.date(2026, 10, 26))
    spec = pr.resolve_period("Week", "specific", TODAY, year=2026, number=10)
    assert spec.label == "CW 10/2026"
    custom = pr.resolve_period("Month", "custom", TODAY, custom=(dt.date(2026, 3, 2), dt.date(2026, 3, 9)))
    assert custom.end == dt.date(2026, 3, 9)
    with pytest.raises(ValueError):
        pr.resolve_period("Week", "nope", TODAY)


def _monthly() -> pd.DataFrame:
    rows = []
    for m, foll, views, spend, reach, br in ((1, 100, 10, 10.0, 1000, 100), (2, 120, 20, 30.0, 1000, 300)):
        rows.append(
            {
                "account": "vegavero/instagram/DE",
                "brand": "vegavero",
                "platform": "instagram",
                "market": "DE",
                "kind": "organic",
                "year": 2026,
                "period_type": "month",
                "period": m,
                "followers": foll,
                "views": views,
                "boost_spend": spend,
                "reach_daily_sum": reach,
                "boosted_reach_daily_sum": br,
                "n_posts": 2,
                "er_mean": 0.05 if m == 1 else 0.10,
                "er_basis": "reach",
            }
        )
    return pd.DataFrame(rows)


def test_to_quarters_sums_flows_keeps_last_stock_recomputes_ratios():
    q = pr.to_quarters(_monthly())
    assert len(q) == 1
    r = q.iloc[0]
    assert r["period_type"] == "quarter" and r["period"] == 1
    assert r["followers"] == 120  # stock: last month
    assert r["views"] == 30 and r["boost_spend"] == 40.0  # flows summed
    assert r["cpm_boosted"] == pytest.approx(40.0 / 400 * 1000)
    assert r["boosted_reach_share"] == pytest.approx(400 / 2400)
    assert r["er_mean"] == pytest.approx((0.05 * 2 + 0.10 * 2) / 4)
    assert r["er_basis"] == "reach"
    empty = pr.to_quarters(_monthly().iloc[0:0])
    assert empty.empty and "period_type" in empty.columns


def test_frame_for_and_in_range():
    monthly = _monthly()
    weekly = monthly.assign(period_type="cw", period=[4, 6])  # CW 04 ends 25 Jan, CW 06 = 2–8 Feb
    assert pr.frame_for(weekly, monthly, "Week") is weekly
    assert pr.frame_for(weekly, monthly, "Month") is monthly
    assert pr.frame_for(weekly, monthly, "Quarter")["period_type"].eq("quarter").all()
    feb = pr.resolve_period("Month", "specific", TODAY, year=2026, number=2)
    assert pr.in_range(monthly, feb)["period"].tolist() == [2]
    assert pr.in_range(weekly, feb)["period"].tolist() == [6]
    dates = pd.Series(["2026-01-31T23:00:00Z", "2026-02-10T10:00:00Z", None])
    assert pr.dates_in_range(dates, feb).tolist() == [False, True, False]


def test_input_sheet_creator_reach_skips_help_and_example_rows():
    df = inp.load_creator_reach(FIX)
    assert df["handle"].tolist() == ["fit_with_anna"]  # @ stripped, lower-cased, rows without reach dropped
    assert df["reach"].iloc[0] == 12500 and df["source"].iloc[0] == "input_sheet"
    assert df["date"].iloc[0] == pd.Timestamp("2026-02-03")
    assert "entered_by" in df.columns and df["entered_by"].iloc[0] == "enno"
    assert inp.load_creator_reach(FIX / "missing").empty


def test_input_sheet_stories_tiktok_budget():
    st = inp.load_stories_manual(FIX)
    assert st["account"].tolist() == ["vegavero/instagram/DE", "wowtamins/instagram/DE"]
    assert st["story_id"].iloc[0] == "manual:vegavero/instagram/DE:2026-02-03"
    assert st["views"].iloc[0] == 5200 and st["n_stories_manual"].iloc[0] == 3
    assert st["brand"].iloc[1] == "wowtamins" and st["market"].iloc[1] == "DE"
    tt = inp.load_tiktok_weekly(FIX)
    assert tt["account"].tolist() == ["vegavero/tiktok/DE", "vegavero/tiktok/IT", "vanatari/tiktok/INT"]
    assert tt["period_type"].eq("cw").all() and tt["kind"].eq("organic").all()
    assert tt["followers"].iloc[0] == 8200 and tt["views"].iloc[2] == 3000
    assert tt["source"].eq("input_sheet").all()
    b = inp.load_budget(FIX)
    assert b["budget_total"].tolist() == [25000.0, 3000.0]


def test_input_sheet_rows_flow_into_bundle():
    from src.pipeline import build_bundle

    b = build_bundle()
    tt = b.weekly_wide[b.weekly_wide["platform"].eq("tiktok") & b.weekly_wide["period"].eq(6)]
    assert set(tt["account"]) >= {"vegavero/tiktok/DE", "vegavero/tiktok/IT", "vanatari/tiktok/INT"}
    assert "input_sheet" in b.status
    manual_days = b.ig_stories[b.ig_stories["story_id"].astype(str).str.startswith("manual:")]
    assert len(manual_days) == 2
