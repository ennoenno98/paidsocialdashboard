"""Klar influencer Google Sheets ("Influencer <Brand>") as the creator / campaign master.

Klar reads its influencer_flex costs from these sheets (one row per campaign). ``Influencer/Affiliate Name`` is
the handle and the join key to Klar's ``influencer_name``; ``Reach`` and ``Link to Post`` are the columns to fill
per campaign, so reach entered there feeds both Klar's own CPM and this dashboard (``reach_source='klar_sheet'``).

Sheet layout (CSV export): a technical-id row (``campaign_name, influencer_name, …``), a description row and the
label row (``Campaign Name, Influencer/Affiliate Name, …``) precede the data. The parser locates the label row.
Fetching: ``make refresh`` downloads ``KLAR_SHEET_CSV_URLS`` (JSON ``{"vegavero": "<published csv url>", …}``)
into ``KLAR_SHEETS_DIR`` (default ``data/raw/klar_sheets``); otherwise the cached CSVs are read.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

SHEETS_DIR = Path(os.environ.get("KLAR_SHEETS_DIR", "data/raw/klar_sheets"))
LABELS = {
    "Campaign Name": "campaign_name",
    "Influencer/Affiliate Name": "influencer_name",
    "Handle": "handle_sheet",
    "Platform": "platform",
    "Link to Profile": "link_to_profile",
    "Followers": "followers",
    "Reach": "reach",
    "Expected Reach": "expected_reach",
    "Expected Sessions": "expected_sessions",
    "Type of Partnership": "type_of_partnership",
    "Category": "category",
    "Post Type": "post_type",
    "# of Integrations": "n_integrations",
    "Link to Post": "link_to_post",
    "Posting Date": "posting_date",
    "End Date": "end_date",
    "Fixed Costs": "fixed_costs",
    "Fixed Costs Distribution": "fixed_costs_distribution",
    "Variable Cost - Percentage": "variable_cost_pct",
    "Variable Costs - Fee": "variable_cost_fee",
    "Discount Codes (Comma Separated)": "discount_codes",
    "Discount Code Type": "discount_code_type",
    "utm_source": "utm_source",
    "utm_medium": "utm_medium",
    "utm_campaign": "utm_campaign",
    "Featured SKU": "featured_sku",
    "Custom Dimension 1": "market",
    "Custom Dimension 2": "custom_dimension_2",
    "Custom Dimension 3": "custom_dimension_3",
    "Status": "status",
}
COLS = [
    "brand",
    "campaign_name",
    "influencer_name",
    "handle",
    "platform",
    "link_to_profile",
    "followers",
    "reach",
    "expected_reach",
    "expected_sessions",
    "type_of_partnership",
    "category",
    "post_type",
    "n_integrations",
    "link_to_post",
    "posting_date",
    "end_date",
    "fixed_costs",
    "fixed_costs_distribution",
    "variable_cost_pct",
    "variable_cost_fee",
    "discount_codes",
    "discount_code_type",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "featured_sku",
    "market",
    "custom_dimension_2",
    "custom_dimension_3",
    "status",
    "status_ok",
    "row",
]
NUMERIC = [
    "followers",
    "reach",
    "expected_reach",
    "expected_sessions",
    "n_integrations",
    "fixed_costs",
    "variable_cost_pct",
    "variable_cost_fee",
]


def normalise_handle(v: object) -> str | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v).strip().lstrip("@").strip().lower()
    return s or None


_PROFILE_RE = re.compile(r"(?:instagram\.com|tiktok\.com|youtube\.com)/@?([A-Za-z0-9._-]+)", re.IGNORECASE)


def handle_from_url(url: object) -> str | None:
    m = _PROFILE_RE.search(str(url or ""))
    return normalise_handle(m.group(1)) if m else None


def alias_map(sheet: pd.DataFrame) -> dict[str, str]:
    """normalised Influencer/Affiliate Name -> handle (Klar's influencer_name can be a display name)."""
    if sheet.empty:
        return {}
    out: dict[str, str] = {}
    for name, handle in zip(sheet["influencer_name"], sheet["handle"], strict=True):
        if isinstance(handle, str) and handle:
            out[handle] = handle
            n = normalise_handle(name)
            if n:
                out.setdefault(n, handle)
    return out


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")


def parse_klar_sheet(text: str, brand: str) -> pd.DataFrame:
    """CSV export text of one 'Influencer <Brand>' sheet -> one row per campaign (``COLS``)."""
    rows = list(csv.reader(io.StringIO(text)))
    hdr_idx = next((i for i, r in enumerate(rows) if "Influencer/Affiliate Name" in r), None)
    if hdr_idx is None:
        log.warning("klar sheet %s: label row not found", brand)
        return pd.DataFrame(columns=COLS)
    labels = [c.strip() for c in rows[hdr_idx]]
    recs = []
    for n, r in enumerate(rows[hdr_idx + 1 :], start=hdr_idx + 2):
        if not any(c.strip() for c in r):
            continue
        rec = {
            LABELS[lab]: r[i].strip() if i < len(r) else "" for i, lab in enumerate(labels) if lab in LABELS
        }
        rec["row"] = n
        recs.append(rec)
    df = pd.DataFrame.from_records(recs)
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df["brand"] = brand
    df["influencer_name"] = df["influencer_name"].astype("string").str.strip()
    # handle: Handle column -> profile link -> Influencer/Affiliate Name (which is usually the handle already)
    df["handle"] = [
        normalise_handle(h) or handle_from_url(u) or normalise_handle(n)
        for h, u, n in zip(
            df["handle_sheet"].fillna(""),
            df["link_to_profile"].fillna(""),
            df["influencer_name"],
            strict=True,
        )
    ]
    df["platform"] = df["platform"].astype("string").str.strip().str.lower().replace("", pd.NA)
    for c in NUMERIC:
        df[c] = _num(df[c])
    for c in ("posting_date", "end_date"):
        df[c] = pd.to_datetime(df[c].replace("", pd.NA), format="%d/%m/%Y", errors="coerce")
    df["discount_codes"] = df["discount_codes"].astype("string").str.upper().str.replace(" ", "", regex=False)
    # market (IT/DE/…) lives in a custom dimension: the sheets use Custom Dimension 2, some rows 1 or 3
    cands = [
        df[c].astype("string").str.strip().str.upper()
        for c in ("market", "custom_dimension_2", "custom_dimension_3")
    ]
    df["market"] = pd.Series(pd.NA, index=df.index, dtype="string")
    for col in cands:
        ok = col.str.fullmatch(r"[A-Z]{2}").fillna(False)
        df["market"] = df["market"].where(df["market"].notna(), col.where(ok))
    df["status_ok"] = df["status"].astype("string").str.startswith("✅").fillna(False)
    for c in (
        "campaign_name",
        "category",
        "type_of_partnership",
        "post_type",
        "link_to_post",
        "link_to_profile",
    ):
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    return df[COLS].sort_values(["brand", "posting_date", "row"]).reset_index(drop=True)


def brand_from_name(name: str) -> str:
    m = re.search(r"influencer[ _-]*(\w+)", name, re.IGNORECASE)
    return (m.group(1) if m else Path(name).stem).lower()


def load_klar_sheets(sheets_dir: Path | str = SHEETS_DIR) -> pd.DataFrame:
    d = Path(sheets_dir)
    frames = [
        parse_klar_sheet(p.read_text(encoding="utf-8"), brand_from_name(p.stem))
        for p in sorted(d.glob("*.csv"))
    ]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)


def pull_klar_sheets(
    urls_json: str | None = None, sheets_dir: Path | str = SHEETS_DIR, timeout: float = 60.0
) -> dict[str, int]:
    """Download published-CSV exports listed in ``KLAR_SHEET_CSV_URLS`` (JSON brand -> url) into ``sheets_dir``."""
    raw = urls_json or os.environ.get("KLAR_SHEET_CSV_URLS", "")
    if not raw:
        return {}
    urls: dict[str, str] = json.loads(raw)
    d = Path(sheets_dir)
    d.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for brand, url in urls.items():
            try:
                r = client.get(url)
                r.raise_for_status()
                (d / f"Influencer {brand.capitalize()}.csv").write_text(r.text, encoding="utf-8")
                counts[brand] = len(parse_klar_sheet(r.text, brand))
            except Exception as e:  # noqa: BLE001
                log.warning("klar sheet %s pull failed: %s", brand, e)
                counts[brand] = -1
    return counts


def creator_master(sheet: pd.DataFrame) -> pd.DataFrame:
    """One row per handle: brand(s), markets, deal type, category, codes, followers, campaigns, costs, reach filled."""
    cols = [
        "handle",
        "brands",
        "markets",
        "platform",
        "type_of_partnership",
        "category",
        "post_types",
        "discount_codes_sheet",
        "followers_sheet",
        "n_campaigns",
        "n_campaigns_with_reach",
        "n_campaigns_with_link",
        "fixed_costs_sheet",
        "reach_sheet",
        "first_posting_date",
        "last_posting_date",
        "link_to_profile",
    ]
    if sheet.empty:
        return pd.DataFrame(columns=cols)
    s = sheet.dropna(subset=["handle"])

    def _first(x: pd.Series) -> object:
        return next((v for v in x if isinstance(v, str) and v), None)

    def _join(x: pd.Series) -> str:
        return ", ".join(sorted({str(v) for v in x if isinstance(v, str) and v}))

    g = s.groupby("handle", as_index=False).agg(
        brands=("brand", _join),
        markets=("market", _join),
        platform=("platform", _first),
        type_of_partnership=("type_of_partnership", _first),
        category=("category", _first),
        post_types=("post_type", _join),
        discount_codes_sheet=("discount_codes", _join),
        followers_sheet=("followers", "max"),
        n_campaigns=("row", "size"),
        n_campaigns_with_reach=(
            "reach",
            lambda x: int((pd.to_numeric(x, errors="coerce").fillna(0) > 0).sum()),
        ),
        n_campaigns_with_link=("link_to_post", lambda x: int(x.notna().sum())),
        fixed_costs_sheet=("fixed_costs", "sum"),
        reach_sheet=("reach", lambda x: pd.to_numeric(x, errors="coerce").sum(min_count=1)),
        first_posting_date=("posting_date", "min"),
        last_posting_date=("posting_date", "max"),
        link_to_profile=("link_to_profile", _first),
    )
    return g[cols]


def sheet_reach(sheet: pd.DataFrame) -> pd.DataFrame:
    """Reach filled in the sheet, in the manual-reach layout (handle, post_url, date, reach, source)."""
    cols = ["handle", "post_url", "date", "reach", "source"]
    if sheet.empty:
        return pd.DataFrame(columns=cols)
    s = sheet[pd.to_numeric(sheet["reach"], errors="coerce").fillna(0) > 0]
    return pd.DataFrame(
        {
            "handle": s["handle"],
            "post_url": s["link_to_post"],
            "date": s["posting_date"],
            "reach": s["reach"],
            "source": "klar_sheet",
        }
    ).reset_index(drop=True)


def campaigns_missing_reach(sheet: pd.DataFrame) -> pd.DataFrame:
    """Paid campaigns (fixed costs > 0) with no Reach in the sheet: the to-do list for the Klar sheet."""
    if sheet.empty:
        return sheet
    s = sheet[
        (sheet["fixed_costs"].fillna(0) > 0) & ~(pd.to_numeric(sheet["reach"], errors="coerce").fillna(0) > 0)
    ]
    return s[
        [
            "brand",
            "row",
            "influencer_name",
            "handle",
            "market",
            "post_type",
            "posting_date",
            "fixed_costs",
            "link_to_post",
        ]
    ]
