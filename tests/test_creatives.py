"""Paid creatives: name parser, funnel stage rules, aggregation / ratios, verdicts, tags, tests, LLM tagging."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.ingest import input_sheet as inp
from src.ingest import klar_marketing as km
from src.ingest import windsor as wz
from src.transform import creative_tagging as ct
from src.transform import creatives as cr

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cfg():
    return cr.load_creatives_config()


@pytest.fixture(scope="module")
def ads_raw(cfg):
    raw = wz.load_raw(wz.CachedWindsorSource(FIX / "windsor"))
    return wz.ads_frame(raw, cfg["ad_accounts"], cfg.get("ads_manager"))


@pytest.fixture(scope="module")
def klar():
    return km.load_klar_marketing(FIX / "klar_marketing")


@pytest.fixture(scope="module")
def ads(cfg, ads_raw, klar):
    enriched, _ = km.allocate_to_ads(cr.enrich_ads(ads_raw, cfg), klar)
    return enriched


def test_parse_ad_name(cfg):
    p = cr.parse_ad_name("IT_PPLImage_MagnesioBisglicinatoCapsule_FormDoseOffer_ProductCard_v1_202605", cfg)
    assert p["parsed"] and p["market"] == "IT" and p["format"] == "static"
    assert p["product"] == "Magnesium Bisglycinate" and p["concept"] == "FormDoseOffer"
    assert p["style"] == "ProductCard" and p["version"] == "V1" and p["launch_month"] == "2026-05"
    p = cr.parse_ad_name(
        "Test-Hand_IT_PPLImage_Vollagen_VeganCollagenAlternative_HumanContext_V01_202607", cfg
    )
    assert p["variant"] == "Test-Hand" and p["product"] == "Vollagen"
    p = cr.parse_ad_name("IT_Carousel_MultiMagnesioComplexCapsule_4FormsB2B6_StaticCards_V01_202607_LP", cfg)
    assert p["variant"] == "LP" and p["format"] == "carousel" and p["launch_month"] == "2026-07"
    p = cr.parse_ad_name("IT_PPLImage_BetaCarotene_FreeGiftSurprise_Static_v1_202605 – Copy 2", cfg)
    assert p["variant"] == "Copy 2" and p["product"] == "Beta Carotene"
    p = cr.parse_ad_name("IT_PPLVideo_MultiMagnesio_Creator_PDP_202607", cfg)
    assert p["format"] == "video" and p["variant"] == "PDP" and p["version"] is None
    assert not cr.parse_ad_name("[04/09/2026] Promoting Vegavero Italia", cfg)["parsed"]
    assert not cr.parse_ad_name(None, cfg)["parsed"]


def test_tags_from_name(cfg):
    p = cr.parse_ad_name("IT_PPLImage_Omega3Oil_AlgaeSource_Infographic_v1_202608", cfg)
    t = cr.tags_from_name(p, "IT_PPLImage_Omega3Oil_AlgaeSource_Infographic_v1_202608", cfg)
    assert t == {"visual_subject": "infographic", "claim": "vegan", "offer": "none"}
    p = cr.parse_ad_name("IT_PPLImage_MultiMagnesioComplexCapsule_GWP_Static_V01_202610", cfg)
    t = cr.tags_from_name(p, "x_GWP_x", cfg)
    assert t["offer"] == "gwp" and t["claim"] == "offer"
    p = cr.parse_ad_name(
        "Test-Hand_IT_PPLImage_Vollagen_VeganCollagenAlternative_HumanContext_V01_202607", cfg
    )
    assert cr.tags_from_name(p, "", cfg)["visual_subject"] == "hand"


def test_funnel_stage(cfg):
    rules = cfg["funnel_stage_rules"]
    assert cr.funnel_stage("AO_IT_SALES_RTG", "x", "{}", rules) == "retargeting"
    assert cr.funnel_stage("AO_IT_SALES_PROSPECTING_VOLUME", "IC_it_broad", "{}", rules) == "prospecting"
    ca = json.dumps({"custom_audiences": [{"id": "1", "name": "All website visitors"}]})
    assert cr.funnel_stage("x", "y", ca, rules) == "retargeting"
    excl = json.dumps({"excluded_custom_audiences": [{"id": "1"}], "geo_locations": {}})
    assert cr.funnel_stage("x", "y", excl, rules) == "prospecting"
    assert cr.funnel_stage("x", "y", "not json", rules) == "unknown"
    assert cr.funnel_stage("x", "y", None, rules) == "unknown"


def test_ads_frame_and_enrich(ads, ads_raw, cfg):
    assert not ads["is_boost"].any()  # Instagram post boosts are dropped (Organic vs Boosted owns them)
    assert ads["ads_manager_url"].str.contains("selected_ad_ids=").all()
    assert ads["ads_manager_url"].str.contains("business_id=2170679796749670").all()  # configured
    assert wz.ads_manager_url("1", None) is None
    u = wz.ads_manager_url("11", "22", {"business_id": "33"})
    assert u == (
        "https://adsmanager.facebook.com/adsmanager/manage/ads?act=11&business_id=33&global_scope_id=33"
        "&selected_ad_ids=22&nav_entry_point=lep_237"
    )
    assert wz.ads_manager_url("11", "22", {"business_id": ""}) == (
        "https://adsmanager.facebook.com/adsmanager/manage/ads?act=11&selected_ad_ids=22&nav_entry_point=lep_237"
    )
    assert (
        wz.ads_manager_url("11", "22", {"url_template": "https://x/{ad_id}?a={account_id}"})
        == "https://x/22?a=11"
    )
    agg = cr.aggregate_assets(ads, by=["asset_id"])
    assert agg["ads_manager_url"].notna().all()
    assert not ads["campaign"].str.startswith("[").any()  # page promotions are excluded, not tagged
    assert set(ads["funnel_stage"]) == {"prospecting", "retargeting", "unknown"}
    bad = ads[~ads["parsed"].astype(bool)]
    assert bad["asset_id"].unique().tolist() == ["Omega3 vecchia creativita senza convenzione"]
    assert ads["goal"].isin(["conversion", "value", "landing_page_view", "leads"]).all()
    ex = cr.excluded_spend(ads_raw, cfg)
    assert ex["instagram_post_boosts"] > 0 and ex["page_promotions"] > 0 and "organic_objectives" not in ex
    # organic objectives and other markets are dropped
    extra = ads_raw.head(2).copy()
    extra["optimization_goal"] = "VISIT_INSTAGRAM_PROFILE"
    de = ads_raw.head(1).copy()
    de["ad_name"] = "DE_PPLImage_Vollagen_VeganCollagenAlternative_Static_V01_202605"
    both = pd.concat([ads_raw, extra, de], ignore_index=True)
    e2 = cr.enrich_ads(both, cfg)
    assert not e2["optimization_goal"].eq("VISIT_INSTAGRAM_PROFILE").any()
    assert not e2["market"].eq("DE").any()
    assert cr.excluded_spend(both, cfg)["organic_objectives"] == pytest.approx(extra["spend"].sum())
    assert cr.excluded_spend(both, cfg)["other_markets"] == pytest.approx(de["spend"].sum())


def test_klar_loader_and_allocation(klar, ads_raw, cfg):
    assert set(klar.columns) == set(km.KLAR_COLS)
    assert klar["channel_name"].str.contains("Meta").all()  # Email rows dropped
    assert not klar.duplicated(["date", "campaign", "ad_name"]).any()
    enriched = cr.enrich_ads(ads_raw, cfg)
    out, unmatched = km.allocate_to_ads(enriched, klar)
    # totals preserved: every matched Klar row lands fully on the ad rows
    assert out["klar_orders"].sum() + unmatched["klar_orders"].sum() == pytest.approx(
        klar["klar_orders"].sum()
    )
    assert out["klar_gross_revenue"].sum() + unmatched["klar_gross_revenue"].sum() == pytest.approx(
        klar["klar_gross_revenue"].sum()
    )
    assert unmatched["ad_name"].tolist() == ["IT_PPLImage_Unknown_ToTheFeed_Static_V01_202601"]
    # split across the ad sets of one (date, campaign, asset) in proportion to spend
    multi = out[out["klar_matched"]].groupby(["date", "campaign", "asset_id"]).filter(lambda g: len(g) > 1)
    if not multi.empty:
        g = multi.groupby(["date", "campaign", "asset_id"]).first().index[0]
        rows = out[(out["date"] == g[0]) & (out["campaign"] == g[1]) & (out["asset_id"] == g[2])]
        assert rows["klar_orders"].sum() / rows["klar_orders"].sum() == pytest.approx(1)
        assert (rows["klar_cost"] / rows["klar_cost"].sum()).to_numpy() == pytest.approx(
            (rows["spend"] / rows["spend"].sum()).to_numpy()
        )
    assert (~out["klar_matched"]).any() and out.loc[~out["klar_matched"], "klar_orders"].isna().all()
    empty, un = km.allocate_to_ads(enriched, klar.iloc[0:0])
    assert empty["klar_orders"].isna().all() and un.empty
    assert km.load_klar_marketing(FIX / "nope").empty


def test_aggregate_ratios_from_sums(ads):
    a = cr.aggregate_assets(ads)
    assert list(a.columns[:3]) == ["asset_id", "funnel_stage", "goal"]
    row = a[
        a["asset_id"].str.contains("VeganCollagenAlternative_Static") & a["funnel_stage"].eq("prospecting")
    ].iloc[0]
    src = ads[
        ads["asset_id"].eq(row["asset_id"])
        & ads["funnel_stage"].eq("prospecting")
        & ads["goal"].eq(row["goal"])
    ]
    assert row["spend"] == pytest.approx(src["spend"].sum())
    assert row["ctr_link"] == pytest.approx(src["link_clicks"].sum() / src["impressions"].sum())
    assert row["roas_meta"] == pytest.approx(src["purchase_value"].sum() / src["spend"].sum())
    assert row["cpa_meta"] == pytest.approx(src["spend"].sum() / src["purchases"].sum())
    assert row["cpm"] == pytest.approx(src["spend"].sum() / src["impressions"].sum() * 1000)
    # Klar is the ROAS source when matched: gross revenue / Meta spend, orders from Klar
    assert row["roas_source"] == "klar"
    assert row["roas"] == pytest.approx(src["klar_gross_revenue"].sum() / src["spend"].sum())
    assert row["orders"] == pytest.approx(src["klar_orders"].sum())
    assert row["cpa"] == pytest.approx(src["spend"].sum() / src["klar_orders"].sum())
    meta_only = cr.aggregate_assets(ads, roas_source="meta")
    assert (meta_only["roas_source"] == "meta").all() and meta_only["roas"].equals(meta_only["roas_meta"])
    # the same asset appears once per stage, never collapsed
    assert set(a[a["asset_id"].eq(row["asset_id"])]["funnel_stage"]) == {"prospecting", "retargeting"}
    vid = a[a["asset_type"].eq("video")]
    assert vid["hook_rate"].notna().all() and a[a["asset_type"].eq("static")]["hook_rate"].isna().all()
    # period window
    end = ads["date"].max()
    w = cr.aggregate_assets(ads, end - dt.timedelta(days=6), end)
    assert w["spend"].sum() == pytest.approx(ads[ads["date"] >= end - dt.timedelta(days=6)]["spend"].sum())
    assert cr.aggregate_assets(ads.iloc[0:0]).empty


def test_verdicts(ads, cfg):
    a = cr.judge_and_verdict(cr.aggregate_assets(ads), cfg)
    tg = a.attrs["targets"]
    rev = a["klar_gross_revenue"].where(a["roas_source"].eq("klar"), a["purchase_value"]).fillna(0)
    assert tg["roas"] == pytest.approx(rev.sum() / a["spend"].sum())
    assert (a.loc[a["goal"].isin(["conversion", "value"]), "judge_kpi"] == "roas").all()
    assert (a.loc[a["goal"].isin(["landing_page_view", "leads"]), "judge_kpi"] == "ctr_link").all()
    ok = a[a["verdict"].isin(["Performing", "Underperforming"])]
    assert ((ok["kpi_value"] >= ok["target"]) == (ok["verdict"] == "Performing")).all()
    pinned = cr.judge_and_verdict(cr.aggregate_assets(ads), cfg, targets={"roas": 100.0})
    assert (
        pinned.loc[pinned["judge_kpi"].eq("roas") & pinned["verdict"].ne("Low data"), "verdict"]
        == "Underperforming"
    ).all()
    assert cr.judge_and_verdict(a.iloc[0:0], cfg).attrs["targets"] == {}


def test_verdicts_na_safe_and_direction(ads, cfg):
    """Regression: the live feed produced nullable Float64 ratios with pd.NA (zero-spend rows) that crashed the
    verdict comparison; and lower-is-better KPIs must be judged the right way round."""
    a = cr.aggregate_assets(ads)
    assert all(str(a[c].dtype) == "float64" for c in cr.RATIO_COLS if c in a.columns)
    nullable = a.copy()
    for c in ("roas", "ctr_link", "cpa", "cpm"):
        nullable[c] = nullable[c].astype("Float64")
    nullable.loc[nullable.index[:2], ["roas", "ctr_link"]] = pd.NA
    nullable.loc[nullable.index[0], "spend"] = 5000.0
    v = cr.judge_and_verdict(nullable, cfg)
    assert str(v["kpi_value"].dtype) == "float64" and str(v["target"].dtype) == "float64"
    assert v["verdict"].iloc[0] == "Low data"  # NA KPI despite spend -> Low data, no crash
    # lower is better: judge every row on CPM with a pinned target
    cheap = a.copy()
    cheap["goal"] = "reach"  # kpi_by_goal: reach -> cpm
    v = cr.judge_and_verdict(cheap, cfg, targets={"cpm": 3.0})
    ok = v[v["verdict"].isin(["Performing", "Underperforming"])]
    assert (ok["judge_kpi"] == "cpm").all()
    assert ((ok["kpi_value"] <= 3.0) == (ok["verdict"] == "Performing")).all()
    # a KPI without a target falls back to default_kpi instead of blanket Low data
    odd = dict(cfg)
    odd["kpi_by_goal"] = {**cfg["kpi_by_goal"], "conversion": "thruplay_rate"}
    v = cr.judge_and_verdict(a, odd)
    assert (v.loc[v["goal"].eq("conversion"), "judge_kpi"] == "roas").all()
    # empty frame: float dtypes on both paths
    e = cr.judge_and_verdict(a.iloc[0:0], cfg)
    assert str(e["target"].dtype) == "float64" and str(e["kpi_value"].dtype) == "float64"
    # frames that skipped allocate_to_ads still aggregate and build matrices
    bare = ads.drop(columns=[*cr.KLAR_SUM, "klar_matched"])
    agg = cr.aggregate_assets(bare)
    assert (~agg["klar_matched"]).all() and agg["klar_orders"].isna().all()
    assert not cr.kpi_matrix(agg, "product", "roas").empty


def test_tests_table_na_safe(ads, cfg):
    tests = inp.load_tests(FIX / "input_sheet")
    allst = cr.aggregate_assets(ads, by=["asset_id"])
    allst["ctr_link"] = allst["ctr_link"].astype("Float64")
    allst.loc[allst["asset_id"].str.startswith("Test-Hand"), "ctr_link"] = pd.NA
    tt = cr.tests_table(tests, allst, cfg)
    assert str(tt["kpi_value"].dtype) == "float64"
    hand = tt[tt["asset_id"].str.startswith("Test-Hand")].iloc[0]
    assert hand["result"] == "No data" and pd.isna(hand["kpi_value"])


def test_merge_tags_precedence(ads):
    a = cr.aggregate_assets(ads, by=["asset_id"])
    manual = inp.load_creative_tags(FIX / "input_sheet")
    llm = pd.DataFrame(
        [
            {
                "asset_id": a["asset_id"].iloc[0],
                "visual_subject": "lifestyle",
                "claim": "vegan",
                "offer": None,
                "hook": "LLM hook",
            }
        ]
    )
    m = cr.merge_tags(a, llm, manual)
    first = m[m["asset_id"].eq(a["asset_id"].iloc[0])].iloc[0]
    assert (
        first["visual_subject"] == "lifestyle"
        and first["hook"] == "LLM hook"
        and first["tag_source"] == "llm"
    )
    inf = m[m["asset_id"].eq("IT_PPLImage_Omega3Oil_AlgaeSource_Infographic_v1_202608")].iloc[0]
    assert inf["claim"] == "lab_tested" and inf["tag_source"] == "manual"  # manual beats naming (vegan)
    chiara = m[m["asset_id"].eq("IT_PPLVideo_FemaleBalance_Routine_Chiara_v1_202608")].iloc[0]
    assert chiara["claim"] is None or pd.isna(
        chiara["claim"]
    )  # empty manual cell leaves the derived tag (none)
    assert chiara["hook"].startswith("Chiara")
    unnamed = m[m["asset_id"].eq("Omega3 vecchia creativita senza convenzione")].iloc[0]
    assert unnamed["tag_source"] == "none"


def test_kpi_matrix(ads):
    a = cr.judge_and_verdict(cr.merge_tags(cr.aggregate_assets(ads)))
    pro = a[a["funnel_stage"].eq("prospecting")]
    m = cr.kpi_matrix(pro, "visual_subject", "roas")  # columns = optimisation goal inside a stage view
    cell = m[m["visual_subject"].eq("product_only") & m["goal"].eq("conversion")].iloc[0]
    src = pro[pro["visual_subject_name"].eq("product_only") & pro["goal"].eq("conversion")]
    assert cell["roas"] == pytest.approx(src["klar_gross_revenue"].sum() / src["spend"].sum())
    assert cell["n_assets"] == src["asset_id"].nunique()
    assert "untagged" in set(m["visual_subject"])
    stage = cr.kpi_matrix(a, "claim", "ctr_link", col_dim="funnel_stage")
    assert set(stage["funnel_stage"]) <= {"prospecting", "retargeting", "unknown"}


def test_tests_table(ads, cfg):
    tests = inp.load_tests(FIX / "input_sheet")
    assert set(tests["test_id"]) == {"T01", "T07"}  # example row skipped
    allst = cr.aggregate_assets(ads, by=["asset_id"])
    tt = cr.tests_table(tests, allst, cfg)
    t1 = tt[tt["test_id"].eq("T01")]
    assert t1["primary_kpi"].eq("ctr_link").all() and list(t1["rank"]) == [1, 2, 3]
    assert t1.iloc[0]["result"] in {"Winner", "Tie"} and t1.iloc[-1]["result"] in {"Lost", "Tie"}
    t7 = tt[tt["test_id"].eq("T07")]
    assert t7.iloc[0]["kpi_value"] >= t7.iloc[1]["kpi_value"]
    missing = cr.tests_table(
        pd.DataFrame([{"test_id": "T9", "asset_id": "nope", "primary_kpi": "roas"}]), allst, cfg
    )
    assert missing.iloc[0]["result"] == "No data"


def test_creative_issues_and_reconcile(ads, tmp_path):
    a = cr.merge_tags(cr.aggregate_assets(ads, by=["asset_id"]))
    issues = cr.creative_issues(ads, a, tmp_path)
    msgs = " | ".join(i["message"] for i in issues)
    assert "naming convention" in msgs and "funnel stage unknown" in msgs and "thumbnail" in msgs
    assert "no Klar attribution row" in msgs  # 20 % of the fixture ad-days have no Klar row
    csv = tmp_path / "export.csv"
    name = a["asset_id"].iloc[0]
    csv.write_text(f'Ad name,Amount spent (EUR)\n"{name}",{a["spend"].iloc[0] + 10:.2f}\n', encoding="utf-8")
    rec = cr.reconcile_ads_manager(ads, csv)
    assert rec[rec["ad_name"].eq(name)]["delta"].iloc[0] == pytest.approx(-10, abs=0.01)


def test_cache_thumbnails_without_network(ads, tmp_path):
    counts = wz.cache_thumbnails(ads.head(3), tmp_path, timeout=0.5, limit=1)
    assert counts["downloaded"] == 0 and counts["failed"] == 1  # example.invalid never resolves
    (tmp_path / "1000.jpg").write_bytes(b"\xff\xd8")
    assert wz.thumbnail_path("1000", tmp_path) is not None and wz.thumbnail_path("x", tmp_path) is None


class _FakeClient:
    """Mimics ``anthropic.Anthropic().messages.create`` for the tagging pass."""

    def __init__(self, payload: dict):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self._payload))]
        )

    @property
    def _payload(self):  # noqa: ANN202
        return self.__dict__["payload"]


def test_tag_assets_once_per_asset(ads, tmp_path):
    a = cr.aggregate_assets(ads, by=["asset_id"])
    client = _FakeClient({})
    client.payload = {
        "visual_subject": "person",
        "claim": "vegan",
        "offer": "bogus",
        "hook": "one two three four five six seven eight nine",
        "rationale": "r",
    }
    out = ct.tag_assets(a, tmp_path, tmp_path / "tags.parquet", client=client)
    n_assets = len(a)
    assert client.calls == n_assets and len(out) == n_assets
    assert out["offer"].isna().all() and (out["visual_subject"] == "person").all()
    assert out["hook"].str.split().str.len().max() == 8
    again = ct.tag_assets(a, tmp_path, tmp_path / "tags.parquet", client=client)
    assert client.calls == n_assets and len(again) == n_assets  # nothing re-tagged
    assert ct.load_tags(tmp_path / "tags.parquet").equals(again)


def test_shrink_image_bounds_size_and_dimensions(tmp_path):
    import io

    from PIL import Image

    big = io.BytesIO()
    Image.new("RGB", (3000, 2000), (200, 30, 30)).save(big, format="PNG")
    small = wz.shrink_image(big.getvalue())
    assert len(small) < len(big.getvalue()) and len(small) < wz.THUMB_MAX_BYTES
    with Image.open(io.BytesIO(small)) as im:
        assert im.format == "JPEG" and max(im.size) == wz.THUMB_MAX_PX
    assert wz.shrink_image(b"not an image") == b"not an image"


def test_cache_thumbnails_reencodes_oversized_cached_files(ads, tmp_path):
    import io

    import numpy as np
    from PIL import Image

    cid = str(ads.dropna(subset=["creative_id"])["creative_id"].iloc[0])
    buf = io.BytesIO()
    noise = np.random.default_rng(0).integers(0, 255, size=(2000, 2000, 3), dtype=np.uint8)  # incompressible
    Image.fromarray(noise, "RGB").save(buf, format="JPEG", quality=100)
    (tmp_path / f"{cid}.jpg").write_bytes(buf.getvalue())
    assert (tmp_path / f"{cid}.jpg").stat().st_size > wz.THUMB_MAX_BYTES
    counts = wz.cache_thumbnails(ads.head(1), tmp_path, timeout=0.5, limit=0)
    assert counts["cached"] == 1 and counts["shrunk"] == 1
    assert (tmp_path / f"{cid}.jpg").stat().st_size < wz.THUMB_MAX_BYTES
