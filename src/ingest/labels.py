"""Label / value normalisation for the human-formatted workbook."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

_WS = re.compile(r"\s+")

# normalised sheet label -> canonical metric name. Text metrics are listed in TEXT_METRICS.
METRIC_SYNONYMS: dict[str, str] = {
    # engagement / reach
    "er": "er_sheet",
    "engagement rate": "er_sheet",
    "reach": "reach",
    "views": "views",
    "post views": "views",
    "video views": "video_views",
    "play time": "play_time",
    "impressions": "impressions",
    # followers
    "follows": "follows",
    "follow": "follows",
    "new followers": "new_followers",
    "unfollows": "unfollows",
    "unfollow": "unfollows",
    "overall": "net_follows",
    "overall follows": "net_follows",
    "net followers": "net_follows",
    "net follows": "net_follows",
    "total followers": "followers",
    "followers": "followers",
    # activity
    "number of post": "n_posts",
    "number of posts": "n_posts",
    "number of igs": "n_igs",
    "posts": "n_posts",
    # per-post interactions
    "like": "likes",
    "likes": "likes",
    "comments": "comments",
    "comment": "comments",
    "save": "saves",
    "saves": "saves",
    "share": "shares",
    "shares": "shares",
    "repost": "reposts",
    "reposts": "reposts",
    # boosting
    "boosted post": "boosted_post",
    "ad spent": "boost_spend",
    "ad spend": "boost_spend",
    "total spent": "boost_spend",
    "total spend": "boost_spend",
    "boosting spent": "boost_spend",
    "boosting spend": "boost_spend",
    "ad cost": "boost_spend",
    "ad costs": "boost_spend",
    "spent": "boost_spend",
    "spend": "boost_spend",
    "budget": "boost_budget",
    "goal": "goal",
    "audience": "audience",
    "website visits": "website_visits",
    "engagement": "engagement",
    "link clicks": "link_clicks",
    # post-by-post
    "post": "post_name",
    "format": "format",
}

TEXT_METRICS: frozenset[str] = frozenset({"boosted_post", "goal", "audience", "post_name", "format"})

_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "mär": 3,
    "mae": 3,
    "apr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "okt": 10,
    "nov": 11,
    "dec": 12,
    "dez": 12,
}
_MONTH_FULL = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "januar",
    "februar",
    "märz",
    "mai",
    "juni",
    "juli",
    "oktober",
    "dezember",
    "sept",
    "janury",  # sheet typo
}
_CW_RE = re.compile(r"^(?:cw|kw|week|wk)\s*0*(\d{1,2})$", re.I)
_NULL_STRINGS = frozenset(
    {
        "",
        "/",
        "-",
        "–",
        "—",
        "n/a",
        "na",
        "nan",
        "none",
        "#div/0!",
        "#ref!",
        "#value!",
        "#n/a",
        "#name?",
        "#num!",
        "x",
        "?",
    }
)


def norm_label(x: Any) -> str:
    """Strip, lowercase, collapse whitespace, drop trailing punctuation."""
    if x is None:
        return ""
    s = _WS.sub(" ", str(x)).strip().lower()
    return s.rstrip(":").strip()


def canonical_metric(label: Any) -> str | None:
    """Map a sheet label to a canonical metric name (None if unknown)."""
    n = norm_label(label)
    if not n:
        return None
    if n in METRIC_SYNONYMS:
        return METRIC_SYNONYMS[n]
    # tolerate things like "AD Spent (EUR)" / "Reach*"
    n2 = re.sub(r"[\(\[].*?[\)\]]", "", n).replace("*", "").strip()
    return METRIC_SYNONYMS.get(n2)


def parse_cw(x: Any) -> int | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x) if 1 <= int(x) <= 53 else None
    m = _CW_RE.match(norm_label(x))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 53 else None


def parse_month(x: Any) -> int | None:
    if x is None:
        return None
    if isinstance(x, (datetime, date)):
        return x.month
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x) if 1 <= int(x) <= 12 else None
    n = norm_label(x)
    if not n:
        return None
    n = re.sub(r"[^a-zäöü]", "", n)
    if not n:
        return None
    if n in _MONTHS:
        return _MONTHS[n]
    if n in _MONTH_FULL or len(n) >= 3:
        return _MONTHS.get(n[:3])
    return None


def parse_number(x: Any) -> float:
    """Parse a cell to float; NaN for '/', '#DIV/0!', names, blanks. Percent strings -> fraction."""
    if x is None:
        return math.nan
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, (datetime, date)):
        return math.nan
    s = str(x).strip()
    if s.lower() in _NULL_STRINGS:
        return math.nan
    pct = s.endswith("%")
    s = s.rstrip("%").strip().replace("€", "").replace("eur", "").replace(" ", "")
    if "," in s and "." in s:
        # 1.234,5 (last sep is decimal comma) vs 1,234.5
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")  # 12.345 -> 12345
    try:
        v = float(s)
    except ValueError:
        return math.nan
    return v / 100.0 if pct else v


def parse_play_time(x: Any) -> float:
    """'1h12m' / '62h' / '45m' / '1:12:00' / numeric minutes -> minutes."""
    if x is None:
        return math.nan
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip().lower().replace(" ", "")
    if not s or s in _NULL_STRINGS:
        return math.nan
    if re.fullmatch(r"\d+:\d{1,2}(:\d{1,2})?", s):
        parts = [int(p) for p in s.split(":")]
        if len(parts) == 3:
            return parts[0] * 60 + parts[1] + parts[2] / 60
        return parts[0] * 60 + parts[1]
    total = 0.0
    found = False
    for num, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(d|h|m|min|s)", s):
        found = True
        v = float(num.replace(",", "."))
        total += {"d": 1440, "h": 60, "m": 1, "min": 1, "s": 1 / 60}[unit] * v
    if found:
        return total
    v = parse_number(s)
    return v


def normalise_er(x: float) -> float:
    """Sheet ER may be a fraction (0.035) or a percent number (3.5). Return a fraction."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return math.nan
    return x / 100.0 if x > 1.0 else x


def is_blank_row(row: list[Any]) -> bool:
    return all(c is None or (isinstance(c, str) and not c.strip()) for c in row)


def ensure_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("float64")
