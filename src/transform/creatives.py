"""Paid social creatives: ad-name parsing, funnel stage, asset aggregation, verdicts, tags and tests.

Grain: one row per **asset x funnel stage** (prospecting / retargeting / unknown). An asset is an ad name
(the naming convention identifies the creative; Meta's ``creative_id`` is per ad copy, so one asset running
in two ad sets has two creative ids and they are kept as a list for thumbnails). Ratios are recomputed
from sums, never averaged from daily rows. Instagram post boosts (Organic vs Boosted) and page promotions
are excluded from the asset model; page promotions are kept in the raw frame tagged ``boost_page_promo``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.transform.metrics import _safe_div

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "creatives.yaml"
STAGES = ["prospecting", "retargeting", "unknown"]
GOAL_ORDER = [
    "conversion",
    "value",
    "auto",
    "landing_page_view",
    "link_clicks",
    "leads",
    "thruplay",
    "reach",
    "impressions",
    "engagement",
]
TAG_DIMS = ("visual_subject", "claim", "offer")
TAG_VOCAB: dict[str, list[str]] = {
    "visual_subject": [
        "product_only",
        "hand",
        "person",
        "lifestyle",
        "infographic",
        "ugc_creator",
        "catalogue",
    ],
    "claim": [
        "vegan",
        "lab_tested",
        "formula_education",
        "comparison",
        "reviews_social_proof",
        "seasonal",
        "offer",
        "brand_trust",
    ],
    "offer": ["none", "discount_pct", "free_gift", "voucher", "gwp"],
}
FORMATS = ["static", "carousel", "video", "dynamic_catalogue", "unknown"]
# KPI -> higher is better
KPI_BETTER_HIGH = {
    "roas": True,
    "ctr_link": True,
    "cpa": False,
    "cpc": False,
    "cpm": False,
    "hook_rate": True,
}
ASSET_KEY = ["asset_id", "funnel_stage", "goal"]
KLAR_SUM = ["klar_cost", "klar_orders", "klar_new_customers", "klar_net_revenue", "klar_gross_revenue"]
SUM_COLS = [
    *KLAR_SUM,
    "spend",
    "impressions",
    "reach",
    "clicks",
    "link_clicks",
    "lpv",
    "outbound_clicks",
    "purchases",
    "purchase_value",
    "video_plays",
    "thruplays",
]
TEXT_FIRST = [  # carried with "first" in the aggregation (klar_matched is aggregated with "any", separately)
    "ad_name",
    "brand",
    "market",
    "format",
    "product",
    "concept",
    "style",
    "version",
    "launch_month",
    "variant",
    "parsed",
    "asset_type",
    "body",
    "title",
]


@lru_cache(maxsize=1)
def load_creatives_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------------------
# ad names
# --------------------------------------------------------------------------------------
_YYYYMM = re.compile(r"^(20\d{2})(0[1-9]|1[0-2])$")
_VERSION = re.compile(r"^[vV]\d{1,3}$")
_WS = re.compile(r"\s+")


def _norm_token(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def parse_ad_name(name: object, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """``[Prefix_]MARKET_FORMAT_PRODUCT_CONCEPT_STYLE_VERSION_YYYYMM[_SUFFIX]`` -> fields.

    Tolerates a missing version / month and ``– Copy 2`` style suffixes. ``parsed`` is False when the
    market+format anchor is not found (the row is kept with everything NaN and listed in Data quality).
    """
    cfg = cfg or load_creatives_config()
    nm = cfg["naming"]
    out: dict[str, Any] = {
        "market": None,
        "format": "unknown",
        "product": None,
        "product_token": None,
        "concept": None,
        "style": None,
        "version": None,
        "launch_month": None,
        "variant": None,
        "parsed": False,
    }
    if name is None or (isinstance(name, float) and name != name):
        return out
    s = _WS.sub(" ", str(name)).strip()
    variant: list[str] = []
    m = re.search(r"\s[–-]\s*(Copy(?:\s*\d+)?)$", s)  # "… – Copy 2"
    if m:
        variant.append(m.group(1))
        s = s[: m.start()]
    tokens = [t for t in s.split("_") if t != ""]
    # anchor: first token that is a market code, followed by a known format
    fmt_map = {k.lower(): v for k, v in nm["formats"].items()}
    markets = {m.upper() for m in nm["markets"]}
    anchor = None
    for i, t in enumerate(tokens[:-1]):
        if t.upper() in markets and tokens[i + 1].lower() in fmt_map:
            anchor = i
            break
    if anchor is None:
        out["variant"] = ", ".join(variant) or None
        return out
    prefix = tokens[:anchor]
    if prefix:
        variant = ["_".join(prefix), *variant]
    core = tokens[anchor:]
    out["market"] = core[0].upper()
    out["format"] = fmt_map[core[1].lower()]
    rest = core[2:]
    # trailing suffixes (LP / PDP / …) and the YYYYMM + version tokens, read from the end
    suffixes = {str(x).lower() for x in nm.get("suffixes", [])}
    while rest and rest[-1].lower() in suffixes:
        variant.append(rest.pop())
    if rest and _YYYYMM.match(rest[-1]):
        ym = rest.pop()
        out["launch_month"] = f"{ym[:4]}-{ym[4:]}"
    while rest and rest[-1].lower() in suffixes:
        variant.append(rest.pop())
    if rest and _VERSION.match(rest[-1]):
        out["version"] = rest.pop().upper()
    if rest:
        out["product_token"] = rest[0]
        out["product"] = cfg["products"].get(_norm_token(rest[0]), rest[0])
    if len(rest) >= 2:
        out["concept"] = rest[1]
    if len(rest) >= 3:
        out["style"] = "_".join(rest[2:])
    out["variant"] = ", ".join(variant) or None
    out["parsed"] = True
    return out


def is_page_promo(campaign: object, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_creatives_config()
    s = str(campaign or "")
    return any(re.search(p, s) for p in cfg.get("page_promo_patterns", []))


# --------------------------------------------------------------------------------------
# funnel stage
# --------------------------------------------------------------------------------------
def _targeting_has_custom_audiences(targeting: object) -> bool | None:
    """True when the ad set targets a custom audience (website visitors, purchasers …), False when the
    targeting JSON is readable and has none, None when unreadable."""
    if targeting is None or (isinstance(targeting, float) and targeting != targeting):
        return None
    try:
        t = json.loads(str(targeting)) if not isinstance(targeting, dict) else targeting
    except (ValueError, TypeError):
        return None
    if not isinstance(t, dict):
        return None
    ca = t.get("custom_audiences") or []
    if ca:
        return True
    flex = t.get("flexible_spec") or []
    for spec in flex if isinstance(flex, list) else []:
        if isinstance(spec, dict) and spec.get("custom_audiences"):
            return True
    return False


def funnel_stage(
    campaign: object, adset_name: object, targeting: object, rules: list[dict[str, Any]] | None = None
) -> str:
    rules = rules if rules is not None else load_creatives_config()["funnel_stage_rules"]
    c, a = str(campaign or "").lower(), str(adset_name or "").lower()
    has_ca = _targeting_has_custom_audiences(targeting)
    for r in rules:
        f = r.get("field")
        if f in ("campaign", "adset_name"):
            needle = str(r.get("contains", "")).lower()
            if needle and needle in (c if f == "campaign" else a):
                return r["stage"]
        elif f == "targeting" and has_ca is not None and has_ca == bool(r.get("has_custom_audiences")):
            return r["stage"]
    return "unknown"


# --------------------------------------------------------------------------------------
# tags from the naming convention
# --------------------------------------------------------------------------------------
def tags_from_name(
    parsed: dict[str, Any], ad_name: object, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Controlled-vocabulary tags from the naming tokens. The variant (``Test-Hand`` …) is checked first, then
    concept + style; within a haystack the longest synonym wins. Offer synonyms also scan the full ad name."""
    cfg = cfg or load_creatives_config()
    hays = [
        _norm_token(str(parsed.get("variant") or "")),
        _norm_token(" ".join(str(parsed.get(k) or "") for k in ("concept", "style"))),
    ]
    full = _norm_token(str(ad_name or ""))
    out: dict[str, Any] = {d: None for d in TAG_DIMS}
    for dim in TAG_DIMS:
        syn = cfg["tags"].get(dim, {})
        keys = sorted(syn, key=len, reverse=True)
        for hay in [*hays, full] if dim == "offer" else hays:
            hit = next((k for k in keys if k in hay), None)
            if hit:
                out[dim] = syn[hit]
                break
    fmt = parsed.get("format")
    if out["visual_subject"] is None and fmt == "dynamic_catalogue":
        out["visual_subject"] = "catalogue"
    if out["offer"] is None:
        out["offer"] = "none"
    if out["claim"] is None and out["offer"] != "none":
        out["claim"] = "offer"
    return out


# --------------------------------------------------------------------------------------
# enrich the ad x day x ad set frame
# --------------------------------------------------------------------------------------
ENRICHED_COLS = [
    "asset_id",
    "funnel_stage",
    "goal",
    "market",
    "format",
    "product",
    "concept",
    "style",
    "version",
    "launch_month",
    "variant",
    "parsed",
    "asset_type",
    "visual_subject_name",
    "claim_name",
    "offer_name",
]


def enrich_ads(ads: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Add asset identity, parsed naming fields, funnel stage, goal label and naming tags to every row.

    Dropped as not-paid-creative (see ``excluded_spend`` for the totals): Instagram post boosts (``is_boost``),
    page / post promotions (``page_promo_patterns``), organic-style optimisation goals
    (``exclude_optimization_goals``) and markets outside ``markets``.
    """
    cfg = cfg or load_creatives_config()
    if ads.empty:
        return pd.DataFrame(columns=[*ads.columns, *ENRICHED_COLS])
    a = ads[~_excluded_mask(ads, cfg)].copy()
    if a.empty:
        return pd.DataFrame(columns=[*ads.columns, *ENRICHED_COLS])
    a["asset_id"] = a["ad_name"].map(lambda x: _WS.sub(" ", str(x)).strip())
    names = a.drop_duplicates("asset_id")[["asset_id", "campaign"]]
    parsed = {aid: parse_ad_name(aid, cfg) for aid in names["asset_id"]}
    for col in (
        "market",
        "format",
        "product",
        "concept",
        "style",
        "version",
        "launch_month",
        "variant",
        "parsed",
    ):
        a[col] = a["asset_id"].map(lambda x, c=col: parsed[x][c])
    a["asset_type"] = a["format"].astype(object)
    markets = {str(m).upper() for m in cfg.get("markets", [])}
    if markets:
        a = a[a["market"].isna() | a["market"].isin(markets)].copy()
    if a.empty:
        return pd.DataFrame(columns=[*ads.columns, *ENRICHED_COLS])
    tags = {aid: tags_from_name(parsed[aid], aid, cfg) for aid in names["asset_id"]}
    for dim in TAG_DIMS:
        a[f"{dim}_name"] = a["asset_id"].map(lambda x, d=dim: tags[x][d])
    rules = cfg["funnel_stage_rules"]
    keys = a.drop_duplicates(["campaign", "adset_name"])[["campaign", "adset_name", "targeting"]]
    stage = {
        (c, s): funnel_stage(c, s, t, rules)
        for c, s, t in zip(keys["campaign"], keys["adset_name"], keys["targeting"], strict=True)
    }
    a["funnel_stage"] = [stage[(c, s)] for c, s in zip(a["campaign"], a["adset_name"], strict=True)]
    goals = cfg.get("optimization_goals", {})
    a["goal"] = a["optimization_goal"].map(
        lambda g: goals.get(str(g), str(g).lower() if pd.notna(g) else "unknown")
    )
    return a


def _excluded_mask(ads: pd.DataFrame, cfg: dict[str, Any]) -> pd.Series:
    excl_goals = {str(g) for g in cfg.get("exclude_optimization_goals", [])}
    m = ads["is_boost"].astype(bool)
    m |= ads["campaign"].map(lambda c: is_page_promo(c, cfg)).astype(bool)
    m |= ads["optimization_goal"].astype(str).isin(excl_goals)
    return m


def excluded_spend(ads: pd.DataFrame, cfg: dict[str, Any] | None = None) -> dict[str, float]:
    """Spend dropped from the asset model, by reason (for the status line and Data quality)."""
    cfg = cfg or load_creatives_config()
    if ads.empty:
        return {}
    excl_goals = {str(g) for g in cfg.get("exclude_optimization_goals", [])}
    boost = ads["is_boost"].astype(bool)
    promo = ads["campaign"].map(lambda c: is_page_promo(c, cfg)).astype(bool) & ~boost
    organic = ads["optimization_goal"].astype(str).isin(excl_goals) & ~boost & ~promo
    markets = {str(m).upper() for m in cfg.get("markets", [])}
    rest = ads[~(boost | promo | organic)]
    mk = rest["ad_name"].map(lambda x: parse_ad_name(x, cfg)["market"])
    other = rest[mk.notna() & ~mk.isin(markets)] if markets else rest.iloc[0:0]
    out = {
        "instagram_post_boosts": float(ads.loc[boost, "spend"].sum()),
        "page_promotions": float(ads.loc[promo, "spend"].sum()),
        "organic_objectives": float(ads.loc[organic, "spend"].sum()),
        "other_markets": float(other["spend"].sum()),
    }
    return {k: v for k, v in out.items() if v > 0}


# --------------------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------------------
RATIO_COLS = [
    "ctr_link",
    "cpc",
    "cpm",
    "cpa_meta",
    "roas_meta",
    "roas_klar",
    "cpa_klar",
    "cac_klar",
    "roas",
    "cpa",
    "orders",
    "lpv_rate",
    "cvr",
    "thruplay_rate",
    "frequency",
    "hook_rate",
]


def ensure_klar_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Frames that never went through ``klar_marketing.allocate_to_ads`` get the Klar sums (NaN) and
    ``klar_matched`` (False), so every aggregator can rely on them."""
    d = df.copy()
    for c in KLAR_SUM:
        if c not in d.columns:
            d[c] = np.nan
    if "klar_matched" not in d.columns:
        d["klar_matched"] = False
    return d


def add_ratios(df: pd.DataFrame, roas_source: str = "klar") -> pd.DataFrame:
    """Ratios from sums, all as plain ``float64`` (never nullable ``Float64`` / ``pd.NA``, which breaks
    comparisons and ``astype(float)`` downstream). ``roas`` / ``cpa`` / ``orders`` follow ``roas_source``:
    Klar (gross revenue, orders) when the row has Klar-matched spend, else Meta (7d click / 1d view);
    ``roas_source`` says which per row."""
    d = ensure_klar_cols(df)
    for c in [*SUM_COLS, "hook_rate"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype("float64")
    d["ctr_link"] = _safe_div(d["link_clicks"], d["impressions"])
    d["cpc"] = _safe_div(d["spend"], d["link_clicks"])
    d["cpm"] = _safe_div(d["spend"], d["impressions"]) * 1000
    d["cpa_meta"] = _safe_div(d["spend"], d["purchases"])
    d["roas_meta"] = _safe_div(d["purchase_value"], d["spend"])
    has_klar = d["klar_cost"].fillna(0) > 0
    d["roas_klar"] = _safe_div(d["klar_gross_revenue"], d["spend"]).where(has_klar)
    d["cpa_klar"] = _safe_div(d["spend"], d["klar_orders"]).where(has_klar)
    d["cac_klar"] = _safe_div(d["spend"], d["klar_new_customers"]).where(has_klar)
    use_klar = has_klar & (roas_source == "klar")
    d["roas_source"] = np.where(use_klar, "klar", "meta")
    d["roas"] = d["roas_klar"].where(use_klar, d["roas_meta"])
    d["cpa"] = d["cpa_klar"].where(use_klar, d["cpa_meta"])
    d["orders"] = d["klar_orders"].where(use_klar, d["purchases"])
    d["lpv_rate"] = _safe_div(d["lpv"], d["link_clicks"])
    d["cvr"] = _safe_div(d["purchases"], d["lpv"])
    d["thruplay_rate"] = _safe_div(d["thruplays"], d["video_plays"])
    d["frequency"] = _safe_div(d["impressions"], d["reach"])
    for c in RATIO_COLS:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype("float64")
    return d


def _weighted_hook(g: pd.DataFrame) -> float:
    w = g["video_plays"].fillna(0)
    s3 = g["play_curve_s3"]
    ok = s3.notna() & (w > 0)
    if not ok.any():
        return np.nan
    return float((s3[ok] * w[ok]).sum() / w[ok].sum())


def aggregate_assets(
    enriched: pd.DataFrame,
    start: dt.date | None = None,
    end: dt.date | None = None,
    by: list[str] | None = None,
    roas_source: str = "klar",
) -> pd.DataFrame:
    """Sum the daily rows per asset x funnel stage x optimisation goal (default ``by``) inside [start, end] and
    recompute ratios. ``goal`` is the primary axis inside a stage view; ``by=["asset_id"]`` gives one row per asset."""
    by = by or ASSET_KEY
    cols = [
        *by,
        *[c for c in TEXT_FIRST if c not in by],
        "goal_mix",
        "n_adsets",
        "adsets",
        "creative_ids",
        "thumbnail_url",
        "image_url",
        "ads_manager_url",
        "first_day",
        "last_day",
        "active",
        *SUM_COLS,
        "klar_matched",
        "hook_rate",
        "ctr_link",
        "cpc",
        "cpm",
        "cpa",
        "roas",
        "orders",
        "roas_source",
        "roas_meta",
        "cpa_meta",
        "roas_klar",
        "cpa_klar",
        "cac_klar",
        "lpv_rate",
        "cvr",
        "thruplay_rate",
        "frequency",
        "visual_subject_name",
        "claim_name",
        "offer_name",
    ]
    if enriched.empty:
        return pd.DataFrame(columns=cols)
    e = enriched
    if start is not None:
        e = e[e["date"] >= start]
    if end is not None:
        e = e[e["date"] <= end]
    if e.empty:
        return pd.DataFrame(columns=cols)
    e = ensure_klar_cols(e)
    e["spend_f"] = e["spend"].fillna(0)
    g = e.groupby(by, dropna=False)
    agg: dict[str, Any] = {c: (c, lambda x: x.sum(min_count=1)) for c in KLAR_SUM}
    agg.update({c: (c, "sum") for c in SUM_COLS if c not in KLAR_SUM})
    agg.update({c: (c, "first") for c in TEXT_FIRST if c not in by})
    agg["klar_matched"] = ("klar_matched", "any")
    agg.update({c: (c, "first") for c in ("visual_subject_name", "claim_name", "offer_name")})
    out = g.agg(
        **agg,
        n_adsets=("adset_name", "nunique"),
        adsets=("adset_name", lambda s: " | ".join(sorted(set(map(str, s.dropna()))))),
        creative_ids=("creative_id", lambda s: ", ".join(sorted(set(map(str, s.dropna()))))),
        thumbnail_url=("thumbnail_url", lambda s: next((x for x in s.dropna() if str(x)), None)),
        image_url=("image_url", lambda s: next((x for x in s.dropna() if str(x)), None)),
        ads_manager_url=("ads_manager_url", lambda s: next((x for x in s.dropna() if str(x)), None)),
        first_day=("date", "min"),
        last_day=("date", "max"),
    ).reset_index()
    # spend share per optimisation goal (for judge_kpi) and the hook rate (plays-weighted)
    mix_by = [*by, *([] if "goal" in by else ["goal"])]
    mix = e.groupby(mix_by, dropna=False)["spend_f"].sum().reset_index()
    mix["goal_"] = mix["goal"]
    tot = mix.groupby(by, dropna=False)["spend_f"].transform("sum")
    mix["share"] = np.where(tot > 0, mix["spend_f"] / tot.replace(0, np.nan), 0.0)
    mix_s = mix.groupby(by, dropna=False).apply(
        lambda d: "; ".join(f"{g} {s:.0%}" for g, s in zip(d["goal_"], d["share"], strict=True) if s > 0),
        include_groups=False,
    )
    mix_s.name = "goal_mix"
    out = out.merge(mix_s.reset_index(), on=by, how="left")
    conv = mix[mix["goal_"].isin(["conversion", "value"])].groupby(by, dropna=False)["share"].sum()
    conv.name = "conv_share"
    out = out.merge(conv.reset_index(), on=by, how="left")
    out["conv_share"] = out["conv_share"].fillna(0.0)
    hook = g.apply(_weighted_hook, include_groups=False)
    hook.name = "hook_rate"
    out = out.merge(hook.reset_index(), on=by, how="left")
    out["active"] = out["last_day"] >= (e["date"].max() - dt.timedelta(days=3))
    out = add_ratios(out, roas_source)
    return out[[*cols, "conv_share"]].sort_values("spend", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# tags: naming -> LLM -> manual
# --------------------------------------------------------------------------------------
def merge_tags(
    assets: pd.DataFrame, llm_tags: pd.DataFrame | None = None, manual_tags: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Final ``visual_subject / claim / offer / hook`` per asset with ``tag_source`` (manual > llm > naming)."""
    a = assets.copy()
    for dim in TAG_DIMS:
        a[dim] = a[f"{dim}_name"]
    a["hook"] = None
    a["tag_source"] = np.where(a[["visual_subject_name", "claim_name"]].notna().any(axis=1), "naming", "none")
    for src, frame in (("llm", llm_tags), ("manual", manual_tags)):
        if frame is None or frame.empty or "asset_id" not in frame.columns:
            continue
        f = frame.drop_duplicates("asset_id", keep="last").set_index("asset_id")
        hit = a["asset_id"].isin(f.index)
        for dim in (*TAG_DIMS, "hook"):
            if dim not in f.columns:
                continue
            vals = a.loc[hit, "asset_id"].map(f[dim])
            ok = vals.notna() & vals.astype(str).str.strip().ne("")
            a.loc[vals[ok].index, dim] = vals[ok]
            if ok.any():
                a.loc[vals[ok].index, "tag_source"] = src
    return a


# --------------------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------------------
def judge_and_verdict(
    assets: pd.DataFrame, cfg: dict[str, Any] | None = None, targets: dict[str, float] | None = None
) -> pd.DataFrame:
    """``judge_kpi`` from the row's optimisation goal (``kpi_by_goal``; ROAS for conversion / value, CTR for
    traffic / leads …), ``target``, ``kpi_value`` and ``verdict`` (Performing / Underperforming / Low data).
    Targets default to the spend-weighted average of the frame (account average of the selection); ROAS / CPA
    follow the frame's ``roas`` (Klar when matched, Meta otherwise). A KPI in ``kpi_by_goal`` that has no
    target (not in ``KPI_BETTER_HIGH``) is logged and replaced by ``default_kpi``."""
    cfg = cfg or load_creatives_config()
    t = cfg["targets"]
    min_spend = float(t.get("min_spend_for_verdict", 100))
    a = assets.copy()
    if a.empty:
        a["judge_kpi"] = pd.Series(dtype=object)
        a["target"] = pd.Series(dtype="float64")
        a["kpi_value"] = pd.Series(dtype="float64")
        a["verdict"] = pd.Series(dtype=object)
        a.attrs["targets"] = {}
        a.attrs["min_spend"] = min_spend
        return a

    def _div(n: float, d: float) -> float:
        return float(n) / float(d) if d and d > 0 else np.nan

    spend = a["spend"].fillna(0)
    klar = a["roas_source"].eq("klar")
    rev = np.where(klar, a["klar_gross_revenue"].fillna(0), a["purchase_value"].fillna(0))
    orders = np.where(klar, a["klar_orders"].fillna(0), a["purchases"].fillna(0))
    impressions, clicks = a["impressions"].fillna(0).sum(), a["link_clicks"].fillna(0).sum()
    avg = {
        "roas": _div(rev.sum(), spend.sum()),
        "ctr_link": _div(clicks, impressions),
        "cpa": _div(spend.sum(), orders.sum()),
        "cpm": _div(spend.sum(), impressions) * 1000,
        "cpc": _div(spend.sum(), clicks),
        "hook_rate": float(a["hook_rate"].mean()) if a["hook_rate"].notna().any() else np.nan,
    }
    assert set(avg) == set(KPI_BETTER_HIGH)  # every judgeable KPI has a target and a direction
    tg = {k: (targets or {}).get(k, t.get(k)) for k in avg}
    tg = {k: (avg[k] if v in (None, "account_average") else float(v)) for k, v in tg.items()}
    kmap = cfg.get("kpi_by_goal", {})
    default = cfg.get("default_kpi", "roas")
    if default not in tg:
        log.warning("default_kpi %r has no target; using roas", default)
        default = "roas"
    unknown = sorted({str(v) for v in kmap.values() if str(v) not in tg})
    if unknown:
        log.warning("kpi_by_goal names KPIs without a target %s; judging those goals on %s", unknown, default)
    kmap = {g: (str(k) if str(k) in tg else default) for g, k in kmap.items()}
    if "goal" in a.columns:
        a["judge_kpi"] = a["goal"].map(lambda g: kmap.get(str(g), default))
    else:
        a["judge_kpi"] = np.where(a["conv_share"] >= 0.5, "roas", "ctr_link")
    a["target"] = a["judge_kpi"].map(tg).astype("float64")
    # vectorised pick of the judged KPI per row: one column per KPI, index by the row's judge_kpi
    kpis = list(tg)
    mat = np.column_stack(
        [
            pd.to_numeric(a[k], errors="coerce").astype("float64").to_numpy()
            if k in a.columns
            else np.full(len(a), np.nan)
            for k in kpis
        ]
    )
    idx = a["judge_kpi"].map({k: i for i, k in enumerate(kpis)}).to_numpy(dtype=int)
    kv = mat[np.arange(len(a)), idx]
    a["kpi_value"] = kv
    tv = a["target"].to_numpy(dtype=float)
    high = a["judge_kpi"].map(KPI_BETTER_HIGH).to_numpy(dtype=bool)
    no_data = np.isnan(kv) | np.isnan(tv)
    with np.errstate(invalid="ignore"):
        better = np.where(high, kv >= tv, kv <= tv)
    a["verdict"] = np.select(
        [a["spend"].fillna(0).to_numpy(dtype=float) < min_spend, no_data, better],
        ["Low data", "Low data", "Performing"],
        default="Underperforming",
    )
    a.attrs["targets"] = tg
    a.attrs["min_spend"] = min_spend
    return a


# --------------------------------------------------------------------------------------
# matrices (what works for which goal)
# --------------------------------------------------------------------------------------
def kpi_matrix(
    assets: pd.DataFrame, row_dim: str, kpi: str, col_dim: str = "goal", roas_source: str = "klar"
) -> pd.DataFrame:
    """Rows = tag / product, columns = optimisation goal (or funnel stage); cell = KPI recomputed from sums plus
    spend and n. Untagged rows are grouped as ``untagged``."""
    if assets.empty:
        return pd.DataFrame(columns=[row_dim, col_dim, "spend", "n_assets", kpi])
    a = ensure_klar_cols(assets)
    a[row_dim] = a[row_dim].fillna("untagged")
    agg: dict[str, Any] = {c: (c, lambda x: x.sum(min_count=1)) for c in KLAR_SUM}
    agg.update({c: (c, "sum") for c in SUM_COLS if c not in KLAR_SUM})
    g = a.groupby([row_dim, col_dim], dropna=False).agg(**agg, n_assets=("asset_id", "nunique")).reset_index()
    hook = a.groupby([row_dim, col_dim], dropna=False).apply(
        lambda d: (
            float((d["hook_rate"] * d["video_plays"]).sum() / d["video_plays"].sum())
            if d["video_plays"].fillna(0).sum() > 0 and d["hook_rate"].notna().any()
            else np.nan
        ),
        include_groups=False,
    )
    hook.name = "hook_rate"
    g = g.merge(hook.reset_index(), on=[row_dim, col_dim], how="left")
    g = add_ratios(g, roas_source)
    return (
        g[[row_dim, col_dim, "spend", "n_assets", kpi]].sort_values([row_dim, col_dim]).reset_index(drop=True)
    )


# --------------------------------------------------------------------------------------
# tests (team input sheet `tests` tab)
# --------------------------------------------------------------------------------------
TEST_COLS = [
    "test_id",
    "test_name",
    "variable",
    "hypothesis",
    "variant",
    "asset_id",
    "primary_kpi",
    "spend",
    "ctr_link",
    "cpa",
    "roas",
    "purchases",
    "kpi_value",
    "rank",
    "result",
    "learning",
]


def tests_table(
    tests: pd.DataFrame, assets_all_stages: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Join each test variant to its asset (all stages summed) and rank the variants on the primary KPI.
    Winner only when spend >= min and the lead over the runner-up is >= ``test_winner_lead``."""
    cfg = cfg or load_creatives_config()
    if tests is None or tests.empty:
        return pd.DataFrame(columns=TEST_COLS)
    t = tests.copy()
    a = assets_all_stages.set_index("asset_id") if not assets_all_stages.empty else pd.DataFrame()
    for c in ("spend", "ctr_link", "cpa", "roas", "purchases"):
        t[c] = t["asset_id"].map(a[c]) if c in a.columns else np.nan
    t["primary_kpi"] = t["primary_kpi"].fillna("roas").str.strip().str.lower().replace({"ctr": "ctr_link"})
    t["kpi_value"] = pd.to_numeric(
        pd.Series(
            [
                (a.at[aid, k] if (aid in a.index and k in a.columns) else np.nan)
                for aid, k in zip(t["asset_id"], t["primary_kpi"], strict=True)
            ],
            index=t.index,
            dtype=object,
        ),
        errors="coerce",
    ).astype("float64")
    min_spend = float(cfg["targets"].get("min_spend_for_verdict", 100))
    lead = float(cfg["targets"].get("test_winner_lead", 0.1))
    t["rank"] = np.nan
    t["result"] = "n/a"
    for _, idx in t.groupby("test_id").groups.items():
        grp = t.loc[idx]
        kpi = str(grp["primary_kpi"].iloc[0])
        high = KPI_BETTER_HIGH.get(kpi, True)
        vals = grp["kpi_value"].astype(float)
        order = vals.rank(ascending=not high, method="min")
        t.loc[idx, "rank"] = order
        valid = vals.dropna()
        if valid.empty:
            t.loc[idx, "result"] = "No data"
            continue
        srt = valid.sort_values(ascending=not high)
        best, second = srt.iloc[0], (srt.iloc[1] if len(srt) > 1 else np.nan)
        enough = grp["spend"].fillna(0) >= min_spend
        if pd.isna(second):
            margin = np.inf
        elif high:
            margin = (best - second) / second if second else np.inf
        else:
            margin = (second - best) / best if best else np.inf
        for i in idx:
            r = t.at[i, "rank"]
            if pd.isna(t.at[i, "kpi_value"]):
                t.at[i, "result"] = "No data"
            elif r == 1 and margin >= lead and enough.at[i] and (len(srt) == 1 or enough.loc[srt.index[1]]):
                t.at[i, "result"] = "Winner"
            elif r == 1 and margin >= lead:
                t.at[i, "result"] = "Leading (low data)"
            elif r == 1 or margin < lead:
                t.at[i, "result"] = "Tie"
            else:
                t.at[i, "result"] = "Lost" if enough.at[i] else "Trailing (low data)"
    for c in TEST_COLS:
        if c not in t.columns:
            t[c] = None
    return t[TEST_COLS].sort_values(["test_id", "rank"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# data quality
# --------------------------------------------------------------------------------------
def creative_issues(
    enriched: pd.DataFrame, assets: pd.DataFrame, thumbs_dir: Path | str | None = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if enriched.empty:
        return out
    un = enriched[~enriched["parsed"].astype(bool)]
    for aid, s in un.groupby("asset_id")["spend"].sum().sort_values(ascending=False).items():
        out.append(
            {
                "source": "creatives",
                "severity": "warn",
                "where": aid,
                "message": f"ad name not in the naming convention (€{s:,.0f} spend): product / concept / tags unknown",
            }
        )
    unk = enriched[enriched["funnel_stage"].eq("unknown")]
    for (c, a), s in unk.groupby(["campaign", "adset_name"])["spend"].sum().items():
        out.append(
            {
                "source": "creatives",
                "severity": "warn",
                "where": f"{c} / {a}",
                "message": f"funnel stage unknown (€{s:,.0f}): add a rule to config/creatives.yaml",
            }
        )
    if not assets.empty:
        if thumbs_dir is not None:
            d = Path(thumbs_dir)
            missing = [
                aid
                for aid, cids in zip(assets["asset_id"], assets["creative_ids"], strict=True)
                if not any((d / f"{c.strip()}.jpg").exists() for c in str(cids or "").split(",") if c.strip())
            ]
            if missing:
                out.append(
                    {
                        "source": "creatives",
                        "severity": "info",
                        "where": f"{len(set(missing))} assets",
                        "message": "no cached thumbnail (run `make refresh` with network access)",
                    }
                )
        if "klar_matched" in enriched.columns:
            nk = enriched[~enriched["klar_matched"].astype(bool)]["spend"].sum()
            tot = enriched["spend"].sum()
            if tot and nk / tot > 0.05:
                out.append(
                    {
                        "source": "creatives",
                        "severity": "warn",
                        "where": f"€{nk:,.0f} of €{tot:,.0f} spend",
                        "message": "no Klar attribution row for this spend (ROAS falls back to Meta 7d click / 1d view); drop a marketing_flex export into data/raw/klar_marketing",
                    }
                )
        if "tag_source" in assets.columns:
            nt = assets[assets["tag_source"].eq("none")]
            if not nt.empty:
                out.append(
                    {
                        "source": "creatives",
                        "severity": "info",
                        "where": f"{nt['asset_id'].nunique()} assets",
                        "message": "no creative tags (naming tokens unknown, no LLM / manual tag)",
                    }
                )
    return out


def reconcile_ads_manager(enriched: pd.DataFrame, export_csv: Path | str) -> pd.DataFrame:
    """Spend per ad name in the feed vs an Ads Manager export dropped at ``data/manual/meta_ads_export.csv``
    (columns ``Ad name`` and ``Amount spent (EUR)``; any date range, compared on the overlapping days when
    the export has ``Reporting starts`` / ``Reporting ends``)."""
    p = Path(export_csv)
    cols = ["ad_name", "spend_feed", "spend_export", "delta"]
    if not p.exists() or enriched.empty:
        return pd.DataFrame(columns=cols)
    x = pd.read_csv(p)
    x.columns = [c.strip() for c in x.columns]
    name_col = next((c for c in x.columns if c.lower() in ("ad name", "ad_name")), None)
    spend_col = next((c for c in x.columns if c.lower().startswith("amount spent")), None)
    if not name_col or not spend_col:
        return pd.DataFrame(columns=cols)
    e = enriched
    if "Reporting starts" in x.columns and "Reporting ends" in x.columns:
        s = pd.to_datetime(x["Reporting starts"], errors="coerce").min()
        t = pd.to_datetime(x["Reporting ends"], errors="coerce").max()
        if pd.notna(s) and pd.notna(t):
            e = e[(pd.to_datetime(e["date"]) >= s) & (pd.to_datetime(e["date"]) <= t)]
    feed = e.groupby("asset_id")["spend"].sum().rename("spend_feed")
    exp = (
        x.assign(
            ad_name=x[name_col].astype(str).str.strip(), spend=pd.to_numeric(x[spend_col], errors="coerce")
        )
        .groupby("ad_name")["spend"]
        .sum()
        .rename("spend_export")
    )
    out = pd.concat([feed, exp], axis=1).fillna(0).reset_index().rename(columns={"index": "ad_name"})
    out["delta"] = out["spend_feed"] - out["spend_export"]
    return out[cols].sort_values("delta", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
