"""Regression tests for the code-review findings (boost filter, empty-side period merge, post counts, agree NA,
fixture gating)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src import pipeline
from src.ingest import windsor as wz
from src.ingest.instagram import ig_post_metrics
from src.ingest.xlsx import load_config
from src.transform import api_metrics as am

FIX = Path(__file__).parent / "fixtures" / "windsor"


def _frames():
    raw = wz.load_raw(wz.CachedWindsorSource(FIX))
    cfg = load_config()["windsor"]
    media = wz.ig_media_frame(raw, cfg["instagram"])
    return (
        raw,
        media,
        wz.ig_daily_frame(raw, cfg["instagram"]),
        wz.boosted_frame(raw, media, cfg["facebook_ad_accounts"]),
    )


def test_row_filter_applies_to_cached_rows_and_other_languages():
    spec = wz.PULLS["facebook__boosted"]
    rows = [
        {"campaign": "Instagram post: Something..."},
        {"campaign": "Instagram-Beitrag: Ende Januar..."},
        {"campaign": "Post di Instagram: Gennaio..."},
        {"campaign": "Conversions | Prospecting DE"},
        {"campaign": None},
    ]
    kept = wz.apply_row_filter(rows, spec)
    assert [r["campaign"][:6] for r in kept] == ["Instag", "Instag", "Post d"]
    assert wz.apply_row_filter(rows, wz.PULLS["instagram__media"]) == rows  # no filter on other pulls
    assert (
        wz.caption_key("Instagram-Beitrag: Ende Januar ist die Routine", 60) == "ende januar ist die routine"
    )


def test_combined_periods_keeps_boost_columns_when_boosted_empty():
    _, media, daily, boosted = _frames()
    org = am.organic_periods(daily, ig_post_metrics(media), "month")
    empty = am.boosted_periods(boosted.iloc[0:0], "month")
    comb = am.combined_periods(org, empty)
    for c in ("boost_spend", "boosted_impressions", "boosted_clicks", "n_boosted_posts", "cpm_boosted"):
        assert c in comb.columns and comb[c].isna().all()
    assert len(comb) == len(org)
    # and the mirror case: boosts without any organic data
    comb2 = am.combined_periods(org.iloc[0:0], am.boosted_periods(boosted, "month"))
    assert "reach_daily_sum" in comb2.columns and comb2["boost_spend"].notna().any()


def test_n_boosted_posts_counts_promoted_posts_not_ad_copies():
    _, _, _, boosted = _frames()
    b = boosted[boosted["mapped"]].copy()
    first = b.iloc[0]
    # a second ad copy (new shortcode) of the same own post in the same period must not add a post
    dup = b.iloc[[0]].assign(shortcode="XXXXXXXXXXX", ad_id="dup")
    per = am.boosted_periods(pd.concat([b, dup]), "month")
    row = per[(per["account"] == first["account"])].iloc[0]
    acc_rows = pd.concat([b, dup])
    acc_rows = acc_rows[acc_rows["account"].eq(first["account"])]
    yr, mo = pd.Timestamp(first["date"]).year, pd.Timestamp(first["date"]).month
    sel = acc_rows[
        pd.to_datetime(acc_rows["date"]).dt.year.eq(yr) & pd.to_datetime(acc_rows["date"]).dt.month.eq(mo)
    ]
    assert row["n_boosted_posts"] == sel["media_id"].nunique() < sel["shortcode"].nunique()


def test_spend_recon_meta_only_months_are_not_flagged():
    rec = pd.DataFrame(
        {
            "account": ["vegavero/instagram/IT"],
            "brand": ["vegavero"],
            "platform": ["instagram"],
            "market": ["IT"],
            "year": [2026],
            "month": [9],
            "boost_spend_monthly_sheet": [565.0],
            "boost_spend_susy": [1260.0],
            "delta_susy_minus_sheet": [695.0],
            "boost_budget": [np.nan],
            "agree": [False],
        }
    )
    meta = pd.DataFrame(
        {
            "account": ["vegavero/instagram/IT", "wowtamins/instagram/DE"],
            "year": [2026, 2026],
            "period": [9, 9],
            "boost_spend": [565.26, 1222.85],
        }
    )
    out = am.spend_recon_with_meta(rec, meta)
    wow = out[out["account"].eq("wowtamins/instagram/DE")].iloc[0]
    assert pd.isna(wow["agree"]) and wow["brand"] == "wowtamins" and wow["market"] == "DE"
    assert bool(out[out["account"].eq("vegavero/instagram/IT")].iloc[0]["agree"]) is False


def test_fixtures_only_with_fixture_workbook(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "PROCESSED", tmp_path)
    monkeypatch.setattr(pipeline.klar_mod, "RAW_DIR", tmp_path / "no_klar")
    df, label = pipeline.load_klar(tmp_path, allow_fixture=False)
    assert df.empty and label == "none"
    posts, scan, label = pipeline.load_ig_graph(tmp_path, allow_fixture=False)
    assert posts.empty and scan.empty and label == "none"
    # default: the fixture workbook unlocks fixtures (what the tests and an empty deploy run on)
    b = pipeline.build_bundle()
    assert b.is_fixture and "FIXTURE" in b.status["klar"]


def test_cache_age(tmp_path):
    assert wz.CachedWindsorSource(tmp_path).age_hours() is None
    wz.pull_all(wz.CachedWindsorSource(FIX), tmp_path, pulls=["instagram__media"])
    age = wz.CachedWindsorSource(tmp_path).age_hours()
    assert age is not None and age < 1
