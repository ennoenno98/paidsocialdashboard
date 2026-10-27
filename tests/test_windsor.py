from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from src.ingest import windsor as wz
from src.ingest.instagram import ig_post_metrics
from src.ingest.xlsx import load_config
from src.transform import api_metrics as am

FIX = Path(__file__).parent / "fixtures" / "windsor"


@pytest.fixture(scope="module")
def raw():
    return wz.load_raw(wz.CachedWindsorSource(FIX))


@pytest.fixture(scope="module")
def cfg():
    return load_config()["windsor"]


def test_caption_key():
    k = wz.caption_key("Instagram post: 🌱Gennaio è il mese per rimettere...")
    assert k.startswith("🌱gennaio è il mese per rimet") and len(k) == wz.CAPTION_KEY_LEN
    assert (
        wz.caption_key("  Ende   Januar ist die Routine wieder voll da ", 60)
        == "ende januar ist die routine wieder voll da"
    )
    assert wz.caption_key(None) is None
    assert wz.shortcode("https://www.instagram.com/reel/DbX2wSvEQMI/") == "DbX2wSvEQMI"


def test_media_frame_and_er(raw, cfg):
    media = wz.ig_media_frame(raw, cfg["instagram"])
    assert set(media["account"]) == {
        "vegavero/instagram/IT",
        "vegavero/instagram/DE",
        "jasnum/instagram/IT",
        "wowtamins/instagram/DE",
    }
    assert media["caption_key"].notna().all() and (media["source"] == "windsor").all()
    m = ig_post_metrics(media)
    r = m[m["reach"].notna()].iloc[0]
    assert r["er"] == (r["like_count"] + r["comments_count"] + r["saved"] + r["shares"]) / r["reach"]
    assert m[m["reach"].isna()]["er"].isna().all()  # no reach -> NaN, never views/followers


def test_daily_frame_merges_new_followers(raw, cfg):
    d = wz.ig_daily_frame(raw, cfg["instagram"])
    assert len(d) == 4 * 130
    assert d["new_followers"].notna().sum() == 4 * 30  # Meta: last 30 days only
    assert d["followers"].notna().sum() == 4  # snapshot for today only
    assert {"brand", "platform", "market"} <= set(d.columns)


def test_boost_mapping(raw, cfg):
    media = wz.ig_media_frame(raw, cfg["instagram"])
    b = wz.boosted_frame(raw, media, cfg["facebook_ad_accounts"])
    counts = b.drop_duplicates("campaign")["match"].value_counts(dropna=False)
    assert counts.get("permalink", 0) == 1 and counts.get("caption", 0) == 6
    un = b[~b["mapped"]]
    assert un["campaign"].nunique() == 1 and (un["brand"] == "vegavero").all() and un["market"].isna().all()
    assert b.loc[b["mapped"], "market"].isin(["IT", "DE"]).all()


def test_periods_and_combined(raw, cfg):
    media = wz.ig_media_frame(raw, cfg["instagram"])
    posts_m = ig_post_metrics(media)
    daily = wz.ig_daily_frame(raw, cfg["instagram"])
    boosted = wz.boosted_frame(raw, media, cfg["facebook_ad_accounts"])
    org = am.organic_periods(daily, posts_m, "cw")
    acc = org[org["account"] == "vegavero/instagram/IT"]
    assert (acc["n_days"] <= 7).all() and (org["scope"] == "api").all()
    # sums reconcile to the daily frame
    wk = acc.iloc[3]
    dd = daily[(daily["account"] == "vegavero/instagram/IT")]
    iso = pd.to_datetime(dd["date"]).dt.isocalendar()
    sel = dd[(iso["year"] == wk["year"]) & (iso["week"] == wk["period"])]
    assert wk["reach_daily_sum"] == sel["reach"].sum() and wk["n_days"] == len(sel)
    bst = am.boosted_periods(boosted, "month")
    comb = am.combined_periods(am.organic_periods(daily, posts_m, "month"), bst)
    row = comb[comb["boost_spend"].notna() & comb["account"].notna()].iloc[0]
    assert row["cpm_boosted"] == pytest.approx(row["boost_spend"] / row["boosted_reach_daily_sum"] * 1000)
    assert 0 < row["boosted_reach_share"] < 1
    assert am.latest_complete_period(org, "cw", today=dt.date(2026, 10, 27)) == (2026, 43)


def test_creators_public_excludes_own(raw, cfg):
    pub = wz.creators_public_frame(raw, cfg["instagram_public_own"])
    assert set(pub["handle"]) == {"cucinabotanica", "fit_giulia"}
    s = wz.creators_public_summary(pub, until=dt.date(2026, 10, 26))
    assert set(s["handle"]) == {"cucinabotanica", "fit_giulia"} and (s["interactions_per_post"] > 0).all()
    assert "reach" not in s.columns


def test_pull_all_and_cache(tmp_path):
    src = wz.CachedWindsorSource(FIX)
    counts = wz.pull_all(src, tmp_path)
    assert set(counts) == set(wz.PULLS) and all(v > 0 for v in counts.values())
    again = wz.load_raw(wz.CachedWindsorSource(tmp_path))
    assert len(again["instagram__media"]) == counts["instagram__media"]
