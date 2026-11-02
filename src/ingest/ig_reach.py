"""Instagram period reach (unique accounts) from the Graph API.

Windsor delivers Meta's account insights per day only, so the dashboard's period reach was the sum of daily
unique reach, which counts an account once per day it was reached and therefore overstates the number the
Instagram app shows for a week or a month. Meta exposes the deduplicated figure only through
``GET /{ig-user-id}/insights?metric=reach&period=day&metric_type=total_value&since=&until=`` for a window of
at most 30 days. This module pulls that number once per ISO week and calendar month per own account (a 31-day
month is covered 1st–30th and flagged), caches it in ``data/raw/meta/ig_period_reach.json`` and re-fetches
only periods that were still running at the previous pull.

Needs ``META_ACCESS_TOKEN`` (a user or system-user token with ``instagram_manage_insights`` on the connected
pages); the account ids come from ``config/accounts.yaml::windsor.instagram``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

log = logging.getLogger(__name__)

RAW_DIR = Path(os.environ.get("IG_REACH_RAW_DIR", "data/raw/meta"))
CACHE_NAME = "ig_period_reach.json"
MAX_DAYS = 30  # Meta: since/until window of a total_value insight
SETTLE_DAYS = 2  # a period whose last day is younger than this is pulled again next time
PERIOD_REACH_COLS = [
    "account",
    "period_type",
    "year",
    "period",
    "since",
    "until",
    "days_covered",
    "days_in_period",
    "reach_unique",
    "fetched_at",
]


class ReachSource(Protocol):
    def period_reach(self, ig_user_id: str, since: dt.date, until: dt.date) -> float | None:
        """Unique accounts reached between ``since`` and ``until`` (inclusive), or None when Meta has nothing."""


class GraphReachSource:
    """Graph API ``reach`` with ``metric_type=total_value`` (deduplicated over the window)."""

    def __init__(self, access_token: str | None = None, version: str | None = None, timeout: float = 30.0):
        from src.ingest.instagram import GRAPH_VERSION, GraphApiSource

        self.api = GraphApiSource(access_token, version or GRAPH_VERSION, timeout)

    def period_reach(self, ig_user_id: str, since: dt.date, until: dt.date) -> float | None:
        since_ts = int(dt.datetime.combine(since, dt.time.min, tzinfo=dt.UTC).timestamp())
        until_ts = int(dt.datetime.combine(until, dt.time.max, tzinfo=dt.UTC).timestamp())
        data = self.api._get(  # noqa: SLF001 (same package; shared token / error handling)
            f"{ig_user_id}/insights",
            metric="reach",
            period="day",
            metric_type="total_value",
            since=since_ts,
            until=until_ts,
        )
        for row in data.get("data", []):
            if row.get("name") == "reach":
                v = (row.get("total_value") or {}).get("value")
                return float(v) if v is not None else None
        return None


class FixtureReachSource:
    """Deterministic stand-in: a share of the daily-sum reach of the given daily frame (tests, empty deploy)."""

    def __init__(self, daily: pd.DataFrame, id_to_account: dict[str, str], share: float = 0.55) -> None:
        d = daily.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.date
        self.daily = d
        self.id_to_account = id_to_account
        self.share = share

    def period_reach(self, ig_user_id: str, since: dt.date, until: dt.date) -> float | None:
        acc = self.id_to_account.get(ig_user_id)
        d = self.daily[
            self.daily["account"].eq(acc) & (self.daily["date"] >= since) & (self.daily["date"] <= until)
        ]
        if d.empty or d["reach"].isna().all():
            return None
        return float(round(d["reach"].fillna(0).sum() * self.share))


def periods_between(start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """ISO weeks and calendar months that ended inside [start, end] (``until <= end``), with the ≤30-day window
    Meta accepts: a 31-day month is covered from the 1st to the 30th (``days_covered`` 30 of 31)."""
    out: list[dict[str, Any]] = []
    # weeks
    monday = start - dt.timedelta(days=start.weekday())
    while monday + dt.timedelta(days=6) <= end:
        sunday = monday + dt.timedelta(days=6)
        if sunday >= start:
            iso = monday.isocalendar()
            out.append(
                {
                    "period_type": "cw",
                    "year": int(iso[0]),
                    "period": int(iso[1]),
                    "since": monday,
                    "until": sunday,
                    "days_covered": 7,
                    "days_in_period": 7,
                }
            )
        monday += dt.timedelta(days=7)
    # months
    first = start.replace(day=1)
    while True:
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        last = nxt - dt.timedelta(days=1)
        if last > end:
            break
        if last >= start:
            n = (last - first).days + 1
            until = min(last, first + dt.timedelta(days=MAX_DAYS - 1))
            out.append(
                {
                    "period_type": "month",
                    "year": first.year,
                    "period": first.month,
                    "since": first,
                    "until": until,
                    "days_covered": (until - first).days + 1,
                    "days_in_period": n,
                }
            )
        first = nxt
    return out


def _cache_path(raw_dir: Path | str | None) -> Path:
    return Path(raw_dir or RAW_DIR) / CACHE_NAME


def load_period_reach(raw_dir: Path | str | None = None) -> pd.DataFrame:
    """Cached rows -> frame (empty with the right columns when there is no cache yet)."""
    p = _cache_path(raw_dir)
    if not p.exists():
        return pd.DataFrame(columns=PERIOD_REACH_COLS)
    with open(p, encoding="utf-8") as fh:
        rows = json.load(fh).get("data", [])
    df = pd.DataFrame(rows, columns=PERIOD_REACH_COLS) if rows else pd.DataFrame(columns=PERIOD_REACH_COLS)
    for c in ("since", "until"):
        df[c] = pd.to_datetime(df[c]).dt.date
    for c in ("year", "period", "days_covered", "days_in_period"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df["reach_unique"] = pd.to_numeric(df["reach_unique"], errors="coerce").astype("float64")
    return df[PERIOD_REACH_COLS]


def pull_period_reach(
    source: ReachSource,
    id_to_account: dict[str, str],
    raw_dir: Path | str | None = None,
    today: dt.date | None = None,
    lookback_days: int = 400,
) -> pd.DataFrame:
    """Fetch unique reach for every week / month of the last ``lookback_days`` per account, reusing cached rows
    whose period had settled (``until`` older than SETTLE_DAYS at fetch time). One failed request skips that
    period only. Returns the merged frame and rewrites the cache."""
    today = today or dt.date.today()
    cached = load_period_reach(raw_dir)
    keep: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for r in cached.to_dict("records"):
        fetched = pd.to_datetime(r["fetched_at"]).date() if r.get("fetched_at") else None
        settled = fetched is not None and (fetched - r["until"]).days >= SETTLE_DAYS
        if settled and pd.notna(r["reach_unique"]):
            keep[(r["account"], r["period_type"], int(r["year"]), int(r["period"]))] = r
    end = today - dt.timedelta(days=1)  # Meta has no complete figure for today
    fetched_at = dt.datetime.now(dt.UTC).isoformat()
    n_new = n_fail = 0
    for ig_id, account in id_to_account.items():
        for per in periods_between(end - dt.timedelta(days=lookback_days), end):
            key = (account, per["period_type"], per["year"], per["period"])
            if key in keep:
                continue
            try:
                value = source.period_reach(ig_id, per["since"], per["until"])
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                log.warning("ig period reach %s %s failed: %s", account, key[1:], e)
                continue
            n_new += 1
            keep[key] = {"account": account, **per, "reach_unique": value, "fetched_at": fetched_at}
    rows = sorted(keep.values(), key=lambda r: (r["account"], r["period_type"], r["year"], r["period"]))
    p = _cache_path(raw_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "status": "done",
                "data": [{**r, "since": str(r["since"]), "until": str(r["until"])} for r in rows],
                "total_rows": len(rows),
                "fetched_at": fetched_at,
                "new": n_new,
                "failed": n_fail,
            },
            fh,
        )
    log.info("ig period reach: %d rows (%d new, %d failed)", len(rows), n_new, n_fail)
    out = load_period_reach(raw_dir)
    out.attrs["new"], out.attrs["failed"] = n_new, n_fail
    return out
