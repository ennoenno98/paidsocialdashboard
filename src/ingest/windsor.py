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

from src.secret_env import clean_secret, redact

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
    "media_shortcode",
    "media_relationship",  # owned | collaborative (Instagram Collab where the account is a co-author)
    "media_owner_username",
    "media_collaborators",
]
STORY_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "story_id",
    "story_timestamp",
    "story_permalink",
    "story_reach",
    "story_views",
    "story_replies",
    "story_shares",
    "story_interactions",
    "story_exits",
    "story_taps_forward",
    "story_taps_back",
    "story_swipe_forward",
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
NEW_FOLLOWERS_FIELDS = ["date", "account_id", "account_name", "follower_count", "follows_and_unfollows"]
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
    "instagram_profile_follow",  # accounts that followed the profile as a result of the ad (Ads Manager "Follows")
    "instagram_profile_visits",
]
# Meta ad-level feed for the paid creatives page: ad x day x ad set. Field ids verified with Windsor
# get_fields (facebook connector). Attribution window 7-day click / 1-day view = Ads Manager default.
ADS_FIELDS = [
    "date",
    "account_id",
    "account_name",
    "campaign_id",
    "campaign",
    "campaign_objective",
    "adset_id",
    "adset_name",
    "adsset_optimization_goal",  # sic: Windsor's field id
    "adset_promoted_object",  # JSON with the pixel conversion event (custom_event_type)
    "adset_targeting",
    "ad_id",
    "ad_name",
    "creative_id",
    "objective",
    "thumbnail_url",
    "image_url",
    "body",
    "title",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "actions_link_click",
    "actions_landing_page_view",
    "outbound_clicks_outbound_click",
    "actions_omni_purchase",
    "action_values_omni_purchase",
    "purchase_roas_omni_purchase",
    "video_play_actions_video_view",
    "video_thruplay_watched_actions_video_view",
    "video_play_curve_actions_s0",
    "video_play_curve_actions_s3",
    "video_p25_watched_actions_video_view",
    "video_avg_time_watched_actions_video_view",
]
ADS_NUMERIC = ADS_FIELDS[ADS_FIELDS.index("spend") :]
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

TT_DAILY_FIELDS = [  # tiktok_organic, Account table: one row per account and day
    "date",
    "account_id",
    "username",
    "followers_count",  # net followers gained that day (TikTok: new minus unfollowed)
    "daily_lost_followers",
    "total_followers_count",
    "video_views",
    "unique_video_views",  # daily reached audience
    "likes",
    "comments",
    "shares",
    "profile_views",
    "engaged_audience",
]
TT_VIDEO_FIELDS = [  # tiktok_organic, Video table: one row per video (date = create date)
    "date",
    "account_id",
    "username",
    "video_id",
    "video_create_datetime",
    "video_caption",
    "video_share_url",
    "video_duration",
    "video_views_count",
    "video_reach",
    "video_likes",
    "video_comments",
    "video_shares",
    "video_favorites",
    "video_new_followers",
    "video_full_watched_rate",
    "video_average_time_watched",
]

# pull name -> request spec. follower_count (new followers/day) is limited to 30 days by Meta.
PULLS: dict[str, dict[str, Any]] = {
    "instagram__media": {
        "connector": "instagram",
        "fields": MEDIA_FIELDS,
        "date_preset": "last_400d",
        "options": {"media_relationship": "owned,collaborative"},  # default is owned only
    },
    # Meta exposes a story for 24 h only: pull the last days and accumulate by story_id in the cache.
    "instagram__stories": {
        "connector": "instagram",
        "fields": STORY_FIELDS,
        "date_preset": "last_3dT",
        "accumulate": "story_id",
    },
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
    # TikTok organic (own accounts connected to the tiktok_organic connector)
    "tiktok_organic__daily": {
        "connector": "tiktok_organic",
        "fields": TT_DAILY_FIELDS,
        "date_preset": "last_400d",
    },
    # TikTok serves video rows for the last 60 days only: pull that window and accumulate by video_id in the cache
    "tiktok_organic__videos": {
        "connector": "tiktok_organic",
        "fields": TT_VIDEO_FIELDS,
        "date_preset": "last_60d",
        "accumulate": "video_id",
    },
    # every ad (boosts included; they are split off in ads_frame), 7d click / 1d view like Ads Manager
    "facebook__ads": {
        "connector": "facebook",
        "fields": ADS_FIELDS,
        "date_preset": "last_400d",
        "options": {"attribution_window": "7d_click,1d_view"},
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
        self.api_key = (
            clean_secret("WINDSOR_API_KEY", api_key) if api_key else clean_secret("WINDSOR_API_KEY")
        )
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
            **spec.get("options", {}),
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{BASE_URL}/{spec['connector']}", params=params)
            if r.status_code >= 400:
                # never let the key travel into a log line (the request URL carries it as a query parameter)
                body = redact(r.text[:300], self.api_key).replace("\n", " ")
                raise RuntimeError(f"windsor {spec['connector']} {pull}: HTTP {r.status_code} {body}")
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
        key = PULLS[name].get("accumulate")
        if key:  # keep history: new rows override cached rows with the same key (stories expire after 24 h)
            rows = accumulate_rows(CachedWindsorSource(raw_dir).fetch(name), rows, key)
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


def accumulate_rows(old: list[dict[str, Any]], new: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for r in [*old, *new]:
        k = r.get(key)
        if k in (None, ""):
            continue
        merged[str(k)] = r
    return list(merged.values())


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


MEDIA_EXTRA = [
    "follows",
    "reposts",
    "shortcode",
    "caption_key",
    "source",
    "relationship",
    "owner_username",
    "collaborators",
]


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
            "reposts": np.nan,  # media_reposts is rejected for accounts connected with Instagram Login
            "shortcode": m["media_permalink"].map(shortcode),
            "caption_key": m["media_caption"].map(lambda t: caption_key(t, 60)),
            "source": "windsor",
            "relationship": m["media_relationship"].astype("string").str.lower().fillna("owned"),
            "owner_username": m["media_owner_username"].astype("string").str.lower(),
            "collaborators": m["media_collaborators"],
        }
    )
    return out[IG_POST_COLS + MEDIA_EXTRA]


STORY_COLS = [
    "account",
    "brand",
    "platform",
    "market",
    "story_id",
    "timestamp",
    "date",
    "permalink",
    "reach",
    "views",
    "replies",
    "shares",
    "interactions",
    "exits",
    "taps_forward",
    "taps_back",
    "swipe_forward",
]


def ig_stories_frame(raw: dict[str, pd.DataFrame], ig_map: dict[str, str]) -> pd.DataFrame:
    """Own-account stories (accumulated daily; Meta exposes each story for 24 h only)."""
    s = raw.get("instagram__stories", pd.DataFrame(columns=STORY_FIELDS)).copy()
    s = s[s["story_id"].notna()] if not s.empty else s
    if s.empty:
        return pd.DataFrame(columns=STORY_COLS)
    s["account"] = s["account_id"].astype(str).map(ig_map)
    s = s[s["account"].notna()].reset_index(drop=True)
    s = _num(
        s,
        [
            "story_reach",
            "story_views",
            "story_replies",
            "story_shares",
            "story_interactions",
            "story_exits",
            "story_taps_forward",
            "story_taps_back",
            "story_swipe_forward",
        ],
    )
    ts = pd.to_datetime(s["story_timestamp"], utc=True, errors="coerce")
    out = pd.DataFrame(
        {
            "account": s["account"],
            "story_id": s["story_id"].astype(str),
            "timestamp": ts,
            "date": ts.dt.date.where(ts.notna(), pd.to_datetime(s["date"], errors="coerce").dt.date),
            "permalink": s["story_permalink"],
            "reach": s["story_reach"],
            "views": s["story_views"],
            "replies": s["story_replies"],
            "shares": s["story_shares"],
            "interactions": s["story_interactions"],
            "exits": s["story_exits"],
            "taps_forward": s["story_taps_forward"],
            "taps_back": s["story_taps_back"],
            "swipe_forward": s["story_swipe_forward"],
        }
    )
    out = _split_key(out)
    return (
        out[STORY_COLS]
        .drop_duplicates("story_id")
        .sort_values(["account", "timestamp"])
        .reset_index(drop=True)
    )


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
    "unfollows",
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
        nf["account"] = nf["account_id"].astype(str).map(ig_map).astype("object")
        nf["date"] = pd.to_datetime(nf["date"]).dt.date
        nf = _num(nf, ["follower_count", "follows_and_unfollows"])
        # Meta reports gross new follows (follower_count) and follows + unfollows together; the difference is
        # the unfollows. Both exist for the last 30 days only; a zero row for today is not a measurement.
        nf["unfollows"] = (nf["follows_and_unfollows"] - nf["follower_count"]).clip(lower=0)
        nf.loc[nf["follows_and_unfollows"].isna() | nf["follower_count"].isna(), "unfollows"] = np.nan
        today = dt.date.today()
        nf = nf[nf["date"] < today]
        nf = nf[["account", "date", "follower_count", "unfollows"]].rename(
            columns={"follower_count": "new_followers"}
        )
        d = d.merge(nf, on=["account", "date"], how="left")
    else:
        d["new_followers"], d["unfollows"] = np.nan, np.nan
    d = d.rename(columns={"followers_count": "followers"})
    d = _split_key(d)
    return d[DAILY_COLS].sort_values(["account", "date"]).reset_index(drop=True)


def tt_daily_frame(raw: dict[str, pd.DataFrame], tt_map: dict[str, str]) -> pd.DataFrame:
    """TikTok organic daily account insights in the ``DAILY_COLS`` layout (platform tiktok). reach = daily reached
    audience, views = video views, new_followers = net followers gained (TikTok reports the net figure daily, no
    30-day limit), followers = total followers (0 = not yet delivered -> NaN). saves are not exposed per day."""
    d = raw.get("tiktok_organic__daily", pd.DataFrame()).copy()
    if d.empty or not tt_map:
        return pd.DataFrame(columns=DAILY_COLS)
    d["account"] = d["account_id"].astype(str).map(tt_map)
    d = d[d["account"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = _num(
        d,
        [
            "followers_count",
            "daily_lost_followers",
            "total_followers_count",
            "video_views",
            "unique_video_views",
            "likes",
            "comments",
            "shares",
            "profile_views",
            "engaged_audience",
        ],
    )
    out = pd.DataFrame(
        {
            "account": d["account"],
            "date": d["date"],
            "reach": d["unique_video_views"],
            "views": d["video_views"],
            "likes": d["likes"],
            "comments": d["comments"],
            "saves": np.nan,
            "shares": d["shares"],
            "total_interactions": d[["likes", "comments", "shares"]].sum(axis=1, min_count=1),
            "accounts_engaged": d["engaged_audience"],
            # TikTok reports the net gain and the lost followers: gross new follows = net + lost
            "new_followers": d["followers_count"] + d["daily_lost_followers"].fillna(0),
            "unfollows": d["daily_lost_followers"],
            "followers": d["total_followers_count"].where(d["total_followers_count"] > 0),
        }
    )
    # a day that TikTok has not delivered yet comes back as all zeros: drop it rather than count a zero day
    flows = out[["reach", "views", "likes", "comments", "shares"]]
    out = out[~(flows.fillna(0).eq(0).all(axis=1) & out["new_followers"].fillna(0).eq(0))]
    out = _split_key(out)
    return out[DAILY_COLS].sort_values(["account", "date"]).reset_index(drop=True)


def tt_videos_frame(
    raw: dict[str, pd.DataFrame], tt_map: dict[str, str], fetched_at: dt.datetime | None = None
) -> pd.DataFrame:
    """TikTok videos in the own-post layout (``IG_POST_COLS`` + ``MEDIA_EXTRA``) so they flow through the same
    post metrics; ``saved`` = favourites, ``reach`` = unique viewers (delivered 24-48 h after the views)."""
    from src.ingest.instagram import IG_POST_COLS

    v = raw.get("tiktok_organic__videos", pd.DataFrame()).copy()
    if v.empty or not tt_map:
        return pd.DataFrame(columns=IG_POST_COLS + MEDIA_EXTRA)
    v["account"] = v["account_id"].astype(str).map(tt_map)
    v = v[v["account"].notna()].copy()
    if v.empty:
        return pd.DataFrame(columns=IG_POST_COLS + MEDIA_EXTRA)
    v = _num(
        v,
        [
            "video_views_count",
            "video_reach",
            "video_likes",
            "video_comments",
            "video_shares",
            "video_favorites",
            "video_new_followers",
            "video_duration",
        ],
    )
    ts = pd.to_datetime(v["video_create_datetime"], errors="coerce", utc=True)
    ts = ts.fillna(pd.to_datetime(v["date"], utc=True, errors="coerce"))
    now = fetched_at or dt.datetime.now(dt.UTC)
    out = pd.DataFrame(
        {
            "account": v["account"],
            "ig_user_id": v["account_id"].astype(str),
            "media_id": v["video_id"].astype(str),
            "timestamp": ts,
            "media_type": "VIDEO",
            "media_product_type": "TIKTOK",
            "permalink": v["video_share_url"].astype("string").str.replace(r"\?utm_.*$", "", regex=True),
            "caption": v["video_caption"].astype("string").str.slice(0, 140),
            "like_count": v["video_likes"],
            "comments_count": v["video_comments"],
            "reach": v["video_reach"],
            "saved": v["video_favorites"],
            "shares": v["video_shares"],
            "total_interactions": np.nan,
            "views": v["video_views_count"],
            "fetched_at": now,
            "follows": v["video_new_followers"],
            "reposts": np.nan,
            "shortcode": v["video_id"].astype(str),
            "caption_key": v["video_caption"].map(lambda t: caption_key(t, 60)),
            "source": "windsor",
            "relationship": "owned",
            "owner_username": v["username"].astype("string").str.lower(),
            "collaborators": None,
        }
    )
    return out[IG_POST_COLS + MEDIA_EXTRA].drop_duplicates("media_id").reset_index(drop=True)


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
    "follows",
    "profile_visits",
    "targeting",
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
            "instagram_profile_follow",
            "instagram_profile_visits",
        ],
    )
    b["shortcode"] = b["instagram_permalink_url"].map(shortcode)
    b["date"] = pd.to_datetime(b["date"]).dt.date
    ig_media = media[media["account"].astype(str).str.contains("/instagram/")] if not media.empty else media
    b = match_boosts_to_media(b, ig_media, brand_of_row=b["account_id"].astype(str).map(fb_brand_map))
    b["targeting"] = b["ad_id"].astype(str).map(targeting_countries(raw))
    b["account"] = b["account"].astype(
        "object"
    )  # all-NaN (no own posts cached) must stay mergeable with str keys
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
            "follows": b["instagram_profile_follow"],
            "profile_visits": b["instagram_profile_visits"],
            "targeting": b["targeting"],
        }
    )
    return out[BOOST_COLS].sort_values(["date", "ad_id"]).reset_index(drop=True)


def targeting_countries(raw: dict[str, pd.DataFrame]) -> dict[str, str]:
    """ad_id -> comma-joined country codes of the ad set's geo targeting (from the facebook__ads feed; empty
    when that pull is absent). Used as a cross-check for the post-based market allocation of boosts."""
    ads = raw.get("facebook__ads", pd.DataFrame())
    if ads.empty or "adset_targeting" not in ads.columns:
        return {}

    def _countries(t: object) -> str | None:
        try:
            j = json.loads(t) if isinstance(t, str) else t
            geo = (j or {}).get("geo_locations", {}) or {}
            found = set(geo.get("countries", []) or [])
            for key in ("regions", "cities", "zips"):
                for loc in geo.get(key, []) or []:
                    if isinstance(loc, dict) and loc.get("country"):
                        found.add(str(loc["country"]))
            return ",".join(sorted(found)) or None
        except (TypeError, ValueError, AttributeError):
            return None

    a = ads.dropna(subset=["ad_id"]).drop_duplicates("ad_id")
    return {str(i): c for i, c in zip(a["ad_id"], a["adset_targeting"].map(_countries), strict=True) if c}


def own_followers_now(raw: dict[str, pd.DataFrame], handle_to_account: dict[str, str]) -> pd.DataFrame:
    """Current follower count per own account from the instagram_public profile field (one value per handle, the
    count on the day of the pull). The instagram connector's followers_count arrives for one account only."""
    p = raw.get("instagram_public__media", pd.DataFrame())
    cols = ["account", "date", "followers"]
    if p.empty or not handle_to_account:
        return pd.DataFrame(columns=cols)
    p = p.copy()
    p["handle"] = p["account_name"].astype(str).str.lower().str.lstrip("@")
    p["account"] = p["handle"].map({k.lower(): v for k, v in handle_to_account.items()})
    p = _num(p, ["profile_followers_count"]).dropna(subset=["account", "profile_followers_count"])
    if p.empty:
        return pd.DataFrame(columns=cols)
    out = p.groupby("account", as_index=False)["profile_followers_count"].max()
    out = out.rename(columns={"profile_followers_count": "followers"})
    out["date"] = dt.date.today()
    return out[cols]


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


# --------------------------------------------------------------------------------------
# Meta ads (paid creatives)
# --------------------------------------------------------------------------------------
ADS_COLS = [
    "date",
    "ad_account_id",
    "ad_account_name",
    "brand",
    "campaign_id",
    "campaign",
    "campaign_objective",
    "adset_id",
    "adset_name",
    "optimization_goal",
    "promoted_object",
    "targeting",
    "ad_id",
    "ad_name",
    "creative_id",
    "thumbnail_url",
    "image_url",
    "body",
    "title",
    "ads_manager_url",
    "is_boost",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "link_clicks",
    "lpv",
    "outbound_clicks",
    "purchases",
    "purchase_value",
    "purchase_roas_meta",
    "video_plays",
    "thruplays",
    "play_curve_s0",
    "play_curve_s3",
    "video_p25",
    "video_avg_time",
]


def ads_frame(
    raw: dict[str, pd.DataFrame],
    ad_accounts: dict[str, str] | None = None,
    ads_manager: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Meta ad-level rows (ad x day x ad set) from the ``facebook__ads`` pull, numeric columns coerced.

    ``is_boost`` marks Instagram post boosts (BOOST_CAMPAIGN_RE); they belong to Organic vs Boosted and are
    dropped from the creative asset model. ``ad_accounts`` (config ``creatives.ad_accounts``) limits the
    frame to the configured accounts and sets the brand; empty = keep everything, brand NaN.
    """
    if "facebook__ads" not in raw or raw["facebook__ads"].empty:
        return pd.DataFrame(columns=ADS_COLS)
    a = raw["facebook__ads"].copy()
    a = _num(a, ADS_NUMERIC)
    a["account_id"] = a["account_id"].astype(str)
    if ad_accounts:
        a = a[a["account_id"].isin({str(k) for k in ad_accounts})]
    a["date"] = pd.to_datetime(a["date"], errors="coerce").dt.date
    a = a[a["date"].notna()]
    out = pd.DataFrame(
        {
            "date": a["date"],
            "ad_account_id": a["account_id"],
            "ad_account_name": a["account_name"],
            "brand": a["account_id"].map({str(k): v for k, v in (ad_accounts or {}).items()}),
            "campaign_id": a["campaign_id"].astype("string"),
            "campaign": a["campaign"].astype("string"),
            "campaign_objective": a["campaign_objective"].astype("string"),
            "adset_id": a["adset_id"].astype("string"),
            "adset_name": a["adset_name"].astype("string"),
            "optimization_goal": a["adsset_optimization_goal"].astype("string"),
            "promoted_object": a["adset_promoted_object"].astype("string"),
            "targeting": a["adset_targeting"].astype("string"),
            "ad_id": a["ad_id"].astype("string"),
            "ad_name": a["ad_name"].astype("string"),
            "creative_id": a["creative_id"].astype("string"),
            "thumbnail_url": a["thumbnail_url"].astype("string"),
            "image_url": a["image_url"].astype("string"),
            "body": a["body"].astype("string"),
            "title": a["title"].astype("string"),
            "ads_manager_url": [
                ads_manager_url(acc, ad, ads_manager)
                for acc, ad in zip(a["account_id"], a["ad_id"], strict=True)
            ],
            "is_boost": a["campaign"].map(lambda x: bool(BOOST_CAMPAIGN_RE.match(str(x or "")))),
            "spend": a["spend"],
            "impressions": a["impressions"],
            "reach": a["reach"],
            "frequency": a["frequency"],
            "clicks": a["clicks"],
            "link_clicks": a["actions_link_click"],
            "lpv": a["actions_landing_page_view"],
            "outbound_clicks": a["outbound_clicks_outbound_click"],
            "purchases": a["actions_omni_purchase"],
            "purchase_value": a["action_values_omni_purchase"],
            "purchase_roas_meta": a["purchase_roas_omni_purchase"],
            "video_plays": a["video_play_actions_video_view"],
            "thruplays": a["video_thruplay_watched_actions_video_view"],
            "play_curve_s0": a["video_play_curve_actions_s0"],
            "play_curve_s3": a["video_play_curve_actions_s3"],
            "video_p25": a["video_p25_watched_actions_video_view"],
            "video_avg_time": a["video_avg_time_watched_actions_video_view"],
        }
    )
    for c in ("creative_id", "ad_id", "adset_id", "campaign_id"):
        out[c] = out[c].replace({"": pd.NA, "None": pd.NA, "nan": pd.NA})
    return out[ADS_COLS].sort_values(["date", "ad_id", "adset_id"]).reset_index(drop=True)


CREATIVES_DIR = Path(os.environ.get("CREATIVES_DIR", "data/raw/creatives"))


DEFAULT_ADS_MANAGER_TEMPLATE = (
    "https://adsmanager.facebook.com/adsmanager/manage/ads/edit"
    "?act={account_id}&business_id={business_id}&global_scope_id={business_id}&selected_ad_ids={ad_id}"
    "&nav_entry_point=lep_237"
)


def ads_manager_url(account_id: object, ad_id: object, cfg: dict[str, str] | None = None) -> str | None:
    """Deep link into Ads Manager with the ad selected (needs a Meta login with access to the ad account).
    ``cfg`` = ``creatives.yaml::ads_manager`` (``business_id``, ``url_template``); without a business id the
    ``business_id`` query parameter is dropped."""
    if ad_id is None or (isinstance(ad_id, float) and ad_id != ad_id) or str(ad_id) in ("", "None", "nan"):
        return None
    cfg = cfg or {}
    template = str(cfg.get("url_template") or DEFAULT_ADS_MANAGER_TEMPLATE)
    bid = str(cfg.get("business_id") or "").strip()
    url = template.format(account_id=account_id, ad_id=ad_id, business_id=bid)
    if not bid:  # drop the empty business_id / global_scope_id parameters
        url = re.sub(r"&(?:business_id|global_scope_id)=(?=&|$)", "", url)
        url = re.sub(r"\?(?:business_id|global_scope_id)=&", "?", url)
    return url


THUMB_MAX_PX = 480  # longest side of a cached creative thumbnail
THUMB_MAX_BYTES = 200_000  # a cached file above this is re-encoded (full-size Meta images run to 5-7 MB)


def shrink_image(data: bytes, max_px: int = THUMB_MAX_PX, quality: int = 80) -> bytes:
    """Re-encode image bytes as a JPEG with the longest side <= ``max_px``. Returns the input unchanged when
    Pillow cannot read it (the creatives page then shows whatever Meta delivered)."""
    import io

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((max_px, max_px))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        log.warning("thumbnail re-encode failed: %s", e)
        return data


def cache_thumbnails(
    ads: pd.DataFrame, out_dir: Path | str = CREATIVES_DIR, timeout: float = 20.0, limit: int = 500
) -> dict[str, int]:
    """Download each creative's image once (Meta CDN URLs expire) and store it as a real thumbnail
    (``<out_dir>/<creative_id>.jpg``, longest side ``THUMB_MAX_PX``, ~20-60 KB), so the whole set stays small
    enough to travel with the data repo to the deployed app. Oversized files from earlier runs are re-encoded.

    Returns counts {"cached", "downloaded", "failed", "shrunk"}. Never raises: a failed download is logged and the
    creative keeps its (expiring) URL.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts = {"cached": 0, "downloaded": 0, "failed": 0, "shrunk": 0}
    if ads.empty:
        return counts
    urls = (
        ads.dropna(subset=["creative_id"])
        .assign(url=lambda d: d["image_url"].fillna(d["thumbnail_url"]))
        .dropna(subset=["url"])
        .drop_duplicates("creative_id")
    )
    todo = [(str(c), str(u)) for c, u in zip(urls["creative_id"], urls["url"], strict=True)]
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for cid, url in todo:
            p = out / f"{cid}.jpg"
            if p.exists():
                counts["cached"] += 1
                if p.stat().st_size > THUMB_MAX_BYTES:
                    small = shrink_image(p.read_bytes())
                    if len(small) < p.stat().st_size:
                        p.write_bytes(small)
                        counts["shrunk"] += 1
                continue
            if counts["downloaded"] + counts["failed"] >= limit:
                break
            try:
                r = client.get(url)
                r.raise_for_status()
                p.write_bytes(shrink_image(r.content))
                counts["downloaded"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("thumbnail %s failed: %s", cid, e)
                counts["failed"] += 1
    return counts


def thumbnail_path(creative_id: object, out_dir: Path | str = CREATIVES_DIR) -> Path | None:
    if creative_id is None or (isinstance(creative_id, float) and creative_id != creative_id):
        return None
    p = Path(out_dir) / f"{creative_id}.jpg"
    return p if p.exists() else None
