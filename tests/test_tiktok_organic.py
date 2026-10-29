"""TikTok organic via Windsor: daily frame, videos as own posts with ER on views, API rows win over sheet blocks."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from src.ingest import instagram as ig
from src.ingest import windsor as wz
from src.ingest.xlsx import load_config
from src.pipeline import FIXTURES, build_bundle, windsor_frames
from src.transform.scorecard import organic_kpis

TT_MAP = {"_000afwDIRJrBF53t6K4HAVnfxL7OqINYkCT": "vegavero/tiktok/IT"}


def _raw():
    return wz.load_raw(wz.CachedWindsorSource(FIXTURES / "windsor"))


def test_tt_daily_frame_layout_and_zero_day_dropped():
    d = wz.tt_daily_frame(_raw(), TT_MAP)
    assert list(d.columns) == wz.DAILY_COLS
    assert d["account"].eq("vegavero/tiktok/IT").all() and d["platform"].eq("tiktok").all()
    assert dt.date(2026, 10, 27) not in set(d["date"])  # all-zero day (not delivered yet) is dropped
    assert len(d) == 40 and d["followers"].max() == 5400 and d["new_followers"].notna().all()
    assert d["saves"].isna().all() and (d["total_interactions"] == 213).all()
    assert wz.tt_daily_frame(_raw(), {}).empty


def test_tt_videos_become_own_posts_with_er_on_views():
    v = wz.tt_videos_frame(_raw(), TT_MAP)
    assert len(v) == 6 and v["relationship"].eq("owned").all()
    assert v["permalink"].iloc[0] == "https://www.tiktok.com/@vegavero.italia/video/770000"
    posts = ig.ig_post_metrics(v)
    assert posts["er_basis"].eq("views").all()
    first = posts.sort_values("media_id").iloc[0]
    assert first["er"] == (100 + 2 + 10 + 5) / 10000


def test_windsor_frames_merge_tiktok_into_daily_and_posts():
    wf = windsor_frames(_raw(), load_config(), allow_fixture=True)
    assert "vegavero/tiktok/IT" in set(wf["daily"]["account"])
    assert wf["daily"][wf["daily"]["platform"].eq("instagram")].shape[0] > 0
    tt_posts = wf["posts_m"][wf["posts_m"]["platform"].eq("tiktok")]
    assert len(tt_posts) == 6 and tt_posts["er_basis"].eq("views").all()
    ig_posts = wf["posts_m"][wf["posts_m"]["platform"].eq("instagram")]
    assert ig_posts["er_basis"].eq("reach").all()
    wk = wf["api_weekly"]
    assert (wk[wk["account"].eq("vegavero/tiktok/IT")]["views"] > 0).any()


def test_organic_kpis_prefers_api_tiktok_over_sheet():
    b = build_bundle()
    org = organic_kpis(
        b.ig_daily, b.monthly_wide, dt.date(2026, 10, 1), dt.date(2026, 10, 26), b.weekly_wide, "Month"
    )
    row = org[org["account"].eq("vegavero/tiktok/IT")]
    assert len(row) == 1 and row["source"].iloc[0] == "api" and row["platform"].iloc[0] == "tiktok"
    assert pd.notna(row["new_followers"].iloc[0]) and row["views"].iloc[0] > 0


def test_media_pull_has_no_reposts_and_tiktok_videos_accumulate():
    assert "media_reposts" not in wz.MEDIA_FIELDS  # rejected for accounts connected with Instagram Login
    spec = wz.PULLS["tiktok_organic__videos"]
    assert spec["date_preset"] == "last_60d" and spec["accumulate"] == "video_id"


def test_combined_periods_survive_boosts_without_mapped_account():
    from src.transform import api_metrics as am

    raw = _raw()
    cfg = load_config()
    ig_map = {str(k): str(v) for k, v in cfg["windsor"]["instagram"].items()}
    fb_map = {str(k): str(v) for k, v in cfg["windsor"]["facebook_ad_accounts"].items()}
    empty_media = wz.ig_media_frame({**raw, "instagram__media": raw["instagram__media"].iloc[0:0]}, ig_map)
    boosted = wz.boosted_frame(raw, empty_media, fb_map)
    assert boosted["account"].isna().all() and boosted["account"].dtype == object
    daily = wz.ig_daily_frame(raw, ig_map)
    org = am.organic_periods(daily, empty_media, "month")
    out = am.combined_periods(org, am.boosted_periods(boosted, "month"))
    assert not out.empty and "boost_spend" in out.columns


def test_git_auth_header_is_basic_x_access_token():
    import base64

    from src import data_repo as dr

    h = dr.auth_header("tok")
    assert h == "Authorization: Basic " + base64.b64encode(b"x-access-token:tok").decode()
