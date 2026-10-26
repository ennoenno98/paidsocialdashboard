"""Orchestration: parse workbook, load/pull Klar + Instagram, compute metrics, build one Bundle."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingest import instagram as ig
from src.ingest import klar as klar_mod
from src.ingest.xlsx import ParseResult, load_config, parse_workbook, pivot_wide
from src.transform import metrics as mx
from src.transform.join import join_klar_creators

log = logging.getLogger(__name__)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
PROCESSED = Path("data/processed")
DEFAULT_XLSX = Path(os.environ.get("SOCIAL_XLSX", "data/Social_Media.xlsx"))


@dataclass
class Bundle:
    xlsx: ParseResult
    is_fixture: bool
    weekly_wide: pd.DataFrame
    monthly_wide: pd.DataFrame
    posts: pd.DataFrame
    account_er_weekly: pd.DataFrame
    boost_weekly: pd.DataFrame
    boost_monthly: pd.DataFrame
    weekly_rollup: pd.DataFrame
    spend_recon: pd.DataFrame
    er_recon: pd.DataFrame
    weekly_er_recon: pd.DataFrame
    klar: pd.DataFrame
    klar_creators: pd.DataFrame
    creator_join: dict[str, pd.DataFrame]
    influencers: pd.DataFrame
    influencer_posts: pd.DataFrame
    ig_posts: pd.DataFrame
    ig_scan: pd.DataFrame
    manual_reach: pd.DataFrame
    status: dict[str, Any] = field(default_factory=dict)

    def issues_df(self) -> pd.DataFrame:
        base = self.xlsx.issues_df()
        extra = []
        for _, r in self.creator_join["unmatched_klar"].iterrows():
            extra.append(
                {
                    "source": "klar",
                    "severity": "warn",
                    "where": r.get("influencer_name"),
                    "message": "Klar influencer not matched to Creators (code or name)",
                }
            )
        for _, r in self.creator_join["unmatched_creators"].iterrows():
            extra.append(
                {
                    "source": "creators",
                    "severity": "info",
                    "where": r.get("name"),
                    "message": "creator without Klar rows in period",
                }
            )
        if not self.influencers.empty:
            for _, r in self.influencers[
                self.influencers["reach_source"].eq("n/a") & (self.influencers["costs"] > 0)
            ].iterrows():
                extra.append(
                    {
                        "source": "influencers",
                        "severity": "warn",
                        "where": r["influencer_name"],
                        "message": "cost but no reach (Klar reach=0, no manual reach) -> CPM n/a",
                    }
                )
        if not self.ig_scan.empty:
            for _, r in self.ig_scan[~self.ig_scan["scannable"]].iterrows():
                extra.append(
                    {
                        "source": "instagram",
                        "severity": "info",
                        "where": r["handle"],
                        "message": f"not scannable via Business Discovery: {r['error']}",
                    }
                )
        for k, v in self.status.items():
            extra.append({"source": "fetch", "severity": "info", "where": k, "message": str(v)})
        return pd.concat([base, pd.DataFrame(extra, columns=base.columns)], ignore_index=True)


def resolve_xlsx(path: Path | str | None) -> tuple[Path, bool]:
    p = Path(path) if path else DEFAULT_XLSX
    if p.exists():
        return p, "fixture" in p.name.lower()
    return FIXTURES / "Social_Media_fixture.xlsx", True


def _read_parquet(p: Path, cols: list[str] | None = None) -> pd.DataFrame:
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=cols or [])


def load_klar(processed: Path = PROCESSED, allow_fixture: bool = True) -> tuple[pd.DataFrame, str]:
    p = processed / "klar_influencer.parquet"
    if p.exists():
        return pd.read_parquet(
            p
        ), f"processed parquet ({dt.datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M})"
    cache = klar_mod.latest_cache()
    if cache:
        return klar_mod.klar_frame(
            json.load(open(cache, encoding="utf-8"))["rows"]
        ), f"raw cache {cache.name}"
    if allow_fixture:
        fx = FIXTURES / "klar_influencer_flex.json"
        return klar_mod.klar_frame(
            json.load(open(fx, encoding="utf-8"))["rows"]
        ), "FIXTURE (tests/fixtures/klar_influencer_flex.json)"
    return klar_mod.klar_frame([]), "none"


def load_ig(
    processed: Path = PROCESSED, allow_fixture: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    posts_p, scan_p = processed / "ig_posts.parquet", processed / "ig_creator_scan.parquet"
    if posts_p.exists():
        return (
            _read_parquet(posts_p, ig.IG_POST_COLS),
            _read_parquet(scan_p, ig.SCAN_COLS),
            "processed parquet",
        )
    if allow_fixture:
        src = ig.FixtureSource(FIXTURES / "ig_media.json", FIXTURES / "ig_business_discovery.json")
        ids = {
            "vegavero/instagram/IT": "17841400000000001",
            "vegavero/instagram/DE": "17841400000000002",
            "wowtamins/instagram/DE": "17841400000000003",
            "jasnum/instagram/IT": "17841400000000004",
        }
        now = dt.datetime(2026, 10, 26, 6, tzinfo=dt.UTC)
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "vanatari_ig_fixture.parquet"
        if tmp.exists():
            tmp.unlink()
        posts = ig.pull_own_accounts(src, ids, tmp, now=now)
        scan = ig.scan_creators(
            src,
            ids["vegavero/instagram/IT"],
            ["fit_giulia", "anna.eats.well", "yogamitlena", "marco_lifestyle", "cucina_di_sara"],
            now=now,
        )
        return posts, scan, "FIXTURE (tests/fixtures/ig_*.json)"
    return pd.DataFrame(columns=ig.IG_POST_COLS), pd.DataFrame(columns=ig.SCAN_COLS), "none"


def build_bundle(
    xlsx: Path | str | None = None,
    processed: Path = PROCESSED,
    allow_fixture: bool = True,
    manual_reach_csv: Path | str | None = None,
    klar_window_days: int = 400,
) -> Bundle:
    path, is_fixture = resolve_xlsx(xlsx)
    res = parse_workbook(path, load_config())
    weekly_wide, monthly_wide = pivot_wide(res.weekly), pivot_wide(res.monthly)
    posts = mx.add_post_metrics(res.posts)
    acc_er = mx.account_er(posts)
    status: dict[str, Any] = {"workbook": f"{path}{' (FIXTURE)' if is_fixture else ''}"}

    klar, status["klar"] = load_klar(processed, allow_fixture)
    today = dt.date.today()
    summary = klar_mod.creator_summary(klar, since=today - dt.timedelta(days=klar_window_days), until=today)
    join = join_klar_creators(summary, res.creators)
    manual_p = Path(manual_reach_csv) if manual_reach_csv else ig.MANUAL_REACH_CSV
    if not manual_p.exists() and is_fixture:
        manual_p = FIXTURES / "influencer_reach.csv"
    manual = ig.load_manual_reach(manual_p)
    influencers = ig.influencer_cpm(join["matched"], manual)
    inf_posts = ig.influencer_post_cpm(klar, join["matched"], manual)

    ig_posts, ig_scan, status["instagram"] = load_ig(processed, allow_fixture)
    ig_posts = ig.ig_post_metrics(ig_posts)
    if not ig_scan.empty and not influencers.empty:
        influencers = influencers.merge(
            ig_scan[
                [
                    "handle",
                    "scannable",
                    "followers_count",
                    "interactions_per_post",
                    "posts_per_30d",
                    "last_post",
                ]
            ].rename(columns={"handle": "creator_handle", "followers_count": "followers_ig"}),
            on="creator_handle",
            how="left",
        )

    return Bundle(
        xlsx=res,
        is_fixture=is_fixture,
        weekly_wide=weekly_wide,
        monthly_wide=monthly_wide,
        posts=posts,
        account_er_weekly=acc_er,
        boost_weekly=mx.boosting_metrics(weekly_wide),
        boost_monthly=mx.boosting_metrics(monthly_wide),
        weekly_rollup=mx.weekly_rollup(weekly_wide),
        spend_recon=mx.reconcile_boost_spend(monthly_wide, res.boosting_susy, res.susy_budget),
        er_recon=mx.er_reconciliation(posts),
        weekly_er_recon=mx.weekly_er_vs_sheet(weekly_wide, acc_er),
        klar=klar,
        klar_creators=summary,
        creator_join=join,
        influencers=influencers,
        influencer_posts=inf_posts,
        ig_posts=ig_posts,
        ig_scan=ig_scan,
        manual_reach=manual,
        status=status,
    )


def refresh(
    xlsx: Path | str | None = None, out_dir: Path = PROCESSED, klar_days: int = 400, live: bool = True
) -> dict[str, str]:
    """``make refresh``: run all ingests and write parquet to data/processed. Never raises on a missing API."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}
    path, is_fixture = resolve_xlsx(xlsx)
    res = parse_workbook(path, load_config())
    for name, df in res.frames().items():
        df.to_parquet(out_dir / f"xlsx_{name}.parquet", index=False)
    res.coverage().to_csv(out_dir / "xlsx_block_coverage.csv", index=False)
    status["workbook"] = f"parsed {path} ({len(res.blocks)} blocks){' FIXTURE' if is_fixture else ''}"

    # Klar
    try:
        if live and os.environ.get("KLAR_API_KEY"):
            client: klar_mod.KlarClient = klar_mod.HttpKlarClient()
        elif os.environ.get("KLAR_CSV_EXPORT"):
            client = klar_mod.CsvExportKlarClient(os.environ["KLAR_CSV_EXPORT"])
        else:
            cache = klar_mod.latest_cache()
            client = klar_mod.FixtureKlarClient(cache or FIXTURES / "klar_influencer_flex.json")
            status["klar_source"] = f"{'cache ' + cache.name if cache else 'FIXTURE'}"
        df, raw = klar_mod.pull_klar(client, days=klar_days, raw_dir=klar_mod.RAW_DIR)
        df.to_parquet(out_dir / "klar_influencer.parquet", index=False)
        status["klar"] = f"ok: {len(df)} rows -> {raw}"
    except NotImplementedError as e:
        status["klar"] = f"not configured: {e}"
    except Exception as e:  # noqa: BLE001
        status["klar"] = f"failed: {type(e).__name__}: {e}"

    # Instagram
    try:
        ids = ig.account_ids_from_env()
        if live and os.environ.get("META_ACCESS_TOKEN") and ids:
            src: ig.InstagramSource = ig.GraphApiSource()
        elif live and os.environ.get("WINDSOR_API_KEY") and ids:
            src = ig.WindsorSource()
        else:
            src = ig.FixtureSource(FIXTURES / "ig_media.json", FIXTURES / "ig_business_discovery.json")
            ids = ids or {
                "vegavero/instagram/IT": "17841400000000001",
                "vegavero/instagram/DE": "17841400000000002",
                "wowtamins/instagram/DE": "17841400000000003",
                "jasnum/instagram/IT": "17841400000000004",
            }
            status["instagram_source"] = "FIXTURE"
        posts = ig.pull_own_accounts(src, ids, out_dir / "ig_posts.parquet")
        status["instagram_posts"] = f"ok: {len(posts)} media"
        klar_df = (
            pd.read_parquet(out_dir / "klar_influencer.parquet")
            if (out_dir / "klar_influencer.parquet").exists()
            else klar_mod.klar_frame([])
        )
        active = klar_mod.creator_summary(klar_df)
        join = join_klar_creators(active[active["active_recent"]], res.creators)
        handles = set(res.creators["handle"].dropna()) | set(join["matched"]["creator_handle"].dropna())
        own = next(iter(ids.values()))
        scan = ig.scan_creators(src, own, sorted(handles))
        scan.to_parquet(out_dir / "ig_creator_scan.parquet", index=False)
        status["instagram_scan"] = f"ok: {int(scan['scannable'].sum())}/{len(scan)} scannable"
    except Exception as e:  # noqa: BLE001
        status["instagram"] = f"failed: {type(e).__name__}: {e}"

    with open(out_dir / "refresh_status.json", "w", encoding="utf-8") as fh:
        json.dump({"at": dt.datetime.now(dt.UTC).isoformat(), **status}, fh, indent=1)
    return status
