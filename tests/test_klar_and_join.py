from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingest import klar
from src.transform.join import join_klar_creators

FIX = Path(__file__).parent / "fixtures" / "klar_influencer_flex.json"


def test_fixture_client_and_frame(tmp_path):
    df, raw = klar.pull_klar(
        klar.FixtureKlarClient(FIX), days=400, end_date=dt.date(2026, 10, 25), raw_dir=tmp_path
    )
    assert raw.name == "2026-10-25.json" and json.loads(raw.read_text())["rows"]
    assert {
        "influencer_name",
        "platform",
        "discount_code",
        "posting_date",
        "date",
        "costs",
        "orders",
        "net_revenue",
    } <= set(df.columns)
    assert (df["platform"].isin(["instagram", "tiktok"])).all()  # normalised to lower case
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_creator_summary():
    df = klar.klar_frame(json.loads(FIX.read_text())["rows"])
    s = klar.creator_summary(df, until=dt.date(2026, 10, 25))
    g = s[s["influencer_name"] == "Giulia Fit"].iloc[0]
    assert g["costs"] == 450 and g["roas"] == pytest.approx(g["net_revenue"] / 450)
    assert g["cac"] == pytest.approx(450 / g["new_customers"])
    assert pd.isna(g["cpm_klar"])  # Klar reach == 0 -> never a CPM from zero reach
    assert bool(s[s["influencer_name"] == "Old Partner"].iloc[0]["active_recent"]) is False


def test_http_client_refuses_to_guess(monkeypatch):
    monkeypatch.setenv("KLAR_API_KEY", "k")
    monkeypatch.setenv("KLAR_SHOP_ID", "s")
    monkeypatch.delenv("KLAR_INFLUENCER_REPORT_PATH", raising=False)
    c = klar.HttpKlarClient()
    with pytest.raises(NotImplementedError):
        c.fetch(dt.date(2026, 1, 1), dt.date(2026, 1, 2), klar.DIMENSIONS, klar.METRICS)


def test_date_chunks_31_days():
    ch = klar.date_chunks(dt.date(2026, 1, 1), dt.date(2026, 3, 5), 31)
    assert ch[0] == (dt.date(2026, 1, 1), dt.date(2026, 1, 31)) and ch[-1][1] == dt.date(2026, 3, 5)
    assert all((b - a).days < 31 for a, b in ch)


def test_join_code_then_fuzzy_then_unmatched():
    klar_df = pd.DataFrame(
        [
            {"influencer_name": "Giulia Fit", "discount_code": "giulia10 ", "costs": 1},
            {"influencer_name": "Anna eats well", "discount_code": None, "costs": 1},  # fuzzy on name
            {"influencer_name": "yogamitlena", "discount_code": "WRONG", "costs": 1},  # fuzzy on handle
            {"influencer_name": "Somebody Else", "discount_code": None, "costs": 1},
        ]
    )
    creators = pd.DataFrame(
        [
            {
                "name": "Giulia Fit",
                "handle": "fit_giulia",
                "platform": "instagram",
                "code": "GIULIA10",
                "followers": 1,
                "deal": "paid",
                "country": "IT",
                "field": "f",
            },
            {
                "name": "Anna Eats Well",
                "handle": "anna.eats.well",
                "platform": "instagram",
                "code": "ANNA15",
                "followers": 1,
                "deal": "product",
                "country": "DE",
                "field": "f",
            },
            {
                "name": "Lena Yoga",
                "handle": "yogamitlena",
                "platform": "tiktok",
                "code": "LENA10",
                "followers": 1,
                "deal": "free",
                "country": "DE",
                "field": "f",
            },
            {
                "name": "Never Matched",
                "handle": "nm",
                "platform": "instagram",
                "code": "NM1",
                "followers": 1,
                "deal": "free",
                "country": "DE",
                "field": "f",
            },
        ]
    )
    out = join_klar_creators(klar_df, creators, threshold=85)
    m = out["matched"].set_index("influencer_name")
    assert m.loc["Giulia Fit", "match_method"] == "discount_code"
    assert (
        m.loc["Anna eats well", "match_method"] == "fuzzy_name"
        and m.loc["Anna eats well", "creator_handle"] == "anna.eats.well"
    )
    assert (
        m.loc["yogamitlena", "match_method"] == "fuzzy_name"
        and m.loc["yogamitlena", "creator_name"] == "Lena Yoga"
    )
    assert list(out["unmatched_klar"]["influencer_name"]) == ["Somebody Else"]
    assert list(out["unmatched_creators"]["name"]) == ["Never Matched"]
