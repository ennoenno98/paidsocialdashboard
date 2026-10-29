"""Manual-input Google Sheet ("Social dashboard – manual inputs") filled by the team.

Tabs: ``Creator reach`` (reach / views per creator post), ``Stories`` (story views per account and day),
``TikTok weekly`` (organic weekly numbers per TikTok account), ``Budget``, ``Creative tags`` (manual tag
overrides per paid-social asset) and ``Tests`` (creative tests: variants, hypothesis, learning). Row 1 = header, row 2 = help text,
data from row 3. Each tab is published as CSV (File -> Share -> Publish to web, one link per tab) and listed in
``INPUT_SHEET_CSV_URLS`` as JSON ``{"creator_reach": url, "stories": url, "tiktok_weekly": url, "budget": url}``;
``make refresh`` downloads them into ``INPUT_SHEET_DIR`` (default ``data/raw/input_sheet``). The dashboard reads
the cached CSVs.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

INPUT_DIR = Path(os.environ.get("INPUT_SHEET_DIR", "data/raw/input_sheet"))
TABS = ("creator_reach", "stories", "tiktok_weekly", "budget", "creative_tags", "tests")
ACCOUNT_RE = r"^[a-z]+/[a-z]+/[A-Z]{2,3}$"


def _read_tab(path: Path) -> pd.DataFrame:
    """CSV export of a tab: header row, help row, then data. Example rows ('example row – replace') are skipped."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    if len(df):
        df = df.iloc[1:]  # help row
    df = df[~df.apply(lambda r: any("example row" in str(v).lower() for v in r), axis=1)]
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)]
    return df.reset_index(drop=True)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.replace("€", "", regex=False).str.strip(),
        errors="coerce",
    )


def load_creator_reach(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    """-> manual-reach layout (handle, post_url, date, reach, source='input_sheet') plus brand/platform/views."""
    cols = ["handle", "post_url", "date", "reach", "source", "brand", "platform", "views", "entered_by"]
    df = _read_tab(Path(input_dir) / "creator_reach.csv")
    if df.empty or "handle" not in df.columns:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(
        {
            "handle": df["handle"].str.strip().str.lstrip("@").str.lower(),
            "post_url": df.get("post_url", pd.Series("", index=df.index)).replace("", None),
            "date": pd.to_datetime(df.get("posting_date", pd.Series("", index=df.index)), errors="coerce"),
            "reach": _num(df.get("reach", pd.Series("", index=df.index))),
            "source": "input_sheet",
            "brand": df.get("brand", pd.Series("", index=df.index)).str.strip().str.lower().replace("", None),
            "platform": df.get("platform", pd.Series("", index=df.index))
            .str.strip()
            .str.lower()
            .replace("", None),
            "views": _num(df.get("views", pd.Series("", index=df.index))),
            "entered_by": df.get("entered_by", pd.Series("", index=df.index)),
        }
    )
    out = out[out["handle"].ne("") & out["reach"].notna() & (out["reach"] > 0)]
    return out[cols].reset_index(drop=True)


def load_stories_manual(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    """-> rows in the ig_stories layout (one synthetic story per account/day with the typed sums)."""
    from src.ingest.windsor import STORY_COLS, _split_key

    df = _read_tab(Path(input_dir) / "stories.csv")
    if df.empty or "account" not in df.columns:
        return pd.DataFrame(columns=STORY_COLS)
    d = pd.to_datetime(df["date"], errors="coerce")
    out = pd.DataFrame(
        {
            "account": df["account"].str.strip(),
            "story_id": [
                "manual:" + a + ":" + str(x.date()) for a, x in zip(df["account"].str.strip(), d, strict=True)
            ],
            "timestamp": d.dt.tz_localize("UTC"),
            "date": d.dt.date,
            "permalink": None,
            "reach": _num(df.get("reach", pd.Series("", index=df.index))),
            "views": _num(df.get("views", pd.Series("", index=df.index))),
            "replies": _num(df.get("replies", pd.Series("", index=df.index))),
            "shares": _num(df.get("shares", pd.Series("", index=df.index))),
            "interactions": None,
            "exits": _num(df.get("exits", pd.Series("", index=df.index))),
            "taps_forward": None,
            "taps_back": None,
            "swipe_forward": None,
        }
    )
    out = out[out["account"].str.match(ACCOUNT_RE) & d.notna()]
    out["n_stories_manual"] = _num(df.loc[out.index, "n_stories"]) if "n_stories" in df.columns else None
    out = _split_key(out)
    return out[[*STORY_COLS, "n_stories_manual"]].reset_index(drop=True)


def load_tiktok_weekly(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    """-> rows in the weekly_wide layout (kind organic, period_type cw) for TikTok accounts."""
    df = _read_tab(Path(input_dir) / "tiktok_weekly.csv")
    cols = ["brand", "platform", "market", "kind", "account", "year", "period_type", "period"]
    if df.empty or "account" not in df.columns:
        return pd.DataFrame(columns=cols)
    acc = df["account"].str.strip()
    ok = acc.str.match(ACCOUNT_RE)
    df, acc = df[ok], acc[ok]
    parts = acc.str.split("/", expand=True)
    out = pd.DataFrame(
        {
            "brand": parts[0],
            "platform": parts[1],
            "market": parts[2],
            "kind": "organic",
            "account": acc,
            "year": _num(df["year"]).astype("Int64"),
            "period_type": "cw",
            "period": _num(df["cw"]).astype("Int64"),
        }
    )
    for c in (
        "followers",
        "net_follows",
        "views",
        "reach",
        "likes",
        "comments",
        "shares",
        "saves",
        "n_posts",
        "boost_spend",
    ):
        if c in df.columns:
            out[c] = _num(df[c])
    out["source"] = "input_sheet"
    return out.dropna(subset=["year", "period"]).reset_index(drop=True)


def load_budget(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    df = _read_tab(Path(input_dir) / "budget.csv")
    cols = ["brand", "year", "month", "budget_performance", "budget_awareness", "budget_total"]
    if df.empty or "brand" not in df.columns:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(
        {
            "brand": df["brand"].str.strip().str.lower(),
            "year": _num(df["year"]).astype("Int64"),
            "month": _num(df["month"]).astype("Int64"),
            "budget_performance": _num(df.get("budget_performance", pd.Series("", index=df.index))),
            "budget_awareness": _num(df.get("budget_awareness", pd.Series("", index=df.index))),
            "budget_total": _num(df.get("budget_total", pd.Series("", index=df.index))),
        }
    )
    out["budget_total"] = out["budget_total"].where(
        out["budget_total"].notna(), out[["budget_performance", "budget_awareness"]].sum(axis=1, min_count=1)
    )
    return out.dropna(subset=["year", "month"]).reset_index(drop=True)


def load_creative_tags(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    """Manual creative tags: ``asset_id`` (= Meta ad name), ``visual_subject``, ``claim``, ``note``.
    Empty cells leave the derived tag in place; a value outside the vocabulary is kept as typed."""
    cols = ["asset_id", "visual_subject", "claim", "note", "entered_by"]
    df = _read_tab(Path(input_dir) / "creative_tags.csv")
    if df.empty or "asset_id" not in df.columns:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({"asset_id": df["asset_id"].str.strip()})
    for c in cols[1:]:
        out[c] = df.get(c, pd.Series("", index=df.index)).astype(str).str.strip().replace("", None)
    for c in ("visual_subject", "claim"):
        out[c] = out[c].map(lambda v: v.lower().replace(" ", "_") if isinstance(v, str) else v)
    return out[out["asset_id"].ne("")].reset_index(drop=True)


def load_tests(input_dir: Path | str = INPUT_DIR) -> pd.DataFrame:
    """Creative tests, one row per variant: ``test_id, test_name, variable, hypothesis, variant, asset_id,
    primary_kpi (roas | ctr | cpa), learning``."""
    cols = [
        "test_id",
        "test_name",
        "variable",
        "hypothesis",
        "variant",
        "asset_id",
        "primary_kpi",
        "learning",
    ]
    df = _read_tab(Path(input_dir) / "tests.csv")
    if df.empty or "asset_id" not in df.columns or "test_id" not in df.columns:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({c: df.get(c, pd.Series("", index=df.index)).astype(str).str.strip() for c in cols})
    out = out.replace("", None)
    return out[out["asset_id"].notna() & out["test_id"].notna()].reset_index(drop=True)


def pull_input_sheet(
    urls_json: str | None = None, input_dir: Path | str = INPUT_DIR, timeout: float = 60.0
) -> dict[str, int]:
    raw = urls_json or os.environ.get("INPUT_SHEET_CSV_URLS", "")
    if not raw:
        return {}
    urls: dict[str, str] = json.loads(raw)
    d = Path(input_dir)
    d.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for tab, url in urls.items():
            if tab not in TABS:
                log.warning("input sheet: unknown tab %s", tab)
                continue
            try:
                r = client.get(url)
                r.raise_for_status()
                (d / f"{tab}.csv").write_text(r.text, encoding="utf-8")
                counts[tab] = max(len(pd.read_csv(io.StringIO(r.text))) - 1, 0)
            except Exception as e:  # noqa: BLE001
                log.warning("input sheet tab %s pull failed: %s", tab, e)
                counts[tab] = -1
    return counts
