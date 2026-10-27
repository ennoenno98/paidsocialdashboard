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


def build(out: Path = OUT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    media, daily, newf, boosted, public = [], [], [], [], []
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
    for name, rows in [
        ("instagram__media", media),
        ("instagram__daily", daily),
        ("instagram__new_followers", newf),
        ("facebook__boosted", boosted),
        ("instagram_public__media", public),
    ]:
        with open(out / f"{name}.json", "w", encoding="utf-8") as fh:
            json.dump({"status": "done", "data": rows, "total_rows": len(rows)}, fh)
    return out


if __name__ == "__main__":
    print(build())
