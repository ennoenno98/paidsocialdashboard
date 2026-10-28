"""Klar marketing attribution at ad level (``marketing_flex`` report: channel_name x campaign x content x date).

``content`` is the Meta ad name and ``campaign`` the Meta campaign, so Klar's attributed orders and revenue can be
joined to the Windsor ad feed. Sources, in order: JSON exports of the report (the shape the Klar MCP server /
Public API return: ``{"rows": [...]}``) in ``KLAR_MARKETING_DIR`` (default ``data/raw/klar_marketing``), or a CSV
export of the same report (``KLAR_MARKETING_CSV``). Rows are de-duplicated on (date, campaign, content), the
latest file wins. The Klar Public API client in ``src/ingest/klar.py`` is still a stub, so ``make refresh`` does
not pull this report itself; drop the export files in and they are picked up.

Klar's own ``roas`` is ``gross_revenue / cost``; ``channel_purchases`` / ``channel_purchase_value`` are Meta's
attributed numbers as seen by Klar and are not used here (the Windsor feed has them directly).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MARKETING_DIR = Path(os.environ.get("KLAR_MARKETING_DIR", "data/raw/klar_marketing"))
KLAR_COLS = [
    "date",
    "channel_name",
    "campaign",
    "ad_name",
    "klar_cost",
    "klar_orders",
    "klar_new_customers",
    "klar_net_revenue",
    "klar_gross_revenue",
]
KLAR_SUM = ["klar_cost", "klar_orders", "klar_new_customers", "klar_net_revenue", "klar_gross_revenue"]
_RENAME = {
    "content": "ad_name",
    "cost": "klar_cost",
    "orders": "klar_orders",
    "new_customers": "klar_new_customers",
    "net_revenue": "klar_net_revenue",
    "gross_revenue": "klar_gross_revenue",
}


def _frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=KLAR_COLS)
    df = pd.DataFrame(rows).rename(columns=_RENAME)
    for c in KLAR_COLS:
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in KLAR_SUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ad_name"] = df["ad_name"].astype("string").str.strip()
    df["campaign"] = df["campaign"].astype("string").str.strip()
    df = df[df["date"].notna() & df["ad_name"].notna() & df["ad_name"].ne("") & df["ad_name"].ne("n/a")]
    return df[KLAR_COLS]


def load_klar_marketing(
    marketing_dir: Path | str = MARKETING_DIR, csv_path: Path | str | None = None, meta_only: bool = True
) -> pd.DataFrame:
    """Every JSON export in ``marketing_dir`` (sorted by name, later files override) plus an optional CSV."""
    frames: list[pd.DataFrame] = []
    d = Path(marketing_dir)
    if d.exists():
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError) as e:
                log.warning("klar marketing export %s unreadable: %s", p, e)
                continue
            rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
            frames.append(_frame(rows if isinstance(rows, list) else []))
    csv = (
        Path(csv_path)
        if csv_path
        else (Path(os.environ["KLAR_MARKETING_CSV"]) if os.environ.get("KLAR_MARKETING_CSV") else None)
    )
    if csv and csv.exists():
        raw = pd.read_csv(csv)
        raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
        frames.append(_frame(raw.to_dict("records")))
    if not frames:
        return pd.DataFrame(columns=KLAR_COLS)
    out = pd.concat(frames, ignore_index=True)
    if meta_only:
        out = out[
            out["channel_name"].astype(str).str.contains("meta|facebook|instagram", case=False, regex=True)
        ]
    out = out.drop_duplicates(["date", "campaign", "ad_name"], keep="last")
    return out.sort_values(["date", "campaign", "ad_name"]).reset_index(drop=True)


def allocate_to_ads(ads: pd.DataFrame, klar: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach Klar orders / revenue to the enriched ad rows, split across ad sets of the same (date, campaign,
    asset) in proportion to Meta spend (equal split when the day had no spend). Returns (ads, unmatched Klar
    rows). Totals are preserved: every matched Klar row lands fully on the ad rows."""
    a = ads.copy()
    for c in KLAR_SUM:
        a[c] = np.nan
    a["klar_matched"] = False
    if a.empty or klar.empty:
        return a, klar.copy()
    key = ["date", "campaign", "asset_id"]
    k = klar.rename(columns={"ad_name": "asset_id"}).copy()
    k["asset_id"] = k["asset_id"].astype(str)
    k["campaign"] = k["campaign"].astype(str)
    a["_campaign"] = a["campaign"].astype(str)
    grp_spend = a.groupby(["date", "_campaign", "asset_id"])["spend"].transform(lambda s: s.fillna(0))
    tot = a.groupby(["date", "_campaign", "asset_id"])["spend"].transform(lambda s: s.fillna(0).sum())
    n = a.groupby(["date", "_campaign", "asset_id"])["spend"].transform("size")
    share = np.where(tot > 0, grp_spend / tot.replace(0, np.nan), 1.0 / n)
    a["_share"] = share
    kk = k.set_index(key)[KLAR_SUM]
    kk = kk[~kk.index.duplicated(keep="last")]
    idx = pd.MultiIndex.from_arrays([a["date"], a["_campaign"], a["asset_id"]], names=key)
    hit = idx.isin(kk.index)
    for c in KLAR_SUM:
        vals = kk[c].reindex(idx).to_numpy()
        a[c] = np.where(hit, vals * a["_share"].to_numpy(), np.nan)
    a["klar_matched"] = hit
    matched_keys = set(idx[hit])
    un = k[
        ~pd.MultiIndex.from_arrays([k["date"], k["campaign"], k["asset_id"]], names=key).isin(matched_keys)
    ]
    return a.drop(columns=["_campaign", "_share"]), un.rename(columns={"asset_id": "ad_name"}).reset_index(
        drop=True
    )
