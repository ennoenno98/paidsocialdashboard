"""Scorecard transforms and the planning-tab parser."""

from __future__ import annotations

import datetime as dt

import openpyxl
import pandas as pd

from src.ingest import klar_sheet as ks
from src.transform import scorecard as sc


def _klar() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "brand": ["vegavero"] * 4 + ["wowtamins"] * 2,
            "influencer_name": [
                "fit_giulia",
                "fit_giulia",
                "@anna.eats.well",
                "yogamitlena",
                "Silke Schwekutsch",
                "liisawood",
            ],
            "campaign_name": ["Performance", "Brand", "Brand", "", "Silke Schwekutsch", ""],
            "platform": ["Instagram", "Instagram", "Instagram", "Instagram", "Affiliate", "Instagram"],
            "category": ["Lifestyle", "Lifestyle", None, "Vegan", "Affiliate", "Mum"],
            "posting_date": pd.to_datetime(
                ["2026-10-20", "2026-09-01", "2026-10-05", "2026-10-10", "2026-10-01", "2026-10-13"]
            ),
            "costs": [3000.0, 1200.0, 1500.0, 800.0, 999.0, 500.0],
            "orders": [30, 5, 10, 0, 50, 20],
            "net_revenue": [2400.0, 300.0, 600.0, 0.0, 5000.0, 1100.0],
            "new_customers": [20, 4, 8, 0, 10, 18],
            "reach": [0, 0, 0, 0, 0, 0],
        }
    )


def test_period_bounds():
    today = dt.date(2026, 10, 27)
    assert sc.period_bounds("last_month", today)[:2] == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert sc.period_bounds("this_quarter", today)[:2] == (dt.date(2026, 10, 1), dt.date(2026, 10, 26))
    assert sc.period_bounds("last_quarter", today)[:2] == (dt.date(2026, 7, 1), dt.date(2026, 9, 30))
    assert sc.period_bounds("ytd", today)[0] == dt.date(2026, 1, 1)


def test_influencer_kpis_goal_tier_industry_and_reach():
    attrs = pd.DataFrame(
        {
            "handle": ["fit_giulia", "anna.eats.well", "yogamitlena"],
            "tier": ["Macro", "Micro", "Unknown"],
            "category_ws": ["Lifestyle", "Vegan Foodie", "Active"],
            "goal_ws": ["Performance", "Brand", "Performance"],
            "followers_ws": [52000, 8000, None],
        }
    )
    reach = pd.DataFrame(
        {
            "handle": ["fit_giulia", "anna.eats.well"],
            "post_url": [None, None],
            "date": pd.to_datetime(["2026-10-20", "2026-10-01"]),
            "reach": [41000, 9000],
            "source": ["klar_sheet", "worksheet"],
        }
    )
    kpi, br = sc.influencer_kpis(_klar(), attrs, reach, dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    v = kpi.set_index("brand").loc["vegavero"]
    assert v["costs"] == 5300 and v["n_creators"] == 3  # the September row is out of period
    assert v["roas"] == (2400 + 600) / 5300
    # reach: exact date match for fit_giulia (41k), month match for anna (9k, posted 05.10, reach dated 01.10)
    assert (
        v["reach"] == 50000
        and abs(v["cpm"] - 4500 / 50000 * 1000) < 1e-9
        and abs(v["reach_coverage"] - 4500 / 5300) < 1e-9
    )
    # yogamitlena has no campaign name in Klar -> goal from the planning tab (Performance)
    assert abs(v["share_performance"] - 3800 / 5300) < 1e-9 and abs(v["roas_performance"] - 2400 / 3800) < 1e-9
    w = kpi.set_index("brand").loc["wowtamins"]
    assert w["costs"] == 500  # affiliate row excluded
    goal = br[br["dimension"].eq("goal") & br["brand"].eq("vegavero")].set_index("value")
    assert (
        goal.loc["Performance", "costs"] == 3000 + 800
    )  # yogamitlena: empty campaign name -> worksheet goal
    assert goal.loc["Brand (awareness)", "costs"] == 1500
    tier = br[br["dimension"].eq("tier") & br["brand"].eq("vegavero")].set_index("value")
    assert tier.loc["Macro", "costs"] == 3000 and tier.loc["Unknown", "costs"] == 800
    ind = br[br["dimension"].eq("industry") & br["brand"].eq("vegavero")].set_index("value")
    assert ind.loc["Vegan Foodie", "costs"] == 1500  # Klar category empty -> worksheet category


def test_organic_kpis_from_fixture_bundle():
    from src.pipeline import build_bundle

    b = build_bundle()
    end = pd.to_datetime(b.ig_daily["date"]).max().date()
    org = sc.organic_kpis(b.ig_daily, b.monthly_wide, end - dt.timedelta(days=29), end)
    ig = org[org["platform"].eq("instagram")]
    assert len(ig) == 4 and (ig["new_followers_days"] == 30).all() and (ig["views"] > 0).all()
    assert (org[org["platform"].eq("tiktok")]["source"] == "sheet").all()


def test_worksheet_parser_and_attributes(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dashboard"
    ws.append(["Do not delete rows!"])
    ws.append(["Always enter your input"])
    ws.append(
        [
            "Country",
            "Name",
            "Link",
            "Status",
            "Month",
            "Note",
            "1st Go Live",
            "Asset",
            "Plattform",
            "Category",
            "Tier",
            "Goal",
            "Type of Partnership",
            "Cost",
            "Code",
            "Link",
            "KLAR Integration",
            "Reach",
        ]
    )
    ws.append(
        [
            "IT",
            "fit_giulia",
            "",
            "booked",
            "October",
            "",
            dt.datetime(2026, 10, 20),
            "Reel",
            "Instagram",
            "Lifestyle",
            "Macro",
            "Performance",
            "Paid",
            3000,
            "GIULIA10",
            "",
            "",
            41000,
        ]
    )
    ws.append(
        [
            "DE",
            "@anna.eats.well",
            "",
            "booked",
            "October",
            "",
            None,
            "Story",
            "Instagram",
            "Vegan Foodie",
            "",
            "Brand",
            "Paid",
            "1.500,00 €",
            "ANNA10",
            "",
            "",
            None,
        ]
    )
    lib = wb.create_sheet("Library Germany")
    lib.append(["Name", "", "", "Followers", "Link"])
    lib.append(["Anna", "@anna.eats.well", "@anna.eats.well", 8000, "https://instagram.com/anna.eats.well"])
    path = tmp_path / "Influencer Testbrand.xlsx"
    wb.save(path)
    df = ks.parse_worksheet(path, "testbrand", year=2026)
    assert len(df) == 2 and df.iloc[1]["cost"] == 1500.0 and df.iloc[1]["handle"] == "anna.eats.well"
    assert df.iloc[1]["go_live"] == pd.Timestamp("2026-10-01")  # month name -> first of month
    attrs = ks.creator_attributes(df, ks.library_followers(path))
    a = attrs.set_index("handle")
    assert a.loc["fit_giulia", "tier"] == "Macro" and a.loc["fit_giulia", "tier_source"] == "worksheet"
    assert (
        a.loc["anna.eats.well", "tier"] == "Micro"
        and a.loc["anna.eats.well", "tier_source"] == "derived from followers"
    )
    r = ks.worksheet_reach(df)
    assert list(r["handle"]) == ["fit_giulia"] and r.iloc[0]["reach"] == 41000
