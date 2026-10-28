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
import numpy as np
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


def klar_rows_from_sheet(sheet: pd.DataFrame) -> list[dict[str, object]]:
    """Klar-API-shaped rows built from the Klar influencer sheets alone (campaign, costs = fixed + variable fee,
    reach, posting date). Used when no Klar API cache exists (fresh clone, cloud deploy without a snapshot):
    spend, CPM and the brand filter work, orders / revenue / ROAS stay 0 and are labelled ``source = sheet``."""
    if sheet.empty:
        return []
    rows: list[dict[str, object]] = []
    for r in sheet.itertuples(index=False):
        fixed = float(r.fixed_costs) if pd.notna(r.fixed_costs) else 0.0
        fee = float(r.variable_cost_fee) if pd.notna(r.variable_cost_fee) else 0.0
        codes = str(r.discount_codes) if pd.notna(r.discount_codes) else ""
        rows.append(
            {
                "influencer_name": r.influencer_name if pd.notna(r.influencer_name) else None,
                "campaign_name": r.campaign_name if pd.notna(r.campaign_name) else None,
                "platform": r.platform if pd.notna(r.platform) else None,
                "type_of_partnership": r.type_of_partnership if pd.notna(r.type_of_partnership) else None,
                "category": r.category if pd.notna(r.category) else None,
                "post_type": r.post_type if pd.notna(r.post_type) else None,
                "posting_date": r.posting_date.date() if pd.notna(r.posting_date) else None,
                "date": r.posting_date.date() if pd.notna(r.posting_date) else None,
                "discount_code": codes.split(",")[0] or None,
                "costs": fixed + fee,
                "fixed_costs": fixed,
                "var_costs": fee,
                "reach": float(r.reach) if pd.notna(r.reach) else None,
                "followers": float(r.followers) if pd.notna(r.followers) else None,
                "_brand": r.brand,
            }
        )
    return rows


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


# --------------------------------------------------------------------------------------
# worksheet tabs of the same workbooks: the team's own planning tabs ("Dashboard" / "Working Sheet") with
# Tier, Category (industry), Goal (Brand vs Performance), Followers and campaign Reach per creator.
# --------------------------------------------------------------------------------------
WS_COLS = [
    "brand",
    "tab",
    "row",
    "handle",
    "name",
    "market",
    "status",
    "month",
    "go_live",
    "asset",
    "platform",
    "category",
    "tier",
    "goal",
    "type_of_partnership",
    "cost",
    "code",
    "followers",
    "reach",
    "rating",
]
WS_HEADERS = {
    "name": {"Name", "Influencer/Affiliate Name"},
    "market": {"Country"},
    "status": {"Status"},
    "month": {"Month"},
    "go_live": {"1st Go Live", "Go Live", "Posting Date"},
    "asset": {"Asset"},
    "platform": {"Plattform", "Platform"},
    "category": {"Category"},
    "tier": {"Tier"},
    "goal": {"Goal", "Campaign Name"},
    "type_of_partnership": {"Type of Partnership"},
    "cost": {"Cost", "Fixed Costs"},
    "code": {"Code"},
    "followers": {"Followers"},
    "reach": {"Reach"},
    "rating": {"Rating"},
}
WS_TABS = ("Dashboard", "Working Sheet", "old")  # "old": pre-Klar campaigns, reach typed in thousands
MONTHS_EN = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def _ws_number(v: object) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("€", "").replace(" ", "")
    if "," in t and "." in t:  # 5.400,00
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _ws_month(v: object, year: int) -> object:
    if v is None or v == "":
        return pd.NaT
    if hasattr(v, "year"):
        return pd.Timestamp(v).normalize()
    t = str(v).strip().lower()
    if t in MONTHS_EN:
        return pd.Timestamp(year=year, month=MONTHS_EN[t], day=1)
    n = _ws_number(t)
    if n and 1 <= n <= 12:
        return pd.Timestamp(year=year, month=int(n), day=1)
    return pd.NaT


def parse_worksheet(xlsx_path: Path | str, brand: str, year: int | None = None) -> pd.DataFrame:
    """Planning tabs (``Dashboard`` / ``Working Sheet``) of an 'Influencer <Brand>' workbook -> one row per campaign."""
    import openpyxl

    year = year or pd.Timestamp.today().year
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    recs: list[dict[str, object]] = []
    for tab in WS_TABS:
        if tab not in wb.sheetnames:
            continue
        rows = list(wb[tab].iter_rows(values_only=True))
        hi = next(
            (
                i
                for i, r in enumerate(rows)
                if r and any(isinstance(c, str) and c.strip() in WS_HEADERS["name"] for c in r)
            ),
            None,
        )
        if hi is None:
            continue
        hdr = [str(c).strip() if c is not None else "" for c in rows[hi]]
        idx: dict[str, int] = {}
        for key, names in WS_HEADERS.items():
            for i, h in enumerate(hdr):
                if h in names and key not in idx:
                    idx[key] = i
        for n, r in enumerate(rows[hi + 1 :], start=hi + 2):
            if not r or not any(c not in (None, "") for c in r):
                continue
            vals = {key: (r[i] if i < len(r) else None) for key, i in idx.items()}
            get = vals.get
            name = get("name")
            handle = normalise_handle(name)  # the planning tabs list creators by handle
            if not handle:
                continue
            go_live = _ws_month(get("go_live"), year)
            if go_live is pd.NaT:
                go_live = _ws_month(get("month"), year)
            market = str(get("market") or "").strip().upper()
            market = {"🥨🇩🇪": "DE", "🤌🇮🇹": "IT"}.get(market, market)
            recs.append(
                {
                    "brand": brand,
                    "tab": tab,
                    "row": n,
                    "handle": handle,
                    "name": str(name).strip() if name else None,
                    "market": market if re.fullmatch(r"[A-Z]{2}", market or "") else None,
                    "status": str(get("status")).strip().lower() if get("status") else None,
                    "month": get("month"),
                    "go_live": go_live,
                    "asset": get("asset"),
                    "platform": str(get("platform")).strip().lower() if get("platform") else None,
                    "category": str(get("category")).strip() if get("category") else None,
                    "tier": str(get("tier")).strip().capitalize() if get("tier") else None,
                    "goal": str(get("goal")).strip() if get("goal") else None,
                    "type_of_partnership": get("type_of_partnership"),
                    "cost": _ws_number(get("cost")),
                    "code": get("code"),
                    "followers": _ws_number(get("followers")),
                    "reach": (
                        (_ws_number(get("reach")) or 0) * 1000
                        if tab == "old" and _ws_number(get("reach")) and _ws_number(get("reach")) < 1000
                        else _ws_number(get("reach"))
                    ),
                    "rating": get("rating"),
                }
            )
    df = pd.DataFrame.from_records(recs, columns=WS_COLS)
    if not df.empty:
        df["go_live"] = pd.to_datetime(df["go_live"], errors="coerce")
    return df


def load_worksheets(sheets_dir: Path | str = SHEETS_DIR) -> pd.DataFrame:
    d = Path(sheets_dir)
    frames = [parse_worksheet(p, brand_from_name(p.stem)) for p in sorted(d.glob("*.xlsx"))]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=WS_COLS)


def creator_attributes(ws: pd.DataFrame, followers_fallback: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per handle: tier (worksheet label, else derived from followers), industry (category), goal(s),
    followers, market, brand(s). ``tier_source`` says where the tier came from."""
    from src.transform.scorecard import tier_from_followers

    cols = [
        "handle",
        "brands",
        "market",
        "category_ws",
        "tier",
        "tier_source",
        "goal_ws",
        "followers_ws",
        "n_rows",
        "alias",
    ]
    if ws.empty:
        return pd.DataFrame(columns=cols)

    def _first(x: pd.Series) -> object:
        return next((v for v in x if isinstance(v, str) and v.strip()), None)

    def _mode(x: pd.Series) -> object:
        vals = [v for v in x if isinstance(v, str) and v.strip()]
        return pd.Series(vals).mode().iloc[0] if vals else None

    g = ws.groupby("handle", as_index=False).agg(
        brands=("brand", lambda x: ", ".join(sorted(set(x)))),
        market=("market", _first),
        category_ws=("category", _mode),
        tier_label=("tier", _first),
        goal_ws=("goal", _mode),
        followers_ws=("followers", "max"),
        n_rows=("row", "size"),
        alias=("name", _first),
    )
    if followers_fallback is not None and not followers_fallback.empty:
        fb = followers_fallback.drop_duplicates("handle").set_index("handle")["followers"]
        g["followers_ws"] = g["followers_ws"].where(g["followers_ws"].notna(), g["handle"].map(fb))
    derived = g["followers_ws"].map(tier_from_followers)
    g["tier"] = g["tier_label"].where(g["tier_label"].notna(), derived).fillna("Unknown")
    g["tier_source"] = np.where(
        g["tier_label"].notna(), "worksheet", np.where(derived.notna(), "derived from followers", "n/a")
    )
    g["alias"] = g["handle"]  # name -> handle aliases are resolved by alias_map(); keep the handle here
    return g[cols]


def worksheet_reach(ws: pd.DataFrame) -> pd.DataFrame:
    """Campaign reach typed into the planning tabs, in the manual-reach layout (source='worksheet')."""
    cols = ["handle", "post_url", "date", "reach", "source"]
    if ws.empty:
        return pd.DataFrame(columns=cols)
    s = ws[
        pd.to_numeric(ws["reach"], errors="coerce").fillna(0) > 100
    ]  # the 'old' tab holds reach in k, skipped
    return pd.DataFrame(
        {
            "handle": s["handle"],
            "post_url": None,
            "date": s["go_live"],
            "reach": s["reach"],
            "source": "worksheet",
        }
    ).reset_index(drop=True)


def library_followers(xlsx_path: Path | str) -> pd.DataFrame:
    """'Library <country>' tabs: creator handle -> followers (used for tier derivation)."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    recs = []
    for tab in wb.sheetnames:
        if not tab.lower().startswith("library"):
            continue
        for r in wb[tab].iter_rows(values_only=True):
            if not r or not r[0] or str(r[0]).strip() == "Name":
                continue
            handles = [
                normalise_handle(c) for c in r[1:3] if isinstance(c, str) and c.strip().startswith("@")
            ]
            followers = next((_ws_number(c) for c in r[1:5] if isinstance(c, (int, float))), None)
            for h in handles:
                if h and followers:
                    recs.append({"handle": h, "followers": followers})
    return pd.DataFrame.from_records(recs, columns=["handle", "followers"])


def load_library_followers(sheets_dir: Path | str = SHEETS_DIR) -> pd.DataFrame:
    frames = [library_followers(p) for p in sorted(Path(sheets_dir).glob("*.xlsx"))]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["handle", "followers"])
