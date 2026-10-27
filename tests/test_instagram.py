from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from src.ingest import instagram as ig

FIX = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 10, 26, 6, tzinfo=dt.UTC)
IDS = {"vegavero/instagram/IT": "17841400000000001", "vegavero/instagram/DE": "17841400000000002"}


def _src() -> ig.FixtureSource:
    return ig.FixtureSource(FIX / "ig_media.json", FIX / "ig_business_discovery.json")


def test_pull_own_accounts_idempotent(tmp_path):
    p = tmp_path / "ig_posts.parquet"
    a = ig.pull_own_accounts(_src(), IDS, p, now=NOW)
    b = ig.pull_own_accounts(_src(), IDS, p, now=NOW + dt.timedelta(days=1))
    assert len(a) == len(b) and b["media_id"].is_unique
    assert (b["fetched_at"] > a["fetched_at"].min()).all()


def test_ig_post_er_by_reach(tmp_path):
    df = ig.pull_own_accounts(_src(), IDS, tmp_path / "x.parquet", now=NOW)
    m = ig.ig_post_metrics(df)
    r = m[m["reach"].notna()].iloc[0]
    assert r["er"] == (r["like_count"] + r["comments_count"] + r["saved"] + r["shares"]) / r["reach"]
    assert (m["er_basis"] == "reach").all()
    assert m[m["reach"].isna()]["er"].isna().all()
    assert {"brand", "platform", "market", "year", "cw", "month"} <= set(m.columns)


def test_scan_creators_handles_not_scannable():
    s = ig.scan_creators(_src(), IDS["vegavero/instagram/IT"], ["fit_giulia", "@Unknown_Person"], now=NOW)
    assert s.set_index("handle").loc["fit_giulia", "scannable"]
    assert not s.set_index("handle").loc["unknown_person", "scannable"]
    assert s.set_index("handle").loc["fit_giulia", "interactions_per_post"] > 0
    assert "reach" not in s.columns  # never available for third parties


def test_influencer_cpm_priority_and_source():
    base = pd.DataFrame(
        [
            {
                "influencer_name": "A",
                "creator_handle": "a",
                "costs": 100.0,
                "reach_klar": 50000.0,
                "n_posting_dates": 2,
            },
            {
                "influencer_name": "B",
                "creator_handle": "b",
                "costs": 100.0,
                "reach_klar": 0.0,
                "n_posting_dates": 1,
            },
            {
                "influencer_name": "C",
                "creator_handle": "c",
                "costs": 100.0,
                "reach_klar": 0.0,
                "n_posting_dates": 1,
            },
        ]
    )
    manual = pd.DataFrame(
        [
            {
                "handle": "b",
                "post_url": "u",
                "date": pd.Timestamp("2026-09-01"),
                "reach": 20000.0,
                "source": "creator_insights",
            }
        ]
    )
    out = ig.influencer_cpm(base, manual).set_index("influencer_name")
    assert out.loc["A", "reach_source"] == "klar" and out.loc["A", "cpm"] == 2.0
    assert out.loc["B", "reach_source"] == "manual" and out.loc["B", "cpm"] == 5.0
    assert out.loc["C", "reach_source"] == "n/a" and pd.isna(out.loc["C", "cpm"])


def test_load_manual_reach_missing_file(tmp_path):
    assert ig.load_manual_reach(tmp_path / "nope.csv").empty
