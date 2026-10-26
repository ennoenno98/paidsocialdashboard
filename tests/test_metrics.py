from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.ingest.xlsx import pivot_wide
from src.transform import metrics as mx


def _posts(**over):  # noqa: ANN003, ANN202
    base = {
        "brand": "vegavero",
        "platform": "instagram",
        "market": "IT",
        "kind": "organic",
        "account": "vegavero/instagram/IT",
        "year": 2026,
        "cw": 1,
        "slot": 1,
        "post_name": "p",
        "format": "Reel",
        "reach": 1000.0,
        "views": 5000.0,
        "video_views": np.nan,
        "play_time_min": np.nan,
        "likes": 50.0,
        "saves": 10.0,
        "follows": 3.0,
        "reposts": 5.0,
        "shares": np.nan,
        "comments": 5.0,
        "er_sheet": 0.07,
        "src_rows": "x",
    }
    base.update(over)
    return base


def test_er_is_engagements_over_reach_never_followers():
    df = mx.add_post_metrics(pd.DataFrame([_posts()]))
    r = df.iloc[0]
    assert r["engagements"] == 70
    assert r["er"] == 70 / 1000
    assert r["er_basis"] == "reach"
    assert abs(r["er_diff_pp"] - 0.0) < 1e-9


def test_er_nan_without_reach_not_zero_not_views():
    df = mx.add_post_metrics(pd.DataFrame([_posts(reach=np.nan)]))
    assert math.isnan(df.iloc[0]["er"])
    df = mx.add_post_metrics(pd.DataFrame([_posts(reach=0)]))
    assert math.isnan(df.iloc[0]["er"])


def test_tiktok_uses_video_views_basis():
    df = mx.add_post_metrics(
        pd.DataFrame(
            [
                _posts(
                    platform="tiktok",
                    account="vanatari/tiktok/INT",
                    reach=np.nan,
                    video_views=2000.0,
                    shares=20.0,
                    reposts=np.nan,
                )
            ]
        )
    )
    r = df.iloc[0]
    assert r["er_basis"] == "views"
    assert r["er"] == (50 + 5 + 10 + 20) / 2000


def test_follows_not_in_engagements():
    a = mx.add_post_metrics(pd.DataFrame([_posts(follows=0)])).iloc[0]["er"]
    b = mx.add_post_metrics(pd.DataFrame([_posts(follows=999)])).iloc[0]["er"]
    assert a == b


def test_account_er_mean_and_weighted():
    df = mx.add_post_metrics(
        pd.DataFrame(
            [
                _posts(reach=1000, likes=100, saves=0, comments=0, reposts=0),  # er 0.10
                _posts(slot=2, reach=9000, likes=90, saves=0, comments=0, reposts=0),  # er 0.01
                _posts(slot=3, reach=np.nan),  # no reach -> excluded from both
            ]
        )
    )
    a = mx.account_er(df).iloc[0]
    assert a["n_posts"] == 3 and a["n_posts_with_er"] == 2
    assert abs(a["er_mean"] - 0.055) < 1e-9
    assert abs(a["er_weighted"] - 190 / 10000) < 1e-9


def test_er_reconciliation_threshold():
    df = mx.add_post_metrics(
        pd.DataFrame([_posts(er_sheet=0.07), _posts(slot=2, er_sheet=0.03), _posts(slot=3, er_sheet=7.4)])
    )
    rec = mx.er_reconciliation(df, threshold_pp=0.5)
    assert len(rec) == 1 and rec.iloc[0]["slot"] == 2  # 7.4 is a percent number -> 0.074, within 0.5pp
    assert abs(rec.iloc[0]["er_diff_pp"] - 4.0) < 1e-9


def _long(rows):  # noqa: ANN001, ANN202
    recs = []
    for acc, kind, period, metric, value in rows:
        brand, platform, market = acc.split("/")
        recs.append(
            {
                "sheet": "w",
                "block_title": "t",
                "brand": brand,
                "platform": platform,
                "market": market,
                "kind": kind,
                "account": acc,
                "year": 2026,
                "period_type": "cw",
                "period": period,
                "metric": metric,
                "value": value,
                "value_text": None,
                "cell": "A1",
                "n_cells": 1,
            }
        )
    return pd.DataFrame(recs)


def test_boosting_metrics():
    long = _long(
        [
            ("vegavero/instagram/IT", "boosting", 1, "boost_spend", 100.0),
            ("vegavero/instagram/IT", "boosting", 1, "reach", 20000.0),
            ("vegavero/instagram/IT", "boosting", 1, "new_followers", 50.0),
            ("vegavero/instagram/IT", "organic", 1, "reach", 80000.0),
            ("vegavero/instagram/IT", "organic", 1, "net_follows", 200.0),
        ]
    )
    b = mx.boosting_metrics(pivot_wide(long)).iloc[0]
    assert b["cpm_boosted"] == 5.0
    assert b["cost_per_new_follower"] == 2.0
    assert b["cost_per_net_follow"] == 0.5
    assert b["boosted_reach_share"] == 0.2
    assert b["spend_source"] == "boosting_block"


def test_weekly_rollup_labelled():
    long = _long(
        [
            ("vegavero/instagram/IT", "organic", 1, "reach", 10.0),
            ("vegavero/instagram/IT", "organic", 2, "reach", 20.0),
            ("vegavero/instagram/IT", "organic", 1, "followers", 100.0),
            ("vegavero/instagram/IT", "organic", 2, "followers", 110.0),
        ]
    )
    r = mx.weekly_rollup(pivot_wide(long))
    assert (r["scope"] == "weekly_rollup").all()
    assert (
        r.iloc[0]["month"] == 1
        and r.iloc[0]["reach"] == 30
        and r.iloc[0]["followers"] == 110
        and r.iloc[0]["n_weeks"] == 2
    )


def test_reconcile_boost_spend_shows_delta(parsed, monthly_wide):
    rec = mx.reconcile_boost_spend(monthly_wide, parsed.boosting_susy, parsed.susy_budget)
    de = rec[(rec["account"] == "vegavero/instagram/DE") & (rec["year"] == 2026) & (rec["month"] == 9)].iloc[
        0
    ]
    assert (
        de["boost_spend_monthly_sheet"] == 1200
        and de["boost_spend_susy"] == 1620
        and de["delta_susy_minus_sheet"] == 420
    )
    assert not de["agree"] and de["boost_budget"] == 1200
    assert rec[
        (rec["account"] == "vegavero/instagram/DE") & (rec["year"] == 2026) & (rec["month"] == 10)
    ].iloc[0]["agree"]
