"""Logos and platform icons for the dashboard chrome.

Brand logos come from the Vanatari Shopify file store (durable cdn.shopify.com URLs, found via the Admin API
``files`` query). Platform glyphs come from Simple Icons' CDN. Images are fetched by the viewer's browser, not by
the server, so nothing here needs network access at build time. Brands without a hosted logo render as a
wordmark in the brand ink.
"""

from __future__ import annotations

import html

SHOPIFY_FILES = "https://cdn.shopify.com/s/files/1/1031/0808/4043/files"
BRAND_LOGOS: dict[str, str] = {
    "vanatari": f"{SHOPIFY_FILES}/vanatari-logo.svg?v=1782372619",  # 993x225
    "vegavero": f"{SHOPIFY_FILES}/vegavero-logo.svg?v=1783955323",  # 1880x690
    # wowtamins / jasnum: no logo file in the Vanatari Shopify store yet -> wordmark fallback
}
BRAND_NAMES = {"vanatari": "Vanatari", "vegavero": "Vegavero", "wowtamins": "Wowtamins", "jasnum": "Jasnum"}
# Simple Icons (CC0 glyphs; colour = brand hex of the platform)
PLATFORM_ICONS: dict[str, str] = {
    "instagram": "https://cdn.simpleicons.org/instagram/E4405F",
    "tiktok": "https://cdn.simpleicons.org/tiktok/000000",
    "meta": "https://cdn.simpleicons.org/meta/0467DF",
    "facebook": "https://cdn.simpleicons.org/facebook/0866FF",
}
PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "meta": "Meta Ads", "facebook": "Facebook"}


def brand_html(brand: str, height: int = 22) -> str:
    """``<img>`` of the brand logo, or a wordmark span when no logo is hosted."""
    url = BRAND_LOGOS.get(brand)
    name = html.escape(BRAND_NAMES.get(brand, brand.title()))
    if url:
        return (
            f'<img src="{url}" alt="{name}" title="{name}" style="height:{height}px;width:auto;'
            'vertical-align:middle;display:inline-block">'
        )
    return f'<span style="font-weight:700;font-size:{height - 4}px;vertical-align:middle">{name}</span>'


def platform_html(platform: str, size: int = 16) -> str:
    url = PLATFORM_ICONS.get(platform)
    name = html.escape(PLATFORM_NAMES.get(platform, platform.title()))
    if not url:
        return f'<span style="vertical-align:middle">{name}</span>'
    return (
        f'<img src="{url}" alt="{name}" title="{name}" style="height:{size}px;width:{size}px;'
        'vertical-align:middle;display:inline-block">'
    )


def account_html(account: str, height: int = 22) -> str:
    """brand logo + platform glyph + market tag for an account key like ``vegavero/instagram/IT``."""
    parts = account.split("/")
    brand, platform, market = (parts + ["", "", ""])[:3]
    tag = (
        f'<span style="font-size:12px;letter-spacing:.04em;opacity:.75;vertical-align:middle">{html.escape(market)}</span>'
        if market
        else ""
    )
    return (
        '<div style="display:flex;align-items:center;gap:8px;margin:2px 0 6px 0" '
        f'title="{html.escape(account)}">{brand_html(brand, height)}{platform_html(platform, height - 6)}{tag}</div>'
    )


def heading_html(text: str, platform: str | None = None, level: int = 3) -> str:
    """Section heading with an optional platform glyph in front (replaces ``st.subheader``)."""
    icon = platform_html(platform, 20) + " " if platform else ""
    return f'<h{level} style="display:flex;align-items:center;gap:8px">{icon}{html.escape(text)}</h{level}>'
