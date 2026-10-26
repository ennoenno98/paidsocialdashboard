"""Join Klar influencer rows to the Creators master: exact on discount code, then fuzzy on name/handle."""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz, process

MATCH_COLS = [
    "creator_name",
    "creator_handle",
    "creator_platform",
    "creator_code",
    "creator_followers",
    "creator_deal",
    "creator_country",
    "creator_field",
    "match_method",
    "match_score",
]


def _norm_code(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.upper().replace("", pd.NA)


def join_klar_creators(
    klar: pd.DataFrame, creators: pd.DataFrame, threshold: int = 85
) -> dict[str, pd.DataFrame]:
    """Returns {'matched', 'unmatched_klar', 'unmatched_creators'}.

    ``klar`` must have influencer_name and discount_code columns (one row per Klar influencer/code).
    """
    k = klar.copy()
    c = creators.copy().reset_index(drop=True)
    c["_cid"] = c.index
    if k.empty:
        return {
            "matched": k.assign(**{col: pd.NA for col in MATCH_COLS}),
            "unmatched_klar": k,
            "unmatched_creators": c.drop(columns="_cid"),
        }
    k["_code"] = _norm_code(k["discount_code"]) if "discount_code" in k else pd.NA
    c["_code"] = _norm_code(c["code"]) if "code" in c else pd.NA
    cre_cols = {
        "name": "creator_name",
        "handle": "creator_handle",
        "platform": "creator_platform",
        "code": "creator_code",
        "followers": "creator_followers",
        "deal": "creator_deal",
        "country": "creator_country",
        "field": "creator_field",
    }
    for src in cre_cols:
        if src not in c.columns:
            c[src] = pd.NA
    cre = c[["_cid", "_code", *cre_cols]].rename(columns=cre_cols)

    # 1) exact on discount code
    by_code = cre.dropna(subset=["_code"]).drop_duplicates("_code")
    m = k.merge(by_code, on="_code", how="left")
    m["match_method"] = m["_cid"].notna().map({True: "discount_code", False: None})
    m["match_score"] = m["_cid"].notna().map({True: 100.0, False: None})

    # 2) fuzzy on influencer_name vs creator name / handle
    choices: dict[int, str] = {}
    for _, r in cre.iterrows():
        for v in (r["creator_name"], r["creator_handle"]):
            if isinstance(v, str) and v.strip():
                choices[len(choices)] = f"{r['_cid']}|{v.strip().lower()}"
    todo = m["_cid"].isna() & m["influencer_name"].notna()
    for i in m.index[todo]:
        q = str(m.at[i, "influencer_name"]).strip().lower()
        if not q or not choices:
            continue
        hit = process.extractOne(
            q,
            {j: v.split("|", 1)[1] for j, v in choices.items()},
            scorer=fuzz.token_set_ratio,
            score_cutoff=threshold,
        )
        if hit is None:
            continue
        _, score, j = hit
        cid = int(choices[j].split("|", 1)[0])
        row = cre[cre["_cid"].eq(cid)].iloc[0]
        for col in cre_cols.values():
            m.at[i, col] = row[col]
        m.at[i, "_cid"] = cid
        m.at[i, "match_method"] = "fuzzy_name"
        m.at[i, "match_score"] = float(score)

    matched_ids = set(m["_cid"].dropna().astype(int))
    unmatched_creators = c[~c["_cid"].isin(matched_ids)].drop(columns=["_cid", "_code"])
    unmatched_klar = m[m["_cid"].isna()].drop(columns=["_cid", "_code"] + MATCH_COLS, errors="ignore")
    matched = m.drop(columns=["_cid", "_code"])
    return {"matched": matched, "unmatched_klar": unmatched_klar, "unmatched_creators": unmatched_creators}
