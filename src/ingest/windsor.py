"""Windsor.ai ingest: Instagram organic (own accounts), Meta boosted posts, creator public metrics.

Connectors used (all already connected in the Windsor account):
* ``instagram``        – Graph-API backed: per-post insights (reach, views, likes, comments, saves, shares,
                         follows) and daily account insights (reach, views, interactions, followers snapshot,
                         new followers for the last 30 days only – Meta limit).
* ``facebook``         – Meta Ads: boosted posts appear as campaigns named ``Instagram post: <caption…>``.
                         A boost promotes an *ad copy* of the post (new media id / shortcode), so the boost is
                         mapped to the own post by caption prefix (permalink match is tried first).
* ``instagram_public`` – public counts for any handle (creators): likes, comments, followers. No reach.

The HTTP client targets Windsor's connector API (``GET https://connectors.windsor.ai/{connector}`` with
``api_key``, ``fields``, ``date_preset``). It could not be exercised live from the build environment
(network policy); the pipeline runs on cached JSON (``data/raw/windsor/<pull>.json``) that was exported
through Windsor's MCP server with the same fields. TODO: confirm parameter names on the first live run.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

RAW_DIR = Path(os.environ.get("WINDSOR_RAW_DIR", "data/raw/windsor"))
BASE_URL = os.environ.get("WINDSOR_API_BASE_URL", "https://connectors.windsor.ai")

MEDIA_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "media_id",
    "media_type",
    "media_product_type",
    "media_permalink",
    "media_caption",
    "media_reach",
    "media_views",
    "media_like_count",
    "media_comments_count",
    "media_saved",
    "media_shares",
    "media_follows",
    "media_reposts",
]
DAILY_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "reach",
    "views",
    "followers_count",
    "total_interactions",
    "likes",
    "comments",
    "saves",
    "shares",
    "accounts_engaged",
]
NEW_FOLLOWERS_FIELDS = ["date", "account_id", "account_name", "follower_count"]
BOOSTED_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "campaign_id",
    "campaign",
    "adset_name",
    "ad_id",
    "ad_name",
    "objective",
    "instagram_actor_id",
    "effective_instagram_media_id",
    "instagram_permalink_url",
    "spend",
    "reach",
    "impressions",
    "clicks",
    "actions_post_engagement",
    "actions_link_click",
    "actions_video_view",
]
PUBLIC_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "media_id",
    "media_type",
    "media_permalink",
    "media_like_count",
    "media_comments_count",
    "profile_followers_count",
    "profile_media_count",
]

# pull name -> request spec. follower_count (new followers/day) is limited to 30 days by Meta.
PULLS: dict[str, dict[str, Any]] = {
    "instagram__media": {"connector": "instagram", "fields": MEDIA_FIELDS, "date_preset": "last_400d"},
    "instagram__daily": {"connector": "instagram", "fields": DAILY_FIELDS, "date_preset": "last_400d"},
    "instagram__new_followers": {
        "connector": "instagram",
        "fields": NEW_FOLLOWERS_FIELDS,
        "date_preset": "last_30d",
    },
    "facebook__boosted": {
        "connector": "facebook",
        "fields": BOOSTED_FIELDS,
        "date_preset": "last_400d",
        "row_filter": "campaign",  # boost campaigns only (BOOST_CAMPAIGN_RE), applied in load_raw to every source
    },
    "instagram_public__media": {
        "connector": "instagram_public",
        "fields": PUBLIC_FIELDS,
        "date_preset": "last_90d",
    },
}
_SHORTCODE = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
# Meta names a boosted post "<Instagram post>: <caption prefix>..." in the ad account's language.
BOOST_CAMPAIGN_RE = re.compile(
    r"^\s*(instagram[ -]?post|instagram[ -]?beitrag|post (?:di|su) instagram|publication instagram)\s*:\s*",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
CAPTION_KEY_LEN = 28  # Meta names a boost "Instagram post: <first ~40 chars of the caption>..."


def shortcode(url: Any) -> str | None:
    m = _SHORTCODE.search(str(url or ""))
    return m.group(1) if m else None


def caption_key(text: Any, n: int = CAPTION_KEY_LEN) -> str | None:
    """Normalised caption prefix used to match a boost campaign name to the promoted post."""
    if text is None or (isinstance(text, float) and text != text):
        return None
    t = _WS.sub(" ", str(text)).strip().lower()
    t = BOOST_CAMPAIGN_RE.sub("", t)
    t = t.rstrip(". …")
    return t[:n] if t else None


class WindsorSource(Protocol):
    def fetch(self, pull: str) -> list[dict[str, Any]]: ...


class HttpWindsorClient:
    """Windsor connector API. Not verified live from the build environment (see module doc)."""

    def __init__(self, api_key: str | None = None, timeout: float = 300.0) -> None:
        self.api_key = api_key or os.environ.get("WINDSOR_API_KEY")
        if not self.api_key:
            raise RuntimeError("WINDSOR_API_KEY not set")
        self.timeout = timeout

    def fetch(self, pull: str) -> list[dict[str, Any]]:
        spec = PULLS[pull]
        params = {
            "api_key": self.api_key,
            "fields": ",".join(spec["fields"]),
            "date_preset": spec["date_preset"],
            "_renderer": "json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{BASE_URL}/{spec['connector']}", params=params)
            r.raise_for_status()
            payload = r.json()
        return payload["data"] if isinstance(payload, dict) else payload


class CachedWindsorSource:
    """Reads ``<raw_dir>/<pull>.json`` (MCP exports or earlier HTTP pulls)."""

    def __init__(self, raw_dir: Path | str = RAW_DIR) -> None:
        self.raw_dir = Path(raw_dir)

    def available(self) -> list[str]:
        return [p for p in PULLS if (self.raw_dir / f"{p}.json").exists()]

    def age_hours(self) -> float | None:
        """Age of the oldest cached pull (None when nothing is cached)."""
        files = [self.raw_dir / f"{p}.json" for p in self.available()]
        if not files:
            return None
        oldest = min(f.stat().st_mtime for f in files)
        return (dt.datetime.now(dt.UTC).timestamp() - oldest) / 3600

    def fetch(self, pull: str) -> list[dict[str, Any]]:
        p = self.raw_dir / f"{pull}.json"
        if not p.exists():
            return []
        with open(p, encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("data", []) if isinstance(payload, dict) else payload


def pull_all(
    source: WindsorSource, raw_dir: Path | str = RAW_DIR, pulls: list[str] | None = None
) -> dict[str, int]:
    """Fetch every pull and cache it as JSON. Returns row counts; failures are recorded as -1 and logged."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in pulls or list(PULLS):
        try:
            rows = source.fetch(name)
        except Exception as e:  # noqa: BLE001
            log.warning("windsor pull %s failed: %s", name, e)
            counts[name] = -1
            continue
        with open(raw_dir / f"{name}.json", "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "status": "done",
                    "data": rows,
                    "total_rows": len(rows),
                    "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                },
                fh,
            )
        counts[name] = len(rows)
    return counts


def apply_row_filter(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep boost campaigns only (``row_filter`` column matches BOOST_CAMPAIGN_RE). Source-independent."""
    col = spec.get("row_filter")
    if not col:
        return rows
    return [x for x in rows if BOOST_CAMPAIGN_RE.match(str(x.get(col) or ""))]


def load_raw(source: WindsorSource | None = None) -> dict[str, pd.DataFrame]:
    src = source or CachedWindsorSource()
    out: dict[str, pd.DataFrame] = {}
    for name, spec in PULLS.items():
        rows = apply_row_filter(src.fetch(name), spec)
        df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=spec["fields"])
        for c in spec["fields"]:
            if c not in df.columns:
                df[c] = None
        out[name] = df
    return out


# --------------------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------------------
def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _split_key(df: pd.DataFrame) -> pd.DataFrame:
    parts = df["account"].astype("string").str.split("/", expand=True)
    if parts.shape[1] == 3:
        df["brand"], df["platform"], df["market"] = parts[0], parts[1], parts[2]
    else:
        df["brand"] = df["platform"] = df["market"] = pd.NA
    return df


MEDIA_EXTRA = ["follows", "reposts", "shortcode", "caption_key", "source"]


def ig_media_frame(
    raw: dict[str, pd.DataFrame], ig_map: dict[str, str], fetched_at: dt.datetime | None = None
) -> pd.DataFrame:
    """Own-account posts in the ``IG_POST_COLS`` layout used by src.ingest.instagram (so ER logic is shared)."""
    from src.ingest.instagram import IG_POST_COLS

    m = raw["instagram__media"].copy()
    if m.empty:
        return pd.DataFrame(columns=IG_POST_COLS + MEDIA_EXTRA)
    m["account"] = m["account_id"].astype(str).map(ig_map)
    unmapped = m["account"].isna()
    if unmapped.any():
        log.warning(
            "windsor instagram: %d media rows for unmapped account ids %s",
            int(unmapped.sum()),
            sorted(m.loc[unmapped, "account_id"].astype(str).unique()),
        )
    m = m[~unmapped].reset_index(drop=True)
    m = _num(
        m,
        [
            "media_reach",
            "media_views",
            "media_like_count",
            "media_comments_count",
            "media_saved",
            "media_shares",
            "media_follows",
            "media_reposts",
        ],
    )
    now = fetched_at or dt.datetime.now(dt.UTC)
    out = pd.DataFrame(
        {
            "account": m["account"],
            "ig_user_id": m["account_id"].astype(str),
            "media_id": m["media_id"].astype(str),
            "timestamp": pd.to_datetime(m["date"], utc=True),
            "media_type": m["media_type"],
            "media_product_type": m["media_product_type"],
            "permalink": m["media_permalink"],
            "caption": m["media_caption"].astype("string").str.slice(0, 140),
            "like_count": m["media_like_count"],
            "comments_count": m["media_comments_count"],
            "reach": m["media_reach"],
            "saved": m["media_saved"],
            "shares": m["media_shares"],
            "total_interactions": np.nan,
            "views": m["media_views"],
            "fetched_at": now,
            "follows": m["media_follows"],
            "reposts": m["media_reposts"],
            "shortcode": m["media_permalink"].map(shortcode),
            "caption_key": m["media_caption"].map(lambda t: caption_key(t, 60)),
            "source": "windsor",
        }
    )
    return out[IG_POST_COLS + MEDIA_EXTRA]


DAILY_COLS = [
    "account",
    "brand",
    "platform",
    "market",
    "date",
    "reach",
    "views",
    "likes",
    "comments",
    "saves",
    "shares",
    "total_interactions",
    "accounts_engaged",
    "new_followers",
    "followers",
]


def ig_daily_frame(raw: dict[str, pd.DataFrame], ig_map: dict[str, str]) -> pd.DataFrame:
    """Daily account insights per own account. ``new_followers`` only for the last 30 days (Meta limit)."""
    d = raw["instagram__daily"].copy()
    if d.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    d["account"] = d["account_id"].astype(str).map(ig_map)
    d = d[d["account"].notna()].copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = _num(
        d,
        [
            "reach",
            "views",
            "likes",
            "comments",
            "saves",
            "shares",
            "total_interactions",
            "accounts_engaged",
            "followers_count",
        ],
    )
    nf = raw["instagram__new_followers"].copy()
    if not nf.empty:
        nf["account"] = nf["account_id"].astype(str).map(ig_map)
        nf["date"] = pd.to_datetime(nf["date"]).dt.date
        nf = _num(nf, ["follower_count"])[["account", "date", "follower_count"]].rename(
            columns={"follower_count": "new_followers"}
        )
        d = d.merge(nf, on=["account", "date"], how="left")
    else:
        d["new_followers"] = np.nan
    d = d.rename(columns={"followers_count": "followers"})
    d = _split_key(d)
    return d[DAILY_COLS].sort_values(["account", "date"]).reset_index(drop=True)


BOOST_COLS = [
    "date",
    "ad_account_id",
    "ad_account_name",
    "campaign",
    "ad_id",
    "objective",
    "permalink",
    "shortcode",
    "media_id",
    "match",
    "account",
    "brand",
    "platform",
    "market",
    "mapped",
    "spend",
    "reach",
    "impressions",
    "clicks",
    "post_engagement",
    "link_clicks",
    "video_views",
]


def match_boosts_to_media(
    boost: pd.DataFrame, media: pd.DataFrame, min_key: int = 8, brand_of_row: pd.Series | None = None
) -> pd.DataFrame:
    """Map each boost campaign to an own post: permalink shortcode first, else the campaign text (a caption
    prefix) must be a prefix of the post caption; among candidates take the latest post published on or before
    the first boost day (+1 day tolerance). Returns boost with media_id / account / match columns filled."""
    boost = boost.copy()
    boost["media_id"], boost["account"], boost["match"] = None, None, None
    if media.empty or boost.empty:
        return boost
    by_code = media.drop_duplicates("shortcode").set_index("shortcode")[["media_id", "account"]]
    hit = boost["shortcode"].map(by_code["media_id"])
    boost.loc[hit.notna(), "media_id"] = hit[hit.notna()]
    boost.loc[hit.notna(), "account"] = boost.loc[hit.notna(), "shortcode"].map(by_code["account"])
    boost.loc[hit.notna(), "match"] = "permalink"
    caps = media[["media_id", "account", "caption_key", "timestamp"]].dropna(subset=["caption_key"]).copy()
    caps["day"] = caps["timestamp"].dt.tz_convert(None).dt.normalize()
    todo = boost[boost["account"].isna()]
    first_day = todo.groupby("campaign")["date"].min()
    for campaign, day0 in first_day.items():
        key = caption_key(campaign, 60)
        if not key or len(key) < min_key:
            continue
        cand = caps[caps["caption_key"].str.startswith(key)]
        if brand_of_row is not None:  # same caption on several brands' accounts: keep the ad account's brand
            brand = brand_of_row[boost["campaign"].eq(campaign)].dropna().head(1)
            if len(brand):
                same = cand[cand["account"].str.startswith(f"{brand.iloc[0]}/")]
                cand = same if not same.empty else cand
        limit = pd.Timestamp(day0) + pd.Timedelta(days=1)
        before = cand[cand["day"] <= limit]
        pick = (
            before.sort_values("day").iloc[-1]
            if not before.empty
            else (cand.sort_values("day").iloc[0] if not cand.empty else None)
        )
        if pick is None:
            continue
        sel = boost["campaign"].eq(campaign) & boost["account"].isna()
        boost.loc[sel, "media_id"] = pick["media_id"]
        boost.loc[sel, "account"] = pick["account"]
        boost.loc[sel, "match"] = "caption"
    return boost


def boosted_frame(
    raw: dict[str, pd.DataFrame], media: pd.DataFrame, fb_brand_map: dict[str, str]
) -> pd.DataFrame:
    """Meta boosted-post rows (ad × day) mapped to the own account via the promoted post (see match_boosts_to_media).

    Unmapped rows keep the brand from the ad account, platform instagram and market NaN (``mapped=False``).
    """
    b = raw["facebook__boosted"].copy()
    if b.empty:
        return pd.DataFrame(columns=BOOST_COLS)
    b = _num(
        b,
        [
            "spend",
            "reach",
            "impressions",
            "clicks",
            "actions_post_engagement",
            "actions_link_click",
            "actions_video_view",
        ],
    )
    b["shortcode"] = b["instagram_permalink_url"].map(shortcode)
    b["date"] = pd.to_datetime(b["date"]).dt.date
    b = match_boosts_to_media(b, media, brand_of_row=b["account_id"].astype(str).map(fb_brand_map))
    b["mapped"] = b["account"].notna()
    b = _split_key(b)
    fallback = b["brand"].isna()
    b.loc[fallback, "brand"] = b.loc[fallback, "account_id"].astype(str).map(fb_brand_map)
    b.loc[fallback, "platform"] = "instagram"
    out = pd.DataFrame(
        {
            "date": b["date"],
            "ad_account_id": b["account_id"].astype(str),
            "ad_account_name": b["account_name"],
            "campaign": b["campaign"],
            "ad_id": b["ad_id"].astype(str),
            "objective": b["objective"],
            "permalink": b["instagram_permalink_url"],
            "shortcode": b["shortcode"],
            "media_id": b["media_id"],
            "match": b["match"],
            "account": b["account"],
            "brand": b["brand"],
            "platform": b["platform"],
            "market": b["market"],
            "mapped": b["mapped"],
            "spend": b["spend"],
            "reach": b["reach"],
            "impressions": b["impressions"],
            "clicks": b["clicks"],
            "post_engagement": b["actions_post_engagement"],
            "link_clicks": b["actions_link_click"],
            "video_views": b["actions_video_view"],
        }
    )
    return out[BOOST_COLS].sort_values(["date", "ad_id"]).reset_index(drop=True)


PUBLIC_COLS = [
    "handle",
    "date",
    "media_id",
    "media_type",
    "permalink",
    "likes",
    "comments",
    "followers",
    "media_count",
]


def creators_public_frame(raw: dict[str, pd.DataFrame], own_handles: list[str]) -> pd.DataFrame:
    """Public per-post counts for creator handles (own accounts excluded). No reach available here."""
    p = raw["instagram_public__media"].copy()
    if p.empty:
        return pd.DataFrame(columns=PUBLIC_COLS)
    p["handle"] = p["account_name"].astype(str).str.lower().str.lstrip("@")
    p = p[~p["handle"].isin({h.lower() for h in own_handles})]
    p = _num(
        p, ["media_like_count", "media_comments_count", "profile_followers_count", "profile_media_count"]
    )
    out = pd.DataFrame(
        {
            "handle": p["handle"],
            "date": pd.to_datetime(p["date"]).dt.date,
            "media_id": p["media_id"].astype(str),
            "media_type": p["media_type"],
            "permalink": p["media_permalink"],
            "likes": p["media_like_count"],
            "comments": p["media_comments_count"],
            "followers": p["profile_followers_count"],
            "media_count": p["profile_media_count"],
        }
    )
    return out[PUBLIC_COLS].sort_values(["handle", "date"]).reset_index(drop=True)


SCAN_COLS = [
    "handle",
    "scannable",
    "followers_count",
    "n_media_fetched",
    "interactions_per_post",
    "likes_per_post",
    "comments_per_post",
    "posts_per_30d",
    "last_post",
    "source",
]


def creators_public_summary(pub: pd.DataFrame, days: int = 90, until: dt.date | None = None) -> pd.DataFrame:
    """Per creator: posts, interactions per post, posting cadence, followers (latest). Mirrors the scan output."""
    if pub.empty:
        return pd.DataFrame(columns=SCAN_COLS)
    ref = until or dt.date.today()
    d = pub[pub["date"] >= ref - dt.timedelta(days=days)]
    g = d.groupby("handle")
    out = g.agg(
        followers_count=("followers", "last"),
        n_media_fetched=("media_id", "nunique"),
        likes_per_post=("likes", "mean"),
        comments_per_post=("comments", "mean"),
        last_post=("date", "max"),
    ).reset_index()
    out["interactions_per_post"] = out["likes_per_post"].fillna(0) + out["comments_per_post"].fillna(0)
    out["posts_per_30d"] = out["n_media_fetched"] / days * 30
    out["scannable"] = True
    out["source"] = "windsor instagram_public"
    return out[SCAN_COLS]
