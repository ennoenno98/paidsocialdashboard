"""Instagram engagement scan: own accounts via the Graph API, creators via Business Discovery.

Sources are swappable (:class:`InstagramSource`): ``GraphApiSource`` (Meta app) and ``FixtureSource`` (JSON).
Windsor (the primary source for own accounts) lives in :mod:`src.ingest.windsor`. Hard rules:

* own-account ER = (likes + comments + saved + shares) / reach, ``er_basis='reach'``; NaN without reach.
* Reach is **not** available for third-party accounts via the Graph API, so influencer CPM uses
  Klar reach -> manual reach CSV -> n/a, always with ``reach_source``. Never followers or likes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")
MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
INSIGHT_METRICS = ["reach", "saved", "shares", "total_interactions", "views"]
DISCOVERY_FIELDS = (
    "followers_count,media_count,media.limit(30){like_count,comments_count,timestamp,media_type}"
)
IG_POSTS_PARQUET = Path("data/processed/ig_posts.parquet")
MANUAL_REACH_CSV = Path("data/manual/influencer_reach.csv")

IG_POST_COLS = [
    "account",
    "ig_user_id",
    "media_id",
    "timestamp",
    "media_type",
    "media_product_type",
    "permalink",
    "caption",
    "like_count",
    "comments_count",
    "reach",
    "saved",
    "shares",
    "total_interactions",
    "views",
    "fetched_at",
]
SCAN_COLS = [
    "handle",
    "scannable",
    "error",
    "followers_count",
    "media_count",
    "n_media_fetched",
    "interactions_per_post",
    "likes_per_post",
    "comments_per_post",
    "posts_per_30d",
    "last_post",
    "fetched_at",
]


class InstagramSource(Protocol):
    def own_media(self, ig_user_id: str, since: dt.datetime) -> list[dict[str, Any]]:
        """Media items (dicts with MEDIA_FIELDS + insight metrics) for an own business account."""

    def business_discovery(self, own_ig_user_id: str, handle: str) -> dict[str, Any]:
        """{'handle', 'scannable', 'error', 'followers_count', 'media_count', 'media': [...]}"""


class GraphApiSource:
    """Instagram Graph API via a Meta app access token."""

    def __init__(
        self, access_token: str | None = None, version: str = GRAPH_VERSION, timeout: float = 30.0
    ) -> None:
        self.token = access_token or os.environ.get("META_ACCESS_TOKEN")
        if not self.token:
            raise RuntimeError("META_ACCESS_TOKEN not set")
        self.base = f"https://graph.facebook.com/{version}"
        self.client = httpx.Client(timeout=timeout)

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        params["access_token"] = self.token
        r = self.client.get(f"{self.base}/{path}", params=params)
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {"message": r.text[:200]}
            raise httpx.HTTPStatusError(
                f"{r.status_code} {err.get('code')} {err.get('message')}", request=r.request, response=r
            )
        return r.json()

    def _insights(self, media_id: str) -> dict[str, float | None]:
        out: dict[str, float | None] = dict.fromkeys(INSIGHT_METRICS)
        try:
            data = self._get(f"{media_id}/insights", metric=",".join(INSIGHT_METRICS))["data"]
        except httpx.HTTPStatusError:
            data = []
            for m in INSIGHT_METRICS:  # some metrics are unsupported per media type -> per-metric fallback
                try:
                    data += self._get(f"{media_id}/insights", metric=m)["data"]
                except httpx.HTTPStatusError as e:
                    log.info("insight %s unavailable for %s: %s", m, media_id, e)
        for d in data:
            vals = d.get("values") or []
            v = vals[0].get("value") if vals else d.get("total_value", {}).get("value")
            out[d["name"]] = float(v) if v is not None else None
        return out

    def own_media(self, ig_user_id: str, since: dt.datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        params: dict[str, Any] = {"fields": MEDIA_FIELDS, "limit": 100}
        path = f"{ig_user_id}/media"
        while True:
            page = self._get(path, **params)
            stop = False
            for m in page.get("data", []):
                ts = dt.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
                if ts < since:
                    stop = True
                    break
                m.update(self._insights(m["id"]))
                items.append(m)
            after = page.get("paging", {}).get("cursors", {}).get("after")
            if stop or not after or not page.get("paging", {}).get("next"):
                break
            params["after"] = after
        return items

    def business_discovery(self, own_ig_user_id: str, handle: str) -> dict[str, Any]:
        try:
            data = self._get(
                own_ig_user_id, fields=f"business_discovery.username({handle}){{{DISCOVERY_FIELDS}}}"
            )
            bd = data["business_discovery"]
            return {
                "handle": handle,
                "scannable": True,
                "error": None,
                "followers_count": bd.get("followers_count"),
                "media_count": bd.get("media_count"),
                "media": bd.get("media", {}).get("data", []),
            }
        except httpx.HTTPStatusError as e:  # 400 for non-business/creator accounts or unknown handles
            return {
                "handle": handle,
                "scannable": False,
                "error": str(e),
                "followers_count": None,
                "media_count": None,
                "media": [],
            }


class FixtureSource:
    """JSON fixtures: ``ig_media.json`` {ig_user_id: [media...]}, ``ig_business_discovery.json`` {handle: {...}}."""

    def __init__(self, media_path: Path | str, discovery_path: Path | str | None = None) -> None:
        with open(media_path, encoding="utf-8") as fh:
            self.media: dict[str, list[dict[str, Any]]] = json.load(fh)
        self.discovery: dict[str, dict[str, Any]] = {}
        if discovery_path and Path(discovery_path).exists():
            with open(discovery_path, encoding="utf-8") as fh:
                self.discovery = json.load(fh)

    def own_media(self, ig_user_id: str, since: dt.datetime) -> list[dict[str, Any]]:
        return [m for m in self.media.get(ig_user_id, []) if pd.Timestamp(m["timestamp"]) >= since]

    def business_discovery(self, own_ig_user_id: str, handle: str) -> dict[str, Any]:
        d = self.discovery.get(handle)
        if d is None:
            return {
                "handle": handle,
                "scannable": False,
                "error": "400 (#100) not a business/creator account",
                "followers_count": None,
                "media_count": None,
                "media": [],
            }
        return {"handle": handle, "scannable": True, "error": None, **d}


# --------------------------------------------------------------------------------------
# own accounts
# --------------------------------------------------------------------------------------
def account_ids_from_env() -> dict[str, str]:
    raw = os.environ.get("IG_BUSINESS_ACCOUNT_IDS", "").strip()
    if not raw:
        return {}
    return {str(k): str(v) for k, v in json.loads(raw).items()}


def pull_own_accounts(
    source: InstagramSource,
    account_ids: dict[str, str],
    parquet: Path | str = IG_POSTS_PARQUET,
    since_days: int = 400,
    now: dt.datetime | None = None,
) -> pd.DataFrame:
    """Daily, idempotent pull: upsert on media_id (latest fetched_at wins), append to parquet."""
    now = now or dt.datetime.now(dt.UTC)
    since = now - dt.timedelta(days=since_days)
    recs: list[dict[str, Any]] = []
    for account, ig_id in account_ids.items():
        for m in source.own_media(ig_id, since):
            recs.append(
                {
                    "account": account,
                    "ig_user_id": ig_id,
                    "media_id": str(m.get("id")),
                    "timestamp": m.get("timestamp"),
                    "media_type": m.get("media_type"),
                    "media_product_type": m.get("media_product_type"),
                    "permalink": m.get("permalink"),
                    "caption": (m.get("caption") or "")[:140] or None,
                    "like_count": m.get("like_count"),
                    "comments_count": m.get("comments_count"),
                    "reach": m.get("reach"),
                    "saved": m.get("saved"),
                    "shares": m.get("shares"),
                    "total_interactions": m.get("total_interactions"),
                    "views": m.get("views"),
                    "fetched_at": now,
                }
            )
    new = pd.DataFrame.from_records(recs, columns=IG_POST_COLS)
    parquet = Path(parquet)
    old = pd.read_parquet(parquet) if parquet.exists() else pd.DataFrame(columns=IG_POST_COLS)
    df = pd.concat([old, new], ignore_index=True)
    df = _typed_ig_posts(df)
    df = (
        df.sort_values("fetched_at")
        .drop_duplicates(["account", "media_id"], keep="last")
        .reset_index(drop=True)
    )
    parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet, index=False)
    return df


def _typed_ig_posts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("like_count", "comments_count", "reach", "saved", "shares", "total_interactions", "views"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True, errors="coerce")
    return df


def ig_post_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Per-post ER by reach for own accounts (+ brand/platform/market from the account key)."""
    d = _typed_ig_posts(df) if not df.empty else df.copy()
    if d.empty:
        return d.assign(
            engagements=pd.Series(dtype=float), er=pd.Series(dtype=float), er_basis=pd.Series(dtype=str)
        )
    d["engagements"] = d[["like_count", "comments_count", "saved", "shares"]].sum(axis=1, min_count=1)
    d["er_denominator"] = d["reach"]
    d["er"] = d["engagements"] / d["reach"].where(d["reach"] > 0)
    d["er_basis"] = "reach"
    parts = d["account"].str.split("/", expand=True)
    d["brand"], d["platform"], d["market"] = parts[0], parts[1], parts[2]
    iso = d["timestamp"].dt.isocalendar()
    d["year"], d["cw"] = iso["year"].astype("Int64"), iso["week"].astype("Int64")
    d["month"] = d["timestamp"].dt.month.astype("Int64")
    return d


# --------------------------------------------------------------------------------------
# creators: business discovery (no reach) + CPM from Klar/manual reach
# --------------------------------------------------------------------------------------
def scan_creators(
    source: InstagramSource, own_ig_user_id: str, handles: list[str], now: dt.datetime | None = None
) -> pd.DataFrame:
    now = now or dt.datetime.now(dt.UTC)
    recs = []
    for h in sorted({h.strip().lower().lstrip("@") for h in handles if isinstance(h, str) and h.strip()}):
        d = source.business_discovery(own_ig_user_id, h)
        media = pd.DataFrame(d.get("media") or [])
        rec: dict[str, Any] = {
            "handle": h,
            "scannable": bool(d.get("scannable")),
            "error": d.get("error"),
            "followers_count": d.get("followers_count"),
            "media_count": d.get("media_count"),
            "n_media_fetched": len(media),
            "interactions_per_post": None,
            "likes_per_post": None,
            "comments_per_post": None,
            "posts_per_30d": None,
            "last_post": None,
            "fetched_at": now,
        }
        if not media.empty:
            likes = pd.to_numeric(media.get("like_count"), errors="coerce")
            comments = pd.to_numeric(media.get("comments_count"), errors="coerce")
            rec["likes_per_post"] = float(likes.mean()) if likes.notna().any() else None
            rec["comments_per_post"] = float(comments.mean()) if comments.notna().any() else None
            rec["interactions_per_post"] = float((likes.fillna(0) + comments.fillna(0)).mean())
            ts = pd.to_datetime(media.get("timestamp"), utc=True, errors="coerce").dropna()
            if len(ts):
                span_days = max((ts.max() - ts.min()).days, 1)
                rec["posts_per_30d"] = float(len(ts) / span_days * 30) if len(ts) > 1 else None
                rec["last_post"] = ts.max()
        recs.append(rec)
    return pd.DataFrame.from_records(recs, columns=SCAN_COLS)


def load_manual_reach(path: Path | str = MANUAL_REACH_CSV) -> pd.DataFrame:
    cols = ["handle", "post_url", "date", "reach", "source"]
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df["handle"] = df["handle"].astype(str).str.strip().str.lower().str.lstrip("@")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["reach"] = pd.to_numeric(df["reach"], errors="coerce")
    df["source"] = df["source"].fillna("manual")
    return df[cols]


def influencer_cpm(creators_klar: pd.DataFrame, manual_reach: pd.DataFrame) -> pd.DataFrame:
    """Per creator: CPM = costs / reach * 1000 with reach priority Klar -> manual CSV -> n/a.

    ``creators_klar`` is the joined creator table (needs costs, reach_klar, creator_handle).
    """
    df = creators_klar.copy()
    if df.empty:
        return df.assign(
            reach=pd.Series(dtype=float),
            reach_source=pd.Series(dtype=str),
            cpm=pd.Series(dtype=float),
            avg_reach_per_post=pd.Series(dtype=float),
            n_posts_with_reach=pd.Series(dtype=float),
        )
    man = (
        manual_reach.groupby("handle", as_index=False).agg(
            reach_manual=("reach", "sum"),
            n_manual=("reach", "count"),
            manual_source=(
                "source",
                lambda x: (
                    "klar_sheet"
                    if "klar_sheet" in set(x)
                    else ("worksheet" if "worksheet" in set(x) else "manual")
                ),
            ),
        )
        if not manual_reach.empty
        else pd.DataFrame(columns=["handle", "reach_manual", "n_manual", "manual_source"])
    )
    df["_h"] = df.get("creator_handle", pd.Series(index=df.index, dtype=object)).astype("string").str.lower()
    df = df.merge(man.rename(columns={"handle": "_h"}), on="_h", how="left").drop(columns="_h")
    reach_klar = pd.to_numeric(df.get("reach_klar"), errors="coerce")
    reach_manual = pd.to_numeric(df["reach_manual"], errors="coerce")
    klar_ok = reach_klar.fillna(0) > 0
    man_ok = reach_manual.fillna(0) > 0
    df["reach"] = np.where(klar_ok, reach_klar, np.where(man_ok, reach_manual, np.nan))
    df["reach_source"] = np.where(
        klar_ok, "klar", np.where(man_ok, df["manual_source"].fillna("manual"), "n/a")
    )
    n_dates = pd.to_numeric(df.get("n_posting_dates"), errors="coerce").fillna(0)
    df["n_posts_with_reach"] = np.where(klar_ok, n_dates, df["n_manual"].fillna(0)).astype(int)
    df["avg_reach_per_post"] = df["reach"] / df["n_posts_with_reach"].where(df["n_posts_with_reach"] > 0)
    df["cpm"] = df["costs"] / df["reach"].where(df["reach"] > 0) * 1000
    return df.drop(columns=["reach_manual", "n_manual", "manual_source"])


def influencer_post_cpm(
    klar: pd.DataFrame, matched: pd.DataFrame, manual_reach: pd.DataFrame
) -> pd.DataFrame:
    """Per post: Klar costs by (influencer, posting_date) joined to manual reach on (handle, date)."""
    cols = [
        "influencer_name",
        "creator_handle",
        "posting_date",
        "post_url",
        "costs",
        "reach",
        "reach_source",
        "cpm",
        "er_by_reach",
    ]
    if klar.empty or manual_reach.empty or matched.empty:
        return pd.DataFrame(columns=cols)
    per_post = (
        klar.dropna(subset=["posting_date"])
        .groupby(["influencer_name", "posting_date"], as_index=False)["costs"]
        .sum()
    )
    handles = matched.dropna(subset=["creator_handle"]).drop_duplicates("influencer_name")[
        ["influencer_name", "creator_handle"]
    ]
    per_post = per_post.merge(handles, on="influencer_name", how="inner")
    mr = manual_reach.rename(columns={"handle": "creator_handle", "date": "posting_date"})
    m = per_post.merge(mr, on=["creator_handle", "posting_date"], how="inner")
    m["reach_source"] = (
        m["source"].eq("klar_sheet").map({True: "klar_sheet", False: "manual"})
        if "source" in m.columns
        else "manual"
    )
    m["cpm"] = m["costs"] / m["reach"].where(m["reach"] > 0) * 1000
    m["er_by_reach"] = float("nan")  # needs per-post interactions from creator insights; optional
    return m[cols]
