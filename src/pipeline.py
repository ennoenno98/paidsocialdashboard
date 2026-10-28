"""Orchestration: workbook + Windsor (Instagram organic, Meta boosts, creator public counts) + Klar -> Bundle.

Source precedence
* Instagram own accounts & boosts: Windsor cache (``data/raw/windsor``) -> live Windsor pull when
  ``WINDSOR_API_KEY`` is set -> Graph-API/fixture path. The workbook stays the source for TikTok and as
  history / reconciliation for Instagram.
* Creators master: Klar (handle, deal type, code, category, followers). The Creators sheet is supplementary.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from src.bootstrap import bootstrap
from src.ingest import input_sheet as inp
from src.ingest import instagram as ig
from src.ingest import klar as klar_mod
from src.ingest import klar_sheet as ks
from src.ingest import windsor as wz
from src.ingest.xlsx import ParseResult, load_config, parse_workbook, pivot_wide
from src.transform import api_metrics as am
from src.transform import metrics as mx
from src.transform.join import join_klar_creators

log = logging.getLogger(__name__)
load_dotenv()  # local .env (gitignored); real env vars / Streamlit Cloud secrets / Actions secrets take precedence

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
    # API (Windsor) frames, scope='api'
    ig_daily: pd.DataFrame
    boosted: pd.DataFrame
    api_weekly: pd.DataFrame
    api_monthly: pd.DataFrame
    creators_public: pd.DataFrame
    collab_posts: pd.DataFrame  # Instagram Collab posts owned by a creator, co-authored by an own account
    ig_stories: pd.DataFrame
    klar_sheet: pd.DataFrame  # Klar influencer Google Sheets, one row per campaign
    klar_sheet_master: pd.DataFrame  # one row per creator handle from the sheets
    klar_worksheet: pd.DataFrame  # planning tabs of the same workbooks (tier, industry, goal, reach)
    creator_attrs: pd.DataFrame  # per handle: tier, industry, goal, followers, market
    status: dict[str, Any] = field(default_factory=dict)

    @property
    def has_api(self) -> bool:
        return not self.api_weekly.empty

    def influencers_for(self, since: dt.date, until: dt.date) -> pd.DataFrame:
        """Creator table for a period (campaign posting date or orders inside [since, until])."""
        return build_influencers(
            self.klar,
            self.xlsx.creators,
            self.klar_sheet,
            self.klar_sheet_master,
            self.creator_attrs,
            self.manual_reach,
            self.ig_scan,
            since,
            until,
        )["influencers"]

    def issues_df(self) -> pd.DataFrame:
        base = self.xlsx.issues_df()
        extra = []
        for _, r in self.creator_join["unmatched_klar"].iterrows():
            extra.append(
                {
                    "source": "klar",
                    "severity": "info",
                    "where": r.get("influencer_name"),
                    "message": "Klar creator not in the Creators sheet (Klar is the master; sheet deal text missing)",
                }
            )
        if not self.influencers.empty:
            miss = self.influencers[
                self.influencers["reach_source"].eq("n/a") & (self.influencers["costs"] > 0)
            ]
            for _, r in miss.iterrows():
                extra.append(
                    {
                        "source": "influencers",
                        "severity": "warn",
                        "where": r["influencer_name"],
                        "message": "cost but no reach (Klar reach=0, no manual reach) -> CPM n/a",
                    }
                )
        if not self.boosted.empty:
            un = self.boosted[~self.boosted["mapped"]]
            if not un.empty:
                extra.append(
                    {
                        "source": "windsor/facebook",
                        "severity": "warn",
                        "where": f"{un['campaign'].nunique()} boost campaigns",
                        "message": f"boosted posts not matched to an own post: €{un['spend'].sum():,.0f} spend without market",
                    }
                )
        if not self.ig_scan.empty and "scannable" in self.ig_scan:
            for _, r in self.ig_scan[~self.ig_scan["scannable"].astype(bool)].iterrows():
                extra.append(
                    {
                        "source": "instagram",
                        "severity": "info",
                        "where": r["handle"],
                        "message": f"not scannable: {r.get('error')}",
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


def parse_result_from_parquet(processed: Path = PROCESSED) -> ParseResult | None:
    """The workbook frames as written by ``refresh`` (``xlsx_*.parquet`` + block coverage CSV), for deployments
    that get their data from the private data repo and never see the workbook itself."""
    from src.models import BlockReport

    frames = {}
    for name in ("weekly", "monthly", "posts", "boosting_susy", "susy_budget", "creators"):
        f = processed / f"xlsx_{name}.parquet"
        if not f.exists():
            return None
        frames[name] = pd.read_parquet(f)
    blocks: list[BlockReport] = []
    cov = processed / "xlsx_block_coverage.csv"
    if cov.exists():
        for rec in pd.read_csv(cov).to_dict("records"):
            rec = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in rec.items()}
            w = rec.pop("warnings", None)
            rec["warnings"] = [x for x in str(w).split(" | ") if x] if w else []
            try:
                blocks.append(BlockReport(**rec))
            except Exception:  # noqa: BLE001
                continue
    stamp = dt.datetime.fromtimestamp((processed / "xlsx_weekly.parquet").stat().st_mtime)
    return ParseResult(
        **frames, blocks=blocks, issues=[], source=f"processed parquet from refresh ({stamp:%Y-%m-%d %H:%M})"
    )


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
    caches = klar_mod.latest_caches()
    if caches:
        return klar_mod.load_caches(), f"raw cache {', '.join(c.name for c in caches)}"
    if allow_fixture:
        fx = FIXTURES / "klar_influencer_flex.json"
        return klar_mod.klar_frame(
            json.load(open(fx, encoding="utf-8"))["rows"]
        ), "FIXTURE (tests/fixtures/klar_influencer_flex.json)"
    return klar_mod.klar_frame([]), "none"


WINDSOR_CACHE_MAX_AGE_H = float(os.environ.get("WINDSOR_CACHE_MAX_AGE_H", "24"))


def load_windsor(
    allow_fixture: bool = True, live_if_possible: bool = True
) -> tuple[dict[str, pd.DataFrame], str]:
    """Raw Windsor pulls: fresh cache -> live pull (WINDSOR_API_KEY; also when the cache is older than
    ``WINDSOR_CACHE_MAX_AGE_H``) -> stale cache -> fixture -> empty."""
    src = wz.CachedWindsorSource(wz.RAW_DIR)
    age = src.age_hours()
    cache_label = f"windsor cache {wz.RAW_DIR} ({len(src.available())}/{len(wz.PULLS)} pulls"
    if age is not None and age <= WINDSOR_CACHE_MAX_AGE_H:
        return wz.load_raw(src), f"{cache_label}, {age:.0f}h old)"
    if live_if_possible and os.environ.get("WINDSOR_API_KEY"):
        try:
            counts = wz.pull_all(wz.HttpWindsorClient(), wz.RAW_DIR)
            if all(n >= 0 for n in counts.values()):
                return wz.load_raw(wz.CachedWindsorSource(wz.RAW_DIR)), f"windsor live pull {counts}"
            log.warning("windsor live pull incomplete: %s", counts)
        except Exception as e:  # noqa: BLE001
            log.warning("windsor live pull failed: %s", e)
    if age is not None:
        return wz.load_raw(src), f"{cache_label}, {age:.0f}h old, STALE)"
    fx = FIXTURES / "windsor"
    if allow_fixture and fx.exists():
        return wz.load_raw(wz.CachedWindsorSource(fx)), "FIXTURE (tests/fixtures/windsor)"
    return wz.load_raw(wz.CachedWindsorSource(Path("/nonexistent"))), "none"


def windsor_frames(raw: dict[str, pd.DataFrame], cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    wcfg = cfg.get("windsor", {})
    ig_map = {str(k): str(v) for k, v in wcfg.get("instagram", {}).items()}
    fb_map = {str(k): str(v) for k, v in wcfg.get("facebook_ad_accounts", {}).items()}
    media = wz.ig_media_frame(raw, ig_map)
    owned = media[media["relationship"].eq("owned")] if not media.empty else media
    collab = media[media["relationship"].eq("collaborative")] if not media.empty else media
    daily = wz.ig_daily_frame(raw, ig_map)
    boosted = wz.boosted_frame(raw, owned, fb_map)
    public = wz.creators_public_frame(raw, wcfg.get("instagram_public_own", []))
    stories = wz.ig_stories_frame(raw, ig_map)
    posts_m = ig.ig_post_metrics(media) if not media.empty else media  # collab rows: no reach -> ER n/a
    posts_owned = ig.ig_post_metrics(owned) if not owned.empty else owned
    frames = {
        "media": media,
        "posts_m": posts_m,
        "collab": ig.ig_post_metrics(collab) if not collab.empty else collab,
        "daily": daily,
        "boosted": boosted,
        "public": public,
        "stories": stories,
    }
    for ptype, name in (("cw", "api_weekly"), ("month", "api_monthly")):
        org = am.organic_periods(daily, posts_owned, ptype)  # own posts only: collab posts are the creator's
        bst = am.boosted_periods(boosted, ptype)
        frames[name] = am.combined_periods(org, bst, am.story_periods(stories, ptype))
    return frames


def _pull_if_missing(dir_: Path, glob: str, env: str, pull: Any, label: str) -> str:
    """Cloud start-up: no cache on disk but published-CSV links in ``env`` -> download once."""
    if any(dir_.glob(glob)) or not os.environ.get(env):
        return ""
    try:
        counts = pull()
        return f"{label} pulled at start-up {counts}; "
    except Exception as e:  # noqa: BLE001
        log.warning("%s start-up pull failed: %s", label, e)
        return f"{label} start-up pull failed ({type(e).__name__}); "


def load_klar_sheets(allow_fixture: bool = True) -> tuple[pd.DataFrame, str]:
    """Klar influencer Google Sheets: cached CSV exports (pulled at start-up from ``KLAR_SHEET_CSV_URLS`` when the
    cache is empty) -> fixture -> empty."""
    note = _pull_if_missing(ks.SHEETS_DIR, "*.csv", "KLAR_SHEET_CSV_URLS", ks.pull_klar_sheets, "klar sheets")
    df = ks.load_klar_sheets(ks.SHEETS_DIR)
    if not df.empty:
        return df, f"{note}klar sheets {ks.SHEETS_DIR} ({df['brand'].nunique()} brands, {len(df)} campaigns)"
    fx = FIXTURES / "klar_sheets"
    if allow_fixture and fx.exists():
        return ks.load_klar_sheets(fx), "FIXTURE (tests/fixtures/klar_sheets)"
    return df, "none"


def load_ig_graph(
    processed: Path = PROCESSED, allow_fixture: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Fallback when Windsor has nothing: parquet written by ``refresh`` (Windsor-derived ``ig_posts`` or the
    Graph-API ``ig_posts_graph``), else JSON fixtures when fixtures are allowed, else empty."""
    scan_p = processed / "ig_creator_scan.parquet"
    for name, label in (("ig_posts.parquet", "windsor refresh"), ("ig_posts_graph.parquet", "graph api")):
        posts_p = processed / name
        if posts_p.exists():
            return (
                _read_parquet(posts_p, ig.IG_POST_COLS),
                _read_parquet(scan_p, ig.SCAN_COLS),
                f"processed parquet ({label})",
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


def build_influencers(
    klar: pd.DataFrame,
    creators: pd.DataFrame,
    sheet: pd.DataFrame,
    sheet_master: pd.DataFrame,
    attrs: pd.DataFrame,
    manual: pd.DataFrame,
    ig_scan: pd.DataFrame,
    since: dt.date | None,
    until: dt.date | None,
) -> dict[str, Any]:
    """Creator table for a window: Klar summary -> join to the Creators sheet -> Klar-sheet / planning-tab
    enrichment -> CPM with the reach priority. Used by the pipeline and by the Influencers page per period."""
    summary = klar_mod.creator_summary(klar, since=since, until=until)
    join = join_klar_creators(summary, creators)
    matched = join["matched"].copy()
    if not matched.empty and not sheet_master.empty:
        # Influencer/Affiliate Name in the sheet == Klar influencer_name: fill master fields from the sheet
        sm = sheet_master.set_index("handle")
        alias = ks.alias_map(sheet)  # display names ("Carlotta Ferlito") -> handle from the profile link
        matched["handle"] = matched["handle"].map(lambda x: alias.get(x, x) if isinstance(x, str) else x)
        h = matched["handle"]
        for col in ("type_of_partnership", "category"):
            matched[col] = matched[col].where(matched[col].notna(), h.map(sm[col]))
        matched["followers_klar"] = matched["followers_klar"].where(
            matched["followers_klar"].notna(), h.map(sm["followers_sheet"])
        )
        for col in ("markets", "post_types", "n_campaigns", "n_campaigns_with_reach", "link_to_profile"):
            matched[col] = h.map(sm[col])
        matched["in_klar_sheet"] = h.isin(sm.index)
    if not matched.empty and not attrs.empty:
        at = attrs.set_index("handle")
        for col in ("tier", "tier_source", "category_ws", "goal_ws", "followers_ws"):
            matched[col] = matched["handle"].map(at[col])
    if not matched.empty:
        # Klar is the master: its handle fills in where the Creators sheet knows nothing
        matched["creator_handle"] = matched["creator_handle"].where(
            matched["creator_handle"].notna(), matched["handle"]
        )
        matched["creator_platform"] = matched["creator_platform"].where(
            matched["creator_platform"].notna(), matched["platform"]
        )
        matched["creator_followers"] = matched["creator_followers"].where(
            matched["creator_followers"].notna(), matched["followers_klar"]
        )
        matched["creator_deal"] = matched["creator_deal"].where(
            matched["creator_deal"].notna(), matched["type_of_partnership"]
        )
    influencers = ig.influencer_cpm(matched, manual)
    inf_posts = ig.influencer_post_cpm(klar, matched, manual)
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
    return {"summary": summary, "join": join, "influencers": influencers, "posts": inf_posts}


def _group_by_brand(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r.get("_brand") or "unknown"), []).append(r)
    return out


def build_bundle(
    xlsx: Path | str | None = None,
    processed: Path = PROCESSED,
    allow_fixture: bool | None = None,
    manual_reach_csv: Path | str | None = None,
    klar_window_days: int = 800,  # legacy Klar source starts Sep 2025; window on order OR posting date
) -> Bundle:
    """``allow_fixture=None`` (default) permits synthetic Windsor/Klar/Graph fixtures only when the workbook itself
    is the fixture (tests, empty deploy). With a real workbook a missing source stays empty and is reported in
    ``status`` rather than silently showing fixture numbers."""
    cfg = load_config()
    boot = bootstrap()  # SOCIAL_XLSX_B64 / DATA_SNAPSHOT_B64 secrets -> files (cloud deploy, fresh clone)
    path, is_fixture = resolve_xlsx(xlsx)
    res = None
    if is_fixture and not (Path(xlsx) if xlsx else DEFAULT_XLSX).exists():
        res = parse_result_from_parquet(processed)  # no workbook here: use the refresh output (data repo)
        if res is not None:
            is_fixture, path = False, Path(res.source)
    if allow_fixture is None:
        allow_fixture = is_fixture
    if res is None:
        res = parse_workbook(path, cfg)
    weekly_wide, monthly_wide = pivot_wide(res.weekly), pivot_wide(res.monthly)
    inp_note = _pull_if_missing(
        inp.INPUT_DIR, "*.csv", "INPUT_SHEET_CSV_URLS", inp.pull_input_sheet, "input sheet"
    )
    tt_manual = inp.load_tiktok_weekly()
    if not tt_manual.empty:  # team input sheet fills TikTok weeks the report sheet has no block for
        have = set(zip(weekly_wide["account"], weekly_wide["year"], weekly_wide["period"], strict=True))
        extra = tt_manual[
            [
                (a, y, p) not in have
                for a, y, p in zip(tt_manual["account"], tt_manual["year"], tt_manual["period"], strict=True)
            ]
        ]
        weekly_wide = pd.concat([weekly_wide, extra.drop(columns=["source"])], ignore_index=True)
    posts = mx.add_post_metrics(res.posts)
    acc_er = mx.account_er(posts)
    status: dict[str, Any] = {"workbook": f"{path}{' (FIXTURE)' if is_fixture else ''}"}
    if boot:
        status["bootstrap"] = "; ".join(f"{k}: {v}" for k, v in boot.items())

    # --- Windsor (primary for Instagram organic + boosts + creator public counts) ---
    raw, status["windsor"] = load_windsor(allow_fixture)
    wf = windsor_frames(raw, cfg)
    st_manual = inp.load_stories_manual()
    if not st_manual.empty:  # manual story rows for days the API has nothing
        api_days = (
            set(zip(wf["stories"]["account"], wf["stories"]["date"], strict=True))
            if not wf["stories"].empty
            else set()
        )
        extra = st_manual[
            [(a, d) not in api_days for a, d in zip(st_manual["account"], st_manual["date"], strict=True)]
        ]
        wf["stories"] = pd.concat(
            [wf["stories"], extra.drop(columns=["n_stories_manual"])], ignore_index=True
        )
        for ptype, name in (("cw", "api_weekly"), ("month", "api_monthly")):
            org = wf[name].drop(
                columns=[
                    c for c in am.STORY_COLS_PERIOD if c not in am.KEY + ["year", "period_type", "period"]
                ],
                errors="ignore",
            )
            wf[name] = am.combined_periods(org, pd.DataFrame(), am.story_periods(wf["stories"], ptype))
    if not wf["media"].empty:
        ig_posts, status["instagram"] = wf["posts_m"], "windsor instagram connector"
    else:
        ig_raw, _, status["instagram"] = load_ig_graph(processed, allow_fixture)
        ig_posts = ig.ig_post_metrics(ig_raw)
    public_summary = wz.creators_public_summary(wf["public"])
    if not public_summary.empty:
        ig_scan = public_summary.assign(error=None, media_count=pd.NA, fetched_at=pd.NaT)[ig.SCAN_COLS]
    else:
        _, ig_scan, _ = load_ig_graph(processed, allow_fixture)

    # --- Klar: creator master + commercials; the Klar Google Sheets carry the campaign detail ---
    klar, status["klar"] = load_klar(processed, allow_fixture)
    sheet, status["klar_sheet"] = load_klar_sheets(allow_fixture)
    if klar.empty and not sheet.empty:
        # no Klar API cache (fresh clone / cloud without DATA_SNAPSHOT_B64): campaigns, spend and reach from the
        # Klar sheets alone; orders / revenue / ROAS need the API cache
        rows = ks.klar_rows_from_sheet(sheet)
        klar = pd.concat(
            [
                klar_mod.klar_frame(
                    [{k: v for k, v in r.items() if k != "_brand"} for r in rs], brand=b, source="sheet"
                )
                for b, rs in _group_by_brand(rows).items()
            ],
            ignore_index=True,
        )
        status["klar"] = (
            f"sheet-only ({len(klar)} campaigns from the Klar sheets; no API cache -> no orders / revenue / ROAS; "
            "set DATA_SNAPSHOT_B64 or run the Klar pull)"
        )
    n_before = len(klar)
    klar = klar_mod.dedupe_sources(klar, alias=ks.alias_map(sheet))  # legacy rows the sheet source repeats
    if len(klar) < n_before:
        status["klar"] += f" ({n_before - len(klar)} legacy rows superseded by the sheet source)"
    sheet_master = ks.creator_master(sheet)
    ws_dir = (
        ks.SHEETS_DIR
        if ks.SHEETS_DIR.exists()
        else (FIXTURES / "klar_sheets" if allow_fixture else ks.SHEETS_DIR)
    )
    worksheet = ks.load_worksheets(ws_dir)
    attrs = ks.creator_attributes(worksheet, ks.load_library_followers(ws_dir))
    status["klar_worksheet"] = (
        f"{worksheet['brand'].nunique()} workbooks, {len(worksheet)} planning rows, {len(attrs)} creators"
        if not worksheet.empty
        else "none"
    )
    today = dt.date.today()
    manual_p = Path(manual_reach_csv) if manual_reach_csv else ig.MANUAL_REACH_CSV
    if not manual_p.exists() and allow_fixture:
        manual_p = FIXTURES / "influencer_reach.csv"
    manual = ig.load_manual_reach(manual_p)
    # team input sheet (Google): creator reach, manual story rows, TikTok weekly rows
    inp_reach = inp.load_creator_reach()
    status["input_sheet"] = inp_note + (
        f"{inp.INPUT_DIR}: {len(inp_reach)} creator reach rows"
        if inp.INPUT_DIR.exists()
        else "none (INPUT_SHEET_CSV_URLS)"
    )
    # reach priority: Klar API reach -> Klar sheet Reach -> planning tab -> team input sheet -> manual CSV -> n/a
    manual = pd.concat(
        [
            ks.sheet_reach(sheet),
            ks.worksheet_reach(worksheet),
            inp_reach[["handle", "post_url", "date", "reach", "source"]],
            manual,
        ],
        ignore_index=True,
    )
    manual["date"] = pd.to_datetime(manual["date"], errors="coerce")
    manual["reach"] = pd.to_numeric(manual["reach"], errors="coerce")
    inf = build_influencers(
        klar,
        res.creators,
        sheet,
        sheet_master,
        attrs,
        manual,
        ig_scan,
        since=today - dt.timedelta(days=klar_window_days),
        until=today,
    )
    summary, join, influencers, inf_posts = inf["summary"], inf["join"], inf["influencers"], inf["posts"]

    spend_recon = mx.reconcile_boost_spend(monthly_wide, res.boosting_susy, res.susy_budget)
    spend_recon = am.spend_recon_with_meta(
        spend_recon,
        wf["api_monthly"][wf["api_monthly"]["boost_spend"].notna()]
        if not wf["api_monthly"].empty
        else wf["api_monthly"],
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
        spend_recon=spend_recon,
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
        ig_daily=wf["daily"],
        boosted=wf["boosted"],
        api_weekly=wf["api_weekly"],
        api_monthly=wf["api_monthly"],
        creators_public=wf["public"],
        collab_posts=wf["collab"],
        ig_stories=wf["stories"],
        klar_sheet=sheet,
        klar_sheet_master=sheet_master,
        klar_worksheet=worksheet,
        creator_attrs=attrs,
        status=status,
    )


def refresh(
    xlsx: Path | str | None = None, out_dir: Path = PROCESSED, klar_days: int = 400, live: bool = True
) -> dict[str, str]:
    """``make refresh``: pull Windsor (+ Klar / Graph when configured) and write parquet to data/processed."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}
    cfg = load_config()
    boot = bootstrap()  # SOCIAL_XLSX_B64 / DATA_SNAPSHOT_B64 secrets -> files (Actions runner)
    if boot:
        status["bootstrap"] = "; ".join(f"{k}: {v}" for k, v in boot.items())
    path, is_fixture = resolve_xlsx(xlsx)
    res = parse_workbook(path, cfg)
    for name, df in res.frames().items():
        df.to_parquet(out_dir / f"xlsx_{name}.parquet", index=False)
    res.coverage().to_csv(out_dir / "xlsx_block_coverage.csv", index=False)
    status["workbook"] = f"parsed {path} ({len(res.blocks)} blocks){' FIXTURE' if is_fixture else ''}"

    # Windsor
    try:
        if live and os.environ.get("WINDSOR_API_KEY"):
            counts = wz.pull_all(wz.HttpWindsorClient(), wz.RAW_DIR)
            status["windsor_pull"] = str(counts)
        raw, status["windsor"] = load_windsor(allow_fixture=True, live_if_possible=False)
        wf = windsor_frames(raw, cfg)
        for name in ("media", "daily", "boosted", "api_weekly", "api_monthly", "public", "stories", "collab"):
            wf[name].to_parquet(out_dir / f"windsor_{name}.parquet", index=False)
        if not wf["media"].empty:
            wf["posts_m"].to_parquet(out_dir / "ig_posts.parquet", index=False)
        # follower snapshots: Meta exposes today's count only, so keep our own history
        if not wf["daily"].empty:
            snap = wf["daily"].dropna(subset=["followers"])[["account", "date", "followers"]]
            hist_p = out_dir / "ig_followers_history.parquet"
            hist = pd.concat(
                [_read_parquet(hist_p, ["account", "date", "followers"]), snap], ignore_index=True
            )
            hist.drop_duplicates(["account", "date"], keep="last").sort_values(
                ["account", "date"]
            ).to_parquet(hist_p, index=False)
        status["windsor_frames"] = (
            f"media {len(wf['media'])}, daily {len(wf['daily'])}, boosted {len(wf['boosted'])}, public {len(wf['public'])}"
        )
    except Exception as e:  # noqa: BLE001
        status["windsor"] = f"failed: {type(e).__name__}: {e}"

    # Klar influencer Google Sheets and the team input sheet (published CSV links)
    if live and os.environ.get("KLAR_SHEET_CSV_URLS"):
        status["klar_sheets"] = str(ks.pull_klar_sheets())
    if live and os.environ.get("INPUT_SHEET_CSV_URLS"):
        status["input_sheet"] = str(inp.pull_input_sheet())

    # Klar
    try:
        if live and os.environ.get("KLAR_API_KEY"):
            client: klar_mod.KlarClient = klar_mod.HttpKlarClient()
        elif os.environ.get("KLAR_CSV_EXPORT"):
            client = klar_mod.CsvExportKlarClient(os.environ["KLAR_CSV_EXPORT"])
        elif live:
            # no Klar API: keep the per-brand caches (pushed from a Claude session / the data repo) as they are and
            # never write the synthetic fixture next to them
            caches = klar_mod.latest_caches()
            if caches:
                klar_mod.load_caches().to_parquet(out_dir / "klar_influencer.parquet", index=False)
                status["klar"] = f"cache kept: {', '.join(c.name for c in caches)} (no Klar API configured)"
            else:
                status["klar"] = "not configured: no KLAR_API_KEY and no cache in data/raw/klar"
            client = None
        else:
            cache = klar_mod.latest_cache()
            client = klar_mod.FixtureKlarClient(cache or FIXTURES / "klar_influencer_flex.json")
            status["klar_source"] = f"{'cache ' + cache.name if cache else 'FIXTURE'}"
        if client is not None:
            df, raw_p = klar_mod.pull_klar(client, days=klar_days, raw_dir=klar_mod.RAW_DIR)
            df.to_parquet(out_dir / "klar_influencer.parquet", index=False)
            status["klar"] = f"ok: {len(df)} rows -> {raw_p}"
    except NotImplementedError as e:
        status["klar"] = f"not configured: {e}"
    except Exception as e:  # noqa: BLE001
        status["klar"] = f"failed: {type(e).__name__}: {e}"

    # Instagram Graph API (only when a Meta app is configured; Windsor covers the rest)
    ids = ig.account_ids_from_env()
    if live and os.environ.get("META_ACCESS_TOKEN") and ids:
        try:
            src = ig.GraphApiSource()
            posts = ig.pull_own_accounts(src, ids, out_dir / "ig_posts_graph.parquet")
            status["instagram_graph"] = f"ok: {len(posts)} media"
        except Exception as e:  # noqa: BLE001
            status["instagram_graph"] = f"failed: {type(e).__name__}: {e}"

    with open(out_dir / "refresh_status.json", "w", encoding="utf-8") as fh:
        json.dump({"at": dt.datetime.now(dt.UTC).isoformat(), **status}, fh, indent=1)
    return status
