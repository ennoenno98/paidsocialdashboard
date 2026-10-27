"""Klar (getklar.com) influencer_flex ingest.

Status of the HTTP client (2026-10): Klar has a **Public API** (help-center articles "Klar Public API",
"Managing Klar Data API Key Access", "Developer Guide: Connecting to the Klar RESTful API") and a legacy
Attribution/Reporting API at https://api.getklar.com/ (refresh-token -> 5-minute access token, 2 requests
per 30 s, max 31 days per request, deprecated 2026-09-30). The technical endpoint specification was not
reachable from the build environment, so :class:`HttpKlarClient` deliberately refuses to guess:
it raises ``NotImplementedError`` until ``KLAR_INFLUENCER_REPORT_PATH`` (+ optional
``KLAR_REQUEST_STYLE``) are set from the official docs. Everything downstream runs on
:class:`FixtureKlarClient` / cached JSON / a CSV export of the influencer_flex report.

Report vocabulary (verified against the live schema via Klar's MCP server):
dimensions ``influencer_name, campaign_name, platform, type_of_partnership, category, post_type,
posting_date, date, discount_code, utm_*, advertised_sku`` ; metrics ``costs, fixed_costs, var_costs,
orders, net_revenue, gross_revenue, new_customers, roas, gross_roas, cac, cpo, sessions, conversion_rate,
cpm, cost_per_follower, reach_share, reach, followers, ...``.
Note: for this account Klar's ``reach``/``cpm`` are 0 for every partnership -> CPM must come from
manual reach (see src/ingest/instagram.py::influencer_cpm).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Protocol

import httpx
import pandas as pd
from pydantic import ValidationError

from src.models import KlarInfluencerRow

log = logging.getLogger(__name__)

RAW_DIR = Path(os.environ.get("KLAR_RAW_DIR", "data/raw/klar"))
DIMENSIONS = [  # creator master fields (deal type, category) come from Klar, so they are pulled as dimensions
    "influencer_name",
    "platform",
    "type_of_partnership",
    "category",
    "discount_code",
    "posting_date",
    "date",
]
METRICS = [
    "costs",
    "fixed_costs",
    "var_costs",
    "orders",
    "net_revenue",
    "gross_revenue",
    "new_customers",
    "roas",
    "gross_roas",
    "cac",
    "cpo",
    "sessions",
    "conversion_rate",
    "cpm",
    "cost_per_follower",
    "reach_share",
    "reach",
    "followers",
]
NUMERIC = METRICS
MAX_DAYS_PER_REQUEST = 31  # legacy API limit; keep for the new one until documented otherwise
MIN_SECONDS_BETWEEN_REQUESTS = 15.0  # 2 requests / 30 s


class KlarClient(Protocol):
    def fetch(
        self, from_date: dt.date, end_date: dt.date, dimensions: list[str], metrics: list[str]
    ) -> list[dict[str, Any]]:
        """Return raw rows (one dict per group) for the inclusive date range."""


class HttpKlarClient:
    """Klar HTTP client. Auth/endpoint come from env; request shape is a documented TODO."""

    def __init__(
        self,
        api_key: str | None = None,
        shop_id: str | None = None,
        base_url: str | None = None,
        report_path: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("KLAR_API_KEY")
        self.shop_id = shop_id or os.environ.get("KLAR_SHOP_ID")
        self.base_url = (base_url or os.environ.get("KLAR_API_BASE_URL") or "https://api.getklar.com").rstrip(
            "/"
        )
        self.report_path = report_path or os.environ.get("KLAR_INFLUENCER_REPORT_PATH")
        self.request_style = os.environ.get("KLAR_REQUEST_STYLE", "post_json")  # or "get_params"
        self.timeout = timeout
        self._last_call = 0.0
        if not self.api_key or not self.shop_id:
            raise RuntimeError("KLAR_API_KEY and KLAR_SHOP_ID must be set")

    def _build_request(
        self, from_date: dt.date, end_date: dt.date, dimensions: list[str], metrics: list[str]
    ) -> dict[str, Any]:
        # TODO(klar): confirm against https://help.getklar.com/en/articles/16145797-klar-public-api
        #   - exact path of the influencer report, parameter names for dimensions/metrics/date range,
        #   - auth header (API key vs. short-lived access token exchange of the legacy API),
        #   - pagination. Until then this client refuses to run.
        if not self.report_path:
            raise NotImplementedError(
                "Klar influencer report endpoint is not configured. Read the Klar Public API technical docs "
                "(help.getklar.com -> 'Klar Public API') and set KLAR_INFLUENCER_REPORT_PATH "
                "(+ KLAR_API_BASE_URL, KLAR_REQUEST_STYLE=post_json|get_params). "
                "Until then use FixtureKlarClient / CsvExportKlarClient (influencer_flex CSV export)."
            )
        payload = {
            "shop_id": self.shop_id,
            "from_date": from_date.isoformat(),
            "end_date": end_date.isoformat(),
            "dimensions": dimensions,
            "metrics": metrics,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }
        url = f"{self.base_url}/{self.report_path.lstrip('/')}"
        if self.request_style == "get_params":
            params = dict(payload, dimensions=",".join(dimensions), metrics=",".join(metrics))
            return {"method": "GET", "url": url, "params": params, "headers": headers}
        return {"method": "POST", "url": url, "json": payload, "headers": headers}

    @staticmethod
    def _rows(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("rows", "data", "results", "items"):
                if isinstance(data.get(k), list):
                    return data[k]
        raise ValueError(
            f"unexpected Klar response shape: {type(data).__name__} keys={list(data)[:5] if isinstance(data, dict) else ''}"
        )

    def _throttle(self) -> None:
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def fetch(
        self, from_date: dt.date, end_date: dt.date, dimensions: list[str], metrics: list[str]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for a, b in date_chunks(from_date, end_date, MAX_DAYS_PER_REQUEST):
                req = self._build_request(a, b, dimensions, metrics)
                for attempt in range(4):
                    self._throttle()
                    resp = client.request(
                        req["method"],
                        req["url"],
                        params=req.get("params"),
                        json=req.get("json"),
                        headers=req["headers"],
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        time.sleep(2**attempt * 5)
                        continue
                    resp.raise_for_status()
                    rows.extend(self._rows(resp.json()))
                    break
                else:
                    raise RuntimeError(
                        f"Klar request failed after retries: {resp.status_code} {resp.text[:200]}"
                    )
        return rows


class FixtureKlarClient:
    """Reads rows from a JSON fixture / cached raw file and filters by date (``date`` or ``posting_date``)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def fetch(
        self, from_date: dt.date, end_date: dt.date, dimensions: list[str], metrics: list[str]
    ) -> list[dict[str, Any]]:
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
        out = []
        for r in rows:
            d = r.get("date") or r.get("posting_date")
            if d is None or from_date.isoformat() <= str(d)[:10] <= end_date.isoformat():
                out.append(r)
        return out


class CsvExportKlarClient:
    """Reads a CSV export of the influencer_flex report (UI download). Column names must match Klar's."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def fetch(
        self, from_date: dt.date, end_date: dt.date, dimensions: list[str], metrics: list[str]
    ) -> list[dict[str, Any]]:
        df = pd.read_csv(self.path)
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        if "date" in df.columns:
            d = pd.to_datetime(df["date"], errors="coerce").dt.date
            df = df[(d >= from_date) & (d <= end_date)]
        return df.to_dict("records")


def date_chunks(a: dt.date, b: dt.date, max_days: int) -> list[tuple[dt.date, dt.date]]:
    out = []
    cur = a
    while cur <= b:
        end = min(cur + dt.timedelta(days=max_days - 1), b)
        out.append((cur, end))
        cur = end + dt.timedelta(days=1)
    return out


def latest_cache(raw_dir: Path | str = RAW_DIR) -> Path | None:
    files = sorted(Path(raw_dir).glob("*.json"))
    return files[-1] if files else None


def pull_klar(
    client: KlarClient,
    days: int = 400,
    end_date: dt.date | None = None,
    raw_dir: Path | str = RAW_DIR,
    dimensions: list[str] | None = None,
    metrics: list[str] | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Fetch the last ``days`` days (end = yesterday), cache raw JSON to ``raw_dir/YYYY-MM-DD.json``."""
    end = end_date or (dt.date.today() - dt.timedelta(days=1))
    start = end - dt.timedelta(days=days - 1)
    dims = dimensions or DIMENSIONS
    mets = metrics or METRICS
    rows = client.fetch(start, end, dims, mets)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / f"{end.isoformat()}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                "from_date": start.isoformat(),
                "end_date": end.isoformat(),
                "dimensions": dims,
                "metrics": mets,
                "rows": rows,
            },
            fh,
            default=str,
        )
    return klar_frame(rows), out


def klar_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Validate + normalise raw rows into a typed frame."""
    recs: list[dict[str, Any]] = []
    bad = 0
    for r in rows:
        try:
            recs.append(KlarInfluencerRow(**{k: (None if v == "" else v) for k, v in r.items()}).model_dump())
        except ValidationError as e:  # noqa: PERF203
            bad += 1
            log.warning("klar row rejected: %s", e.errors()[0].get("msg"))
    if bad:
        log.warning("klar: %d rows rejected", bad)
    cols = [
        "influencer_name",
        "campaign_name",
        "platform",
        "type_of_partnership",
        "category",
        "post_type",
        "posting_date",
        "date",
        "discount_code",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "advertised_sku",
        *NUMERIC,
    ]
    df = pd.DataFrame.from_records(recs, columns=cols) if recs else pd.DataFrame(columns=cols)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["platform"] = df["platform"].astype("string").str.strip().str.lower()
    df["discount_code"] = df["discount_code"].astype("string").str.strip().str.upper()
    for c in ("posting_date", "date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["date"] = df["date"].fillna(df["posting_date"])  # rows pulled without the order-date dimension
    return df


def creator_summary(
    df: pd.DataFrame, since: dt.date | None = None, until: dt.date | None = None, active_days: int = 180
) -> pd.DataFrame:
    """One row per (influencer_name, platform): costs, orders, revenue, ROAS, CAC, posts, Klar reach/CPM and the
    creator master data Klar carries (deal type, category, codes, followers). ``handle`` = influencer_name
    without '@', lower-cased (Klar names are mostly handles)."""
    cols = [
        "influencer_name",
        "handle",
        "platform",
        "type_of_partnership",
        "category",
        "discount_codes",
        "discount_code",
        "costs",
        "fixed_costs",
        "var_costs",
        "orders",
        "net_revenue",
        "gross_revenue",
        "new_customers",
        "sessions",
        "roas",
        "cac",
        "cpo",
        "n_posting_dates",
        "first_posting_date",
        "last_posting_date",
        "reach_klar",
        "cpm_klar",
        "followers_klar",
        "active_recent",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.copy()
    for c in ("type_of_partnership", "category"):
        if c not in d.columns:
            d[c] = None
    ref = pd.Timestamp(until or dt.date.today())
    if since is not None:
        d = d[d["date"].isna() | (d["date"] >= pd.Timestamp(since))]
    if until is not None:
        d = d[d["date"].isna() | (d["date"] <= ref)]
    d["_recent_cost"] = d["costs"].where(d["date"] >= ref - pd.Timedelta(days=active_days), 0)
    g = d.groupby(["influencer_name", "platform"], dropna=False)
    out = g.agg(
        type_of_partnership=(
            "type_of_partnership",
            lambda s: next((x for x in s if isinstance(x, str) and x), None),
        ),
        category=("category", lambda s: next((x for x in s if isinstance(x, str) and x), None)),
        discount_codes=(
            "discount_code",
            lambda s: "|".join(sorted({str(x) for x in s.dropna() if str(x) and str(x).lower() != "n/a"})),
        ),
        costs=("costs", "sum"),
        fixed_costs=("fixed_costs", "sum"),
        var_costs=("var_costs", "sum"),
        orders=("orders", "sum"),
        net_revenue=("net_revenue", "sum"),
        gross_revenue=("gross_revenue", "sum"),
        new_customers=("new_customers", "sum"),
        sessions=("sessions", "sum"),
        n_posting_dates=("posting_date", "nunique"),
        first_posting_date=("posting_date", "min"),
        last_posting_date=("posting_date", "max"),
        reach_klar=("reach", "sum"),
        followers_klar=("followers", "max"),
        _recent_cost=("_recent_cost", "sum"),
    ).reset_index()
    out["handle"] = out["influencer_name"].astype(str).str.strip().str.lstrip("@").str.lower()
    out["discount_code"] = out["discount_codes"].str.split("|").str[0].replace("", pd.NA)
    out["roas"] = out["net_revenue"] / out["costs"].where(out["costs"] > 0)
    out["cac"] = out["costs"] / out["new_customers"].where(out["new_customers"] > 0)
    out["cpo"] = out["costs"] / out["orders"].where(out["orders"] > 0)
    out["cpm_klar"] = out["costs"] / out["reach_klar"].where(out["reach_klar"] > 0) * 1000
    out["active_recent"] = out["_recent_cost"] > 0
    return out[cols].sort_values("costs", ascending=False).reset_index(drop=True)
