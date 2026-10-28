"""LLM vision pass over creatives: thumbnail + body + title -> controlled-vocabulary tags and a hook line.

Runs once per asset (``make refresh`` with ``ANTHROPIC_API_KEY`` set), results are stored in
``data/processed/creative_tags.parquet`` and never recomputed for an asset that already has a row
(``--retag`` on the CLI clears it). Values outside the vocabulary are dropped, so the page only ever
shows tags the filters know. Manual tags from the team input sheet always win over these.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from src.transform.creatives import TAG_DIMS, TAG_VOCAB

log = logging.getLogger(__name__)

TAGS_PARQUET = Path(os.environ.get("CREATIVE_TAGS_PARQUET", "data/processed/creative_tags.parquet"))
MODEL = os.environ.get("CREATIVE_TAGGING_MODEL", "claude-opus-5-5")
TAG_COLS = ["asset_id", "creative_id", *TAG_DIMS, "hook", "rationale", "model", "tagged_at"]
SYSTEM = (
    "You classify paid-social creatives for a vegan supplements brand (Vegavero). Return only values from "
    "the given vocabulary. visual_subject: what dominates the image (product_only = pack shot / product "
    "card with text, hand = a hand holding the product, person = a visible person or face, lifestyle = scene "
    "without a dominant person, infographic = chart / diagram / comparison table, ugc_creator = creator "
    "video still or selfie style, catalogue = dynamic product grid). claim: the main message hook "
    "(vegan / plant-based source, lab_tested / quality proof, formula_education / ingredient & dosage facts, "
    "comparison vs others, reviews_social_proof, seasonal, offer / discount / gift, brand_trust). offer: "
    "the incentive shown (none, discount_pct, free_gift, voucher, gwp = gift with purchase). hook: the "
    "attention hook a viewer sees first, max 8 words, in English."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "visual_subject": {"type": "string", "enum": TAG_VOCAB["visual_subject"]},
        "claim": {"type": "string", "enum": TAG_VOCAB["claim"]},
        "offer": {"type": "string", "enum": TAG_VOCAB["offer"]},
        "hook": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["visual_subject", "claim", "offer", "hook", "rationale"],
    "additionalProperties": False,
}


def load_tags(path: Path | str = TAGS_PARQUET) -> pd.DataFrame:
    p = Path(path)
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=TAG_COLS)


def _image_block(thumb: Path | None, url: str | None) -> dict[str, Any] | None:
    if thumb is not None and thumb.exists():
        data = base64.standard_b64encode(thumb.read_bytes()).decode("utf-8")
        media = "image/png" if thumb.read_bytes()[:4] == b"\x89PNG" else "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
    if url:
        return {"type": "image", "source": {"type": "url", "url": str(url)}}
    return None


def tag_one(
    client: Any, asset_id: str, body: str | None, title: str | None, thumb: Path | None, url: str | None
) -> dict[str, Any] | None:
    """One Messages call with structured output; None when no image is available or the model declines."""
    img = _image_block(thumb, url)
    if img is None:
        return None
    text = f"Ad name: {asset_id}\nHeadline: {title or '-'}\nPrimary text: {body or '-'}"
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": [img, {"type": "text", "text": text}]}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        return None
    raw = next((b.text for b in resp.content if b.type == "text"), None)
    if not raw:
        return None
    import json

    try:
        out = json.loads(raw)
    except ValueError:
        return None
    clean: dict[str, Any] = {}
    for dim in TAG_DIMS:
        v = out.get(dim)
        clean[dim] = v if v in TAG_VOCAB[dim] else None
    clean["hook"] = " ".join(str(out.get("hook", "")).split()[:8]) or None
    clean["rationale"] = str(out.get("rationale", ""))[:300]
    return clean


def tag_assets(
    assets: pd.DataFrame,
    thumbs_dir: Path | str,
    path: Path | str = TAGS_PARQUET,
    client: Any | None = None,
    limit: int = 200,
) -> pd.DataFrame:
    """Tag every asset without a stored row. Needs ``ANTHROPIC_API_KEY`` (or an ``anthropic`` client passed
    in for tests). Returns the full tag table; failures are logged and the asset is retried next run."""
    existing = load_tags(path)
    if assets.empty:
        return existing
    todo = assets[~assets["asset_id"].isin(existing["asset_id"])].drop_duplicates("asset_id")
    todo = todo[todo["asset_type"].ne("boost_page_promo")]
    if todo.empty:
        return existing
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.info("creative tagging skipped: ANTHROPIC_API_KEY not set (%d assets untagged)", len(todo))
            return existing
        import anthropic

        client = anthropic.Anthropic()
    rows: list[dict[str, Any]] = []
    d = Path(thumbs_dir)
    for _, r in todo.head(limit).iterrows():
        cids = [c.strip() for c in str(r.get("creative_ids") or "").split(",") if c.strip()]
        thumb = next((d / f"{c}.jpg" for c in cids if (d / f"{c}.jpg").exists()), None)
        url = next(
            (str(u) for u in (r.get("image_url"), r.get("thumbnail_url")) if pd.notna(u) and str(u)), None
        )
        try:
            res = tag_one(client, r["asset_id"], r.get("body"), r.get("title"), thumb, url)
        except Exception as e:  # noqa: BLE001
            log.warning("tagging %s failed: %s", r["asset_id"], e)
            continue
        if res is None:
            continue
        rows.append(
            {
                "asset_id": r["asset_id"],
                "creative_id": cids[0] if cids else None,
                **res,
                "model": MODEL,
                "tagged_at": dt.datetime.now(dt.UTC).isoformat(),
            }
        )
    if rows:
        existing = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)[TAG_COLS]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        existing.to_parquet(path, index=False)
    return existing
