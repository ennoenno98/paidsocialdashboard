"""Synthetic Windsor pulls (same fields as src.ingest.windsor.PULLS) -> tests/fixtures/windsor/*.json."""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

OUT = Path(__file__).with_name("windsor")
rng = random.Random(11)
ACCOUNTS = [
    ("17841404238631874", "vegavero.italia"),
    ("17841404132673810", "vegavero.de"),
    ("17841472676539331", "jasnum.italia"),
    ("17841460265340889", "wowtamins.de"),
]
END = dt.date(2026, 10, 26)
CAPTIONS = [
    "🌱 Gennaio è il mese per rimettere in moto la routine",
    "La vera bellezza nasce dalle piccole abitudini",
    "Ende Januar ist die Routine wieder voll da",
    "5 Lebensphasen, 5 unterschiedliche Bedürfnisse",
    "Cosa faceva la nonna per affrontare i primi freddi",
    "Die Woche startet mit einem Ranking unserer Favoriten",
    "Il tuo intestino merita una coccola quotidiana",
    "Manche Symptome sind eher unspezifisch",
    "Etwas Herzhaftes 🥪, etwas Fruchtiges 🍓",
    "Wenn es draußen kälter wird, braucht der Körper mehr",
]


# Paid creatives: ad x day x ad set rows for the Vegavero IT ad account (real naming convention, synthetic numbers)
AD_ACCOUNT = ("1180996603943052", "Vegavero")
ADSETS = {  # adset_name -> (campaign, objective, optimisation goal, targeting json)
    "IC_it_broad_all-25-64_advantage-placements": (
        "AO_IT_SALES_PROSPECTING_VOLUME",
        "OUTCOME_SALES",
        "OFFSITE_CONVERSIONS",
        '{"age_min": 25, "age_max": 64, "excluded_custom_audiences": [{"id": "1", "name": "All website visitors | Last 30 days"}], "geo_locations": {"countries": ["IT"]}}',
    ),
    "it_broad_all-25-54_advantage-placements_landing-page-view": (
        "AO_IT_TRAFFIC_PROSPECTING",
        "OUTCOME_TRAFFIC",
        "LANDING_PAGE_VIEWS",
        '{"age_min": 25, "age_max": 54, "geo_locations": {"countries": ["IT"]}}',
    ),
    "PPL_it_website-visitors_all_advantage-placements_purchase": (
        "AO_IT_SALES_RTG",
        "OUTCOME_SALES",
        "VALUE",
        '{"age_min": 18, "age_max": 65, "custom_audiences": [{"id": "2", "name": "All website visitors | Last 30 days"}], "geo_locations": {"countries": ["IT"]}}',
    ),
    "IT - Open [25-64]": (
        "AO_IT_LEADS_PROSPECTING",
        "OUTCOME_LEADS",
        "LEAD_GENERATION",
        '{"age_min": 25, "age_max": 64, "geo_locations": {"countries": ["IT"]}}',
    ),
    "summer-sale_it_mystery_audience": (  # no rule matches -> funnel stage unknown (Data quality)
        "AO_IT_SALES_SUMMER",
        "OUTCOME_SALES",
        "OFFSITE_CONVERSIONS",
        "not json",
    ),
}
# ad name -> (ad sets it ran in, format for video metrics, roas tendency)
ADS = {
    "IT_PPLImage_Vollagen_VeganCollagenAlternative_Static_V01_202605": (
        [
            "IC_it_broad_all-25-64_advantage-placements",
            "PPL_it_website-visitors_all_advantage-placements_purchase",
        ],
        "static",
        1.6,
    ),
    "IT_PPLImage_MagnesiumBisglycinate_FormMatters_Static_V01_202605": (
        [
            "IC_it_broad_all-25-64_advantage-placements",
            "it_broad_all-25-54_advantage-placements_landing-page-view",
        ],
        "static",
        0.2,
    ),
    "IT_PPLImage_MyoInositolComplex_LabelComparison_Static_V01_202608": (
        ["IC_it_broad_all-25-64_advantage-placements"],
        "static",
        1.5,
    ),
    "IT_PPLImage_Omega3Oil_FishFreeMicroalgae_Static_V01_202608": (
        [
            "IC_it_broad_all-25-64_advantage-placements",
            "PPL_it_website-visitors_all_advantage-placements_purchase",
        ],
        "static",
        0.8,
    ),
    "IT_PPLImage_Omega3Oil_AlgaeSource_Infographic_v1_202608": (
        ["IC_it_broad_all-25-64_advantage-placements"],
        "static",
        0.5,
    ),
    "Test-Hand_IT_PPLImage_Vollagen_VeganCollagenAlternative_HumanContext_V01_202607": (
        ["it_broad_all-25-54_advantage-placements_landing-page-view"],
        "static",
        0.0,
    ),
    "Test-Human_IT_PPLImage_Vollagen_VeganCollagenAlternative_HumanContext_V01_202607": (
        ["it_broad_all-25-54_advantage-placements_landing-page-view"],
        "static",
        0.0,
    ),
    "Test-Product_IT_PPLImage_Vollagen_VeganCollagenAlternative_HumanContext_V01_202607": (
        ["it_broad_all-25-54_advantage-placements_landing-page-view"],
        "static",
        0.0,
    ),
    "IT_Carousel_MultiMagnesioComplexCapsule_CustomerReviews_StaticCards_V01_202607": (
        ["PPL_it_website-visitors_all_advantage-placements_purchase"],
        "carousel",
        7.5,
    ),
    "IT_PPLImage_MultiMagnesioComplexCapsule_GWP_Static_V01_202610": (
        [
            "IC_it_broad_all-25-64_advantage-placements",
            "PPL_it_website-visitors_all_advantage-placements_purchase",
        ],
        "static",
        6.0,
    ),
    "IT_DynamicAd_AllProducts_WelcomeVoucher_PURE5_V01_202608": (
        ["PPL_it_website-visitors_all_advantage-placements_purchase"],
        "dynamic_catalogue",
        4.2,
    ),
    "IT_PPLVideo_FemaleBalance_Routine_Chiara_v1_202608": (
        ["IC_it_broad_all-25-64_advantage-placements"],
        "video",
        0.9,
    ),
    "IT_PPLVideo_Omega3Oil_QuizLampo_8s_V05_202610": (
        ["IC_it_broad_all-25-64_advantage-placements"],
        "video",
        1.1,
    ),
    "IT_PPLImage_BrandRange_VoucherDiscovery_RichCard_v1_202607": (["IT - Open [25-64]"], "static", 0.0),
    "Omega3 vecchia creativita senza convenzione": (["summer-sale_it_mystery_audience"], "static", 1.0),
}


def build_ads(end: dt.date) -> list[dict]:
    rows: list[dict] = []
    aid, aname = AD_ACCOUNT
    for k, (name, (adsets, fmt, roas)) in enumerate(ADS.items()):
        for j, adset in enumerate(adsets):
            campaign, objective, goal, targeting = ADSETS[adset]
            cid = f"{1000 + k * 10 + j}"
            is_video = fmt == "video"
            for d in range(0, 50):
                day = end - dt.timedelta(days=d)
                if rng.random() < 0.35:
                    continue
                spend = round(rng.uniform(3, 60) * (2.5 if "PROSPECTING_VOLUME" in campaign else 1), 2)
                imps = int(spend * rng.uniform(250, 420))
                link = int(imps * rng.uniform(0.004, 0.03))
                plays = int(imps * 0.6) if is_video else 0
                purchases = int(round(spend / 60 * roas * rng.uniform(0.5, 1.5))) if roas else 0
                rows.append(
                    {
                        "date": day.isoformat(),
                        "account_id": aid,
                        "account_name": aname,
                        "campaign_id": f"c{list(ADSETS).index(adset)}",
                        "campaign": campaign,
                        "campaign_objective": objective,
                        "adset_id": f"s{list(ADSETS).index(adset)}",
                        "adset_name": adset,
                        "adsset_optimization_goal": goal,
                        "adset_targeting": targeting,
                        "ad_id": f"a{k}{j}",
                        "ad_name": name,
                        "creative_id": cid,
                        "objective": objective,
                        "thumbnail_url": f"https://example.invalid/thumb/{cid}.jpg",
                        "image_url": None if is_video else f"https://example.invalid/img/{cid}.jpg",
                        "body": f"Primary text for {name.split('_')[2] if '_' in name else name}",
                        "title": f"Headline {k}",
                        "ad_preview_shareable_link": f"https://fb.me/preview{k}{j}",
                        "instagram_permalink_url": f"https://www.instagram.com/p/AD{k}{j}x/"
                        if k % 3
                        else None,
                        "spend": spend,
                        "impressions": imps,
                        "reach": int(imps / rng.uniform(1.3, 3.2)),
                        "frequency": round(rng.uniform(1.3, 3.2), 3),
                        "clicks": int(link * rng.uniform(1.3, 2.0)),
                        "actions_link_click": link,
                        "actions_landing_page_view": int(link * rng.uniform(0.2, 0.7)),
                        "outbound_clicks_outbound_click": int(link * 0.8),
                        "actions_omni_purchase": purchases,
                        "action_values_omni_purchase": round(purchases * rng.uniform(35, 70), 2),
                        "purchase_roas_omni_purchase": None,
                        "video_play_actions_video_view": plays or None,
                        "video_thruplay_watched_actions_video_view": int(plays * 0.18) if plays else None,
                        "video_play_curve_actions_s0": 100.0 if plays else None,
                        "video_play_curve_actions_s3": round(rng.uniform(25, 45), 1) if plays else None,
                        "video_p25_watched_actions_video_view": int(plays * 0.3) if plays else None,
                        "video_avg_time_watched_actions_video_view": round(rng.uniform(2, 6), 1)
                        if plays
                        else None,
                    }
                )
    # a page promotion (kept, tagged boost_page_promo) and an Instagram post boost (dropped: Organic vs Boosted)
    for name, campaign, goal in [
        ("[04/09/2026] Promoting Vegavero Italia", "[04/09/2026] Promoting Vegavero Italia", "PAGE_LIKES"),
        (
            "Instagram post: In una piccola capsula c'è spesso...",
            "Instagram post: In una piccola capsula c'è spesso...",
            "POST_ENGAGEMENT",
        ),
    ]:
        for d in range(5):
            rows.append(
                {
                    "date": (end - dt.timedelta(days=d)).isoformat(),
                    "account_id": aid,
                    "account_name": aname,
                    "campaign_id": "cpromo",
                    "campaign": campaign,
                    "campaign_objective": "OUTCOME_ENGAGEMENT",
                    "adset_id": "spromo",
                    "adset_name": campaign,
                    "adsset_optimization_goal": goal,
                    "adset_targeting": "{}",
                    "ad_id": "apromo",
                    "ad_name": name,
                    "creative_id": "9999",
                    "objective": "OUTCOME_ENGAGEMENT",
                    "thumbnail_url": None,
                    "image_url": None,
                    "body": None,
                    "title": None,
                    "ad_preview_shareable_link": "https://fb.me/promo",
                    "instagram_permalink_url": None,
                    "spend": 27.8,
                    "impressions": 9000,
                    "reach": 6000,
                    "frequency": 1.5,
                    "clicks": 90,
                    "actions_link_click": 60,
                    "actions_landing_page_view": 10,
                    "outbound_clicks_outbound_click": None,
                    "actions_omni_purchase": 0,
                    "action_values_omni_purchase": 0,
                    "purchase_roas_omni_purchase": None,
                    "video_play_actions_video_view": None,
                    "video_thruplay_watched_actions_video_view": None,
                    "video_play_curve_actions_s0": None,
                    "video_play_curve_actions_s3": None,
                    "video_p25_watched_actions_video_view": None,
                    "video_avg_time_watched_actions_video_view": None,
                }
            )
    return rows


def build_klar_marketing(ads: list[dict], out: Path) -> Path:
    """Klar marketing_flex export (date x channel x campaign x content) for ~80 % of the Meta ad-days, plus an
    Email row and one Meta row with an ad name the feed does not know (-> unmatched)."""
    rows: list[dict] = []
    seen: set[tuple] = set()
    for r in ads:
        key = (r["date"], r["campaign"], r["ad_name"])
        if key in seen or r["campaign"].startswith("Instagram post") or r["campaign"].startswith("["):
            continue
        seen.add(key)
        if rng.random() < 0.2:
            continue
        spend = sum(x["spend"] for x in ads if (x["date"], x["campaign"], x["ad_name"]) == key)
        orders = int(round(spend / 45 * rng.uniform(0, 2)))
        rows.append(
            {
                "date": r["date"],
                "channel_name": "Meta Paid",
                "campaign": r["campaign"],
                "content": r["ad_name"],
                "cost": round(spend * rng.uniform(0.97, 1.03), 2),
                "orders": orders,
                "new_customers": int(orders * rng.uniform(0.4, 0.9)),
                "net_revenue": round(orders * rng.uniform(30, 60), 2),
                "gross_revenue": round(orders * rng.uniform(35, 70), 2),
                "roas": None,
            }
        )
    rows.append(
        {
            "date": ads[0]["date"],
            "channel_name": "Email",
            "campaign": "Autumn Deals",
            "content": "n/a",
            "cost": 80.0,
            "orders": 3,
            "new_customers": 1,
            "net_revenue": 90.0,
            "gross_revenue": 100.0,
            "roas": 1.25,
        }
    )
    rows.append(
        {
            "date": ads[0]["date"],
            "channel_name": "Meta Paid",
            "campaign": "AO_IT_SALES_RTG",
            "content": "IT_PPLImage_Unknown_ToTheFeed_Static_V01_202601",
            "cost": 12.0,
            "orders": 1,
            "new_customers": 1,
            "net_revenue": 40.0,
            "gross_revenue": 45.0,
            "roas": 3.75,
        }
    )
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "marketing_flex_2026-10.json", "w", encoding="utf-8") as fh:
        json.dump({"group_by": ["date", "channel_name", "campaign", "content"], "rows": rows}, fh)
    return out


def build(out: Path = OUT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    media, daily, newf, boosted, public, stories = [], [], [], [], [], []
    for aid, name in ACCOUNTS:
        n_posts = 3 if name == "jasnum.italia" else 24
        for i in range(n_posts):
            day = END - dt.timedelta(days=rng.randint(0, 120))
            reach = rng.randint(400, 40000)
            media.append(
                {
                    "date": day.isoformat(),
                    "account_id": aid,
                    "account_name": name,
                    "media_id": f"{aid[-4:]}{i:04d}",
                    "media_type": rng.choice(["CAROUSEL_ALBUM", "REELS", "IMAGE"]),
                    "media_product_type": rng.choice(["FEED", "REELS"]),
                    "media_permalink": f"https://www.instagram.com/p/C{aid[-3:]}{i:03d}x/",
                    "media_caption": f"{name.split('.')[0][:4].upper()}{i:02d} {CAPTIONS[i % len(CAPTIONS)]} lorem ipsum",
                    "media_reach": None if i == 5 else reach,
                    "media_views": int(reach * rng.uniform(1.2, 2.5)),
                    "media_like_count": int(reach * rng.uniform(0.01, 0.05)),
                    "media_comments_count": rng.randint(0, 12),
                    "media_saved": rng.randint(0, 60),
                    "media_shares": rng.randint(0, 30),
                    "media_follows": rng.randint(0, 5),
                    "media_reposts": rng.randint(0, 3),
                    "media_shortcode": f"C{aid[-3:]}{i:03d}x",
                    "media_relationship": "owned",
                    "media_owner_username": name,
                    "media_collaborators": "fit_giulia" if i == 2 else None,
                }
            )
        if name == "vegavero.italia":  # a Collab reel owned by a paid creator, co-authored by the own account
            media.append(
                {
                    "date": (END - dt.timedelta(days=6)).isoformat(),
                    "account_id": aid,
                    "account_name": name,
                    "media_id": f"{aid[-4:]}collab1",
                    "media_type": "VIDEO",
                    "media_product_type": "REELS",
                    "media_permalink": "https://www.instagram.com/reel/COLLAB0001x/",
                    "media_caption": "Collab reel con fit_giulia",
                    "media_reach": None,
                    "media_views": None,
                    "media_like_count": 8272,
                    "media_comments_count": 245,
                    "media_saved": 15338,
                    "media_shares": 1975,
                    "media_follows": None,
                    "media_reposts": None,
                    "media_shortcode": "COLLAB0001x",
                    "media_relationship": "collaborative",
                    "media_owner_username": "fit_giulia",
                    "media_collaborators": None,
                }
            )
        for j in range(4 if name != "jasnum.italia" else 0):  # stories (24 h objects, accumulated daily)
            day = END - dt.timedelta(days=j)
            views = rng.randint(50, 900)
            stories.append(
                {
                    "date": day.isoformat(),
                    "account_id": aid,
                    "account_name": name,
                    "story_id": f"s{aid[-4:]}{j:02d}",
                    "story_timestamp": f"{day.isoformat()}T11:00:00+0000",
                    "story_permalink": f"https://www.instagram.com/stories/{name}/{aid[-4:]}{j:02d}",
                    "story_reach": int(views * 0.85),
                    "story_views": views,
                    "story_replies": rng.randint(0, 3),
                    "story_shares": rng.randint(0, 3),
                    "story_interactions": rng.randint(0, 5),
                    "story_exits": int(views * 0.15),
                    "story_taps_forward": int(views * 0.6),
                    "story_taps_back": rng.randint(0, 5),
                    "story_swipe_forward": rng.randint(0, 20),
                }
            )
        for d in range(130):
            day = END - dt.timedelta(days=d)
            daily.append(
                {
                    "date": day.isoformat(),
                    "account_id": aid,
                    "account_name": name,
                    "reach": None if d == 0 else rng.randint(1000, 40000),
                    "views": None if d == 0 else rng.randint(2000, 90000),
                    "followers_count": rng.randint(800, 35000) if d == 0 else None,
                    "total_interactions": rng.randint(50, 5000),
                    "likes": rng.randint(30, 3000),
                    "comments": rng.randint(0, 100),
                    "saves": rng.randint(10, 2000),
                    "shares": rng.randint(5, 500),
                    "accounts_engaged": rng.randint(40, 3000),
                }
            )
            if d < 30:
                newf.append(
                    {
                        "date": day.isoformat(),
                        "account_id": aid,
                        "account_name": name,
                        "follower_count": rng.randint(0, 120),
                    }
                )
    # boosts: 6 campaigns promoting own posts (caption prefix), 1 permalink match, 1 unmatched
    own = [m for m in media if m["account_name"] != "jasnum.italia"]
    picks = rng.sample(own, 7)
    ad_acc = {
        "vegavero.italia": ("1180996603943052", "Vegavero"),
        "vegavero.de": ("1180996603943052", "Vegavero"),
        "wowtamins.de": ("578368689581825", "wowtamins"),
    }
    for k, m in enumerate(picks):
        acc_id, acc_name = ad_acc[m["account_name"]]
        start = dt.date.fromisoformat(m["date"]) + dt.timedelta(days=1)
        campaign = f"Instagram post: {m['media_caption'][:38]}..."
        for d in range(5):
            day = start + dt.timedelta(days=d)
            if day > END:
                break
            spend = round(rng.uniform(8, 25), 2)
            boosted.append(
                {
                    "date": day.isoformat(),
                    "account_id": acc_id,
                    "account_name": acc_name,
                    "campaign_id": f"c{k}",
                    "campaign": campaign,
                    "adset_name": campaign,
                    "ad_id": f"a{k}",
                    "ad_name": campaign,
                    "objective": "LINK_CLICKS",
                    "instagram_actor_id": None,
                    "effective_instagram_media_id": f"99{k}",
                    "instagram_permalink_url": m["media_permalink"]
                    if k == 0
                    else f"https://www.instagram.com/p/AD{k}copy/",
                    "spend": spend,
                    "reach": int(spend * rng.uniform(80, 200)),
                    "impressions": int(spend * rng.uniform(100, 260)),
                    "clicks": rng.randint(5, 80),
                    "actions_post_engagement": rng.randint(10, 300),
                    "actions_link_click": rng.randint(3, 60),
                    "actions_video_view": None,
                }
            )
    boosted.append(
        {
            "date": (END - dt.timedelta(days=3)).isoformat(),
            "account_id": "1874437769863301",
            "account_name": "Susanna Belli",
            "campaign_id": "cx",
            "campaign": "Instagram post: Something that is not an own post...",
            "adset_name": "x",
            "ad_id": "ax",
            "ad_name": "x",
            "objective": "LINK_CLICKS",
            "instagram_actor_id": None,
            "effective_instagram_media_id": "77",
            "instagram_permalink_url": "https://www.instagram.com/p/NOPE/",
            "spend": 12.5,
            "reach": 900,
            "impressions": 1000,
            "clicks": 10,
            "actions_post_engagement": 20,
            "actions_link_click": 5,
            "actions_video_view": None,
        }
    )
    for handle, fol in [("cucinabotanica", 1480000), ("fit_giulia", 45000), ("vegavero.de", 16000)]:
        for i in range(12):
            day = END - dt.timedelta(days=i * 7)
            public.append(
                {
                    "date": day.isoformat(),
                    "account_id": handle,
                    "account_name": handle,
                    "media_id": f"{handle}{i}",
                    "media_type": "VIDEO",
                    "media_permalink": f"https://www.instagram.com/reel/{handle}{i}/",
                    "media_like_count": int(fol * rng.uniform(0.005, 0.03)),
                    "media_comments_count": rng.randint(0, 300),
                    "profile_followers_count": fol,
                    "profile_media_count": 500,
                }
            )
    ads = build_ads(END)  # after the other pulls so their random sequence stays as before
    build_klar_marketing(ads, out.parent / "klar_marketing")
    for name, rows in [
        ("instagram__media", media),
        ("instagram__daily", daily),
        ("instagram__new_followers", newf),
        ("facebook__boosted", boosted),
        ("instagram_public__media", public),
        ("instagram__stories", stories),
        ("facebook__ads", ads),
    ]:
        with open(out / f"{name}.json", "w", encoding="utf-8") as fh:
            json.dump({"status": "done", "data": rows, "total_rows": len(rows)}, fh)
    return out


if __name__ == "__main__":
    print(build())
