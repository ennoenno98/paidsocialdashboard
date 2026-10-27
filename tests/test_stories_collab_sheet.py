"""Stories accumulation, Collab posts, Klar sheet parsing and the quarter helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from app.common import quarter_of, with_quarter
from src.ingest import klar_sheet as ks
from src.ingest import windsor as wz
from src.ingest.xlsx import load_config
from src.pipeline import build_bundle
from src.transform import api_metrics as am

FIX = Path(__file__).parent / "fixtures"


def test_klar_sheet_parser():
    df = ks.load_klar_sheets(FIX / "klar_sheets")
    assert len(df) == 4 and set(df["brand"]) == {"testbrand"}
    assert list(df["handle"]).count("fit_giulia") == 2  # display name row resolved via the profile link
    assert ks.alias_map(df)["giulia fit"] == "fit_giulia"
    g = df[df["influencer_name"].eq("fit_giulia")].set_index("handle")
    assert g.loc["fit_giulia", "reach"] == 41000 and g.loc["fit_giulia", "fixed_costs"] == 3000.0
    assert g.loc["fit_giulia", "market"] == "IT"  # Custom Dimension 2
    g2 = df.drop_duplicates("handle", keep="first").set_index("handle")
    assert g2.loc["anna.eats.well", "market"] == "DE"  # '@' stripped
    assert g.loc["fit_giulia", "posting_date"] == pd.Timestamp("2026-10-20")
    assert bool(g2.loc["yogamitlena", "status_ok"]) is False and pd.isna(
        g2.loc["yogamitlena", "posting_date"]
    )
    master = ks.creator_master(df)
    assert set(master["handle"]) == {"fit_giulia", "anna.eats.well", "yogamitlena"}
    mg = master.set_index("handle")
    assert mg.loc["fit_giulia", "n_campaigns"] == 2 and mg.loc["fit_giulia", "n_campaigns_with_reach"] == 1
    reach = ks.sheet_reach(df)
    assert list(reach["handle"]) == ["fit_giulia"] and (reach["source"] == "klar_sheet").all()
    missing = ks.campaigns_missing_reach(df)
    assert set(missing["handle"]) == {
        "fit_giulia",
        "anna.eats.well",
        "yogamitlena",
    }  # the reel row has reach, the second Giulia row not


def test_collab_posts_are_separated():
    raw = wz.load_raw(wz.CachedWindsorSource(FIX / "windsor"))
    cfg = load_config()["windsor"]
    media = wz.ig_media_frame(raw, cfg["instagram"])
    collab = media[media["relationship"].eq("collaborative")]
    assert len(collab) == 1 and collab.iloc[0]["owner_username"] == "fit_giulia"
    assert (media.loc[media["relationship"].eq("owned"), "owner_username"] != "fit_giulia").all()
    b = build_bundle()
    assert len(b.collab_posts) == 1 and b.collab_posts["er"].isna().all()  # no reach -> ER n/a
    # own-post counts exclude the collab post
    own = b.ig_posts[b.ig_posts["relationship"].eq("owned")]
    assert b.api_monthly["n_posts"].sum() == len(own)
    assert b.influencers.set_index("creator_handle").loc["fit_giulia", "reach_source"] == "klar_sheet"


def test_stories_frame_and_periods():
    raw = wz.load_raw(wz.CachedWindsorSource(FIX / "windsor"))
    cfg = load_config()["windsor"]
    s = wz.ig_stories_frame(raw, cfg["instagram"])
    assert len(s) == 12 and s["story_id"].is_unique and set(s["account"]).issubset(cfg["instagram"].values())
    per = am.story_periods(s, "cw")
    assert per["n_stories"].sum() == 12 and (per["story_exit_rate"].dropna() <= 1).all()
    comb = am.combined_periods(
        am.organic_periods(wz.ig_daily_frame(raw, cfg["instagram"]), pd.DataFrame(), "cw"),
        pd.DataFrame(),
        per,
    )
    assert "n_stories" in comb.columns and comb["n_stories"].sum() == 12


def test_accumulate_rows_keeps_history(tmp_path):
    old = [{"story_id": "a", "story_views": 1}, {"story_id": "b", "story_views": 2}]
    new = [{"story_id": "b", "story_views": 5}, {"story_id": "c", "story_views": 3}, {"story_id": None}]
    merged = {r["story_id"]: r["story_views"] for r in wz.accumulate_rows(old, new, "story_id")}
    assert merged == {"a": 1, "b": 5, "c": 3}
    # pull_all accumulates the stories pull across runs
    src = wz.CachedWindsorSource(FIX / "windsor")
    wz.pull_all(src, tmp_path, pulls=["instagram__stories"])
    n1 = len(wz.CachedWindsorSource(tmp_path).fetch("instagram__stories"))

    class Extra:
        def fetch(self, pull: str) -> list[dict]:
            return [
                {
                    "story_id": "brand-new",
                    "account_id": "17841404238631874",
                    "story_views": 9,
                    "date": "2026-10-27",
                }
            ]

    wz.pull_all(Extra(), tmp_path, pulls=["instagram__stories"])
    assert len(wz.CachedWindsorSource(tmp_path).fetch("instagram__stories")) == n1 + 1


def test_quarter_helpers():
    assert quarter_of("month", 2026, 11) == "Q4 2026"
    assert quarter_of("cw", 2026, 1) == "Q1 2026" and quarter_of("cw", 2026, 40) == "Q4 2026"
    df = pd.DataFrame({"year": [2026, 2026], "period": [3, 27], "period_type": ["month", "cw"]})
    assert list(with_quarter(df)["quarter"]) == ["Q1 2026", "Q3 2026"]
    ts = pd.DataFrame({"timestamp": [pd.Timestamp(dt.datetime(2026, 8, 3, tzinfo=dt.UTC))]})
    assert with_quarter(ts)["quarter"].iloc[0] == "Q3 2026"
