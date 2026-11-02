"""Net follower growth, paid Instagram views and Meta's unique period reach (organic dashboard fixes)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ingest import ig_reach as igr
from src.ingest import windsor as wz
from src.ingest.instagram import ig_post_metrics
from src.ingest.xlsx import load_config
from src.transform import api_metrics as am
from src.transform import periods as pr
from src.transform import scorecard as sc

FIX = Path(__file__).parent / "fixtures" / "windsor"


@pytest.fixture(scope="module")
def raw():
    return wz.load_raw(wz.CachedWindsorSource(FIX))


@pytest.fixture(scope="module")
def cfg():
    return load_config()["windsor"]


@pytest.fixture(scope="module")
def daily(raw, cfg):
    return wz.ig_daily_frame(raw, cfg["instagram"])


# ------------------------------------------------------------------ followers
def test_daily_frame_derives_unfollows_and_net(raw, cfg, daily):
    nf = raw["instagram__new_followers"]
    nf = nf[nf["account_id"].astype(str).eq("17841404238631874")].copy()
    nf["date"] = pd.to_datetime(nf["date"]).dt.date
    d = daily[daily["account"].eq("vegavero/instagram/IT")].set_index("date")
    row = nf.iloc[5]
    follows, both = float(row["follower_count"]), float(row["follows_and_unfollows"])
    assert d.loc[row["date"], "new_followers"] == follows
    assert d.loc[row["date"], "unfollows"] == both - follows
    assert d.loc[row["date"], "net_follows"] == follows - (both - follows)
    assert d["net_follows"].notna().sum() == 30 and (d["unfollows"].dropna() >= 0).all()
    assert list(daily.columns) == wz.DAILY_COLS


def test_daily_frame_without_unfollow_field(raw, cfg):
    raw2 = dict(raw)
    raw2["instagram__new_followers"] = raw["instagram__new_followers"].drop(columns=["follows_and_unfollows"])
    d = wz.ig_daily_frame(raw2, cfg["instagram"])
    assert d["unfollows"].isna().all() and d["net_follows"].isna().all()
    assert d["new_followers"].notna().sum() == 4 * 30


def test_tiktok_daily_net_semantics():
    from tests.test_tiktok_organic import TT_MAP, _raw

    d = wz.tt_daily_frame(_raw(), TT_MAP)
    assert d["net_follows"].equals(d["new_followers"])  # TikTok reports the net figure
    assert "unfollows" in d.columns


# ------------------------------------------------------------------ paid views
def test_market_from_targeting():
    assert wz.market_from_targeting('{"geo_locations": {"countries": ["IT"]}}') == "IT"
    assert wz.market_from_targeting('{"geo_locations": {"countries": ["CH", "AT", "DE"]}}') == "DE"
    assert wz.market_from_targeting('{"geo_locations": {"regions": [{"country": "ES", "key": "1"}]}}') == "ES"
    assert wz.market_from_targeting('{"geo_locations": {"countries": ["IT", "DE"]}}') is None
    assert wz.market_from_targeting("{}") is None and wz.market_from_targeting(None) is None
    assert wz.market_from_targeting("not json") is None


def test_paid_views_frame_maps_instagram_placement(raw, cfg):
    pv = wz.paid_views_frame(
        raw, cfg["facebook_ad_accounts"], {"vegavero/instagram/IT", "vegavero/instagram/DE"}
    )
    assert list(pv.columns) == wz.PAID_VIEWS_COLS
    assert set(pv["account"]) == {"vegavero/instagram/IT"}  # fixture ad sets all target IT
    pl = raw["facebook__placements"]
    ig = pl[pl["publisher_platform"].eq("instagram")].copy()
    ads = raw["facebook__ads"].drop_duplicates("adset_id").set_index("adset_id")["adset_targeting"]
    ig["market"] = ig["adset_id"].map(ads).map(wz.market_from_targeting)
    mapped, promo = ig[ig["market"].eq("IT")], ig[ig["market"].isna()]  # the page-promotion ad set has no geo
    assert len(promo) > 0
    assert pv["paid_views"].sum() == pytest.approx(pd.to_numeric(mapped["impressions"]).sum())
    assert pv["paid_spend"].sum() == pytest.approx(pd.to_numeric(mapped["spend"]).sum(), rel=1e-6)
    assert pv.attrs["unmapped_spend"] == pytest.approx(pd.to_numeric(promo["spend"]).sum(), rel=1e-6)
    # unknown ad account -> dropped and counted
    pv2 = wz.paid_views_frame(raw, {}, None)
    assert pv2.empty and pv2.attrs["unmapped_spend"] == pytest.approx(
        pd.to_numeric(ig["spend"]).sum(), rel=1e-6
    )
    assert wz.paid_views_frame({k: v for k, v in raw.items() if k != "facebook__placements"}, {}).empty


def test_organic_periods_total_views_and_net(raw, cfg, daily):
    pv = wz.paid_views_frame(raw, cfg["facebook_ad_accounts"], set(cfg["instagram"].values()))
    org = am.organic_periods(daily, ig_post_metrics(wz.ig_media_frame(raw, cfg["instagram"])), "month", pv)
    it = org[org["account"].eq("vegavero/instagram/IT")].set_index("period")
    de = org[org["account"].eq("vegavero/instagram/DE")]
    assert (it["total_views"] >= it["views"]).all()
    m = int(pd.to_datetime(pv["date"]).dt.month.mode()[0])
    assert it.loc[m, "paid_views"] == pytest.approx(
        pv[pd.to_datetime(pv["date"]).dt.month.eq(m)]["paid_views"].sum()
    )
    assert it.loc[m, "total_views"] == pytest.approx(it.loc[m, "views"] + it.loc[m, "paid_views"])
    assert de["paid_views"].isna().all() and de["total_views"].equals(de["views"].astype(float))
    last = it.sort_index().iloc[-1]
    assert last["net_follows"] == pytest.approx(last["new_followers"] - last["unfollows"])
    assert "reach_unique" in org.columns and org["reach_unique"].isna().all()


# ------------------------------------------------------------------ unique reach
def test_periods_between_weeks_and_months():
    per = igr.periods_between(dt.date(2026, 9, 1), dt.date(2026, 11, 1))
    months = [p for p in per if p["period_type"] == "month"]
    assert [(p["year"], p["period"]) for p in months] == [(2026, 9), (2026, 10)]
    oct_ = months[1]
    assert oct_["since"] == dt.date(2026, 10, 1) and oct_["until"] == dt.date(2026, 10, 30)
    assert oct_["days_covered"] == 30 and oct_["days_in_period"] == 31
    assert months[0]["days_covered"] == months[0]["days_in_period"] == 30
    weeks = [p for p in per if p["period_type"] == "cw"]
    assert weeks[0]["since"] == dt.date(2026, 8, 31) and weeks[0]["period"] == 36  # ISO week containing 1 Sep
    assert all(p["until"] - p["since"] == dt.timedelta(days=6) for p in weeks)
    assert weeks[-1]["until"] == dt.date(2026, 11, 1)  # ended inside the range
    assert all(p["until"] <= dt.date(2026, 11, 1) for p in per)


class _Counting:
    def __init__(self, value: float | None = 1234.0, fail_for: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dt.date, dt.date]] = []
        self.value = value
        self.fail_for = fail_for or set()

    def period_reach(self, ig_user_id: str, since: dt.date, until: dt.date) -> float | None:
        self.calls.append((ig_user_id, since, until))
        if ig_user_id in self.fail_for:
            raise RuntimeError("boom")
        return self.value


def test_pull_period_reach_caches_settled_periods(tmp_path):
    ids = {"1": "a/instagram/IT", "2": "b/instagram/DE"}
    today = dt.date(2026, 11, 2)
    src = _Counting()
    df = igr.pull_period_reach(src, ids, tmp_path, today=today, lookback_days=60)
    n_first = len(src.calls)
    assert n_first == len(df) > 0 and set(df["account"]) == set(ids.values())
    assert (df["reach_unique"] == 1234.0).all() and df.attrs["new"] == n_first
    assert not any(p["until"] >= today for p in igr.periods_between(today - dt.timedelta(days=60), today))
    # second pull the same day: only periods that ended within SETTLE_DAYS of the fetch are requested again
    src2 = _Counting(value=99.0)
    df2 = igr.pull_period_reach(src2, ids, tmp_path, today=today, lookback_days=60)
    young = {(a, s, u) for a, s, u in src2.calls}
    assert all((today - u).days < igr.SETTLE_DAYS for _, _, u in young) and len(young) < n_first
    assert len(df2) == len(df) and (df2["reach_unique"].isin([1234.0, 99.0])).all()
    # a failing account keeps the cached rows of the others and skips its own
    src3 = _Counting(fail_for={"2"})
    df3 = igr.pull_period_reach(src3, ids, tmp_path, today=today + dt.timedelta(days=7), lookback_days=60)
    assert df3.attrs["failed"] > 0 and set(df3["account"]) == set(ids.values())
    cached = json.loads((tmp_path / igr.CACHE_NAME).read_text(encoding="utf-8"))
    assert cached["total_rows"] == len(df3) and {"since", "until", "fetched_at"} <= set(cached["data"][0])
    assert igr.load_period_reach(tmp_path / "missing").empty


def test_fixture_reach_source_and_merge(daily, cfg):
    ig_map = {k: v for k, v in cfg["instagram"].items() if v in set(daily["account"])}
    src = igr.FixtureReachSource(daily, ig_map)
    end = pd.to_datetime(daily["date"]).max().date()
    per = [p for p in igr.periods_between(end - dt.timedelta(days=60), end) if p["period_type"] == "month"][0]
    ig_id = next(k for k, v in ig_map.items() if v == "vegavero/instagram/IT")
    v = src.period_reach(ig_id, per["since"], per["until"])
    d = daily[daily["account"].eq("vegavero/instagram/IT")]
    dates = pd.to_datetime(d["date"]).dt.date
    expected = d[(dates >= per["since"]) & (dates <= per["until"])]["reach"].sum() * 0.55
    assert v == pytest.approx(expected, abs=1)
    assert src.period_reach("nope", per["since"], per["until"]) is None
    reach = pd.DataFrame(
        [
            {
                "account": "vegavero/instagram/IT",
                **per,
                "reach_unique": v,
                "fetched_at": None,
            }
        ]
    )
    org = am.organic_periods(daily, pd.DataFrame(), "month", period_reach=reach)
    row = org[org["account"].eq("vegavero/instagram/IT") & org["period"].eq(per["period"])].iloc[0]
    assert row["reach_unique"] == v and row["reach_unique_days"] == per["days_covered"]
    assert row["reach_unique"] < row["reach_daily_sum"]
    other = org[~(org["account"].eq("vegavero/instagram/IT") & org["period"].eq(per["period"]))]
    assert other["reach_unique"].isna().all()
    # quarters never sum unique reach
    q = pr.to_quarters(am.combined_periods(org, pd.DataFrame()))
    assert q["reach_unique"].isna().all() and (q["reach_daily_sum"] > 0).any()


def test_scorecard_unique_reach_only_for_exact_period(daily, cfg):
    reach = pd.DataFrame(
        [
            {
                "account": "vegavero/instagram/IT",
                "period_type": "month",
                "year": 2026,
                "period": 10,
                "since": dt.date(2026, 10, 1),
                "until": dt.date(2026, 10, 30),
                "days_covered": 30,
                "days_in_period": 31,
                "reach_unique": 250000.0,
                "fetched_at": None,
            }
        ]
    )
    pv = pd.DataFrame(
        {
            "account": ["vegavero/instagram/IT"] * 2,
            "date": [dt.date(2026, 10, 2), dt.date(2026, 10, 20)],
            "paid_views": [1000.0, 500.0],
            "paid_video_plays": [1, 1],
            "paid_spend": [1.0, 1.0],
        }
    )
    d = daily[pd.to_datetime(daily["date"]).dt.month.eq(10)]
    out = sc.organic_kpis(
        d, pd.DataFrame(), dt.date(2026, 10, 1), dt.date(2026, 10, 31), None, "Month", pv, reach
    )
    it = out.set_index("account").loc["vegavero/instagram/IT"]
    assert it["reach_unique"] == 250000.0  # full month selected: the 1st–30th window counts as the month
    assert it["paid_views"] == 1500.0 and it["total_views"] == pytest.approx(it["views"] + 1500.0)
    assert it["net_follows"] == pytest.approx(it["new_followers"] - it["unfollows"])
    de = out.set_index("account").loc["vegavero/instagram/DE"]
    assert np.isnan(de["reach_unique"]) and np.isnan(de["paid_views"]) and de["total_views"] == de["views"]
    part = sc.organic_kpis(
        d, pd.DataFrame(), dt.date(2026, 10, 5), dt.date(2026, 10, 31), None, "Month", pv, reach
    )
    assert np.isnan(part.set_index("account").loc["vegavero/instagram/IT", "reach_unique"])
    assert list(out.columns) == sc.ORGANIC_COLS
