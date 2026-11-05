"""Meta Ad Library API (``ads_archive``): competitor ads for pages reaching the EU.

Non-political ads are returned for EU-reached countries with start / stop time, platforms, creative text, targeting
and an estimated EU reach; spend and impressions are not available. Access needs an app plus the user's Ad Library
identity confirmation (``META_ADLIB_TOKEN``; ``META_APP_ID`` / ``META_APP_SECRET`` let the job renew the token).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.secret_env import clean_secret, redact

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
FIELDS = [
    "id",
    "page_id",
    "page_name",
    "ad_creation_time",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_creative_link_captions",
    "ad_snapshot_url",
    "publisher_platforms",
    "languages",
    "eu_total_reach",
    "target_ages",
    "target_gender",
    "target_locations",
    "beneficiary_payers",
]


class AdLibraryClient:
    def __init__(self, token: str | None = None, timeout: float = 60.0) -> None:
        self.token = clean_secret("META_ADLIB_TOKEN", token) if token else clean_secret("META_ADLIB_TOKEN")
        if not self.token:
            raise RuntimeError("META_ADLIB_TOKEN not set")
        self.timeout = timeout

    def _get(self, client: httpx.Client, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        r = client.get(url, params=params)
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            msg = redact(str(err.get("message") or r.text[:300]), self.token)
            raise RuntimeError(
                f"ads_archive HTTP {r.status_code}: {msg} (code {err.get('code')}, subcode {err.get('error_subcode')})"
            )
        return r.json()

    def search(
        self,
        page_ids: list[str] | None = None,
        search_terms: str | None = None,
        countries: list[str] | None = None,
        active: str = "ALL",
        limit: int = 100,
        max_pages: int = 50,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """All ads matching the filters (follows ``paging.next``). ``countries`` default DE; EU codes give EU fields."""
        params: dict[str, Any] = {
            "access_token": self.token,
            "ad_reached_countries": "[" + ",".join(f'"{c}"' for c in (countries or ["DE"])) + "]",
            "ad_active_status": active,
            "ad_type": "ALL",
            "fields": ",".join(fields or FIELDS),
            "limit": limit,
        }
        if page_ids:
            params["search_page_ids"] = ",".join(str(p) for p in page_ids)
        if search_terms:
            params["search_terms"] = search_terms
        if not page_ids and not search_terms:
            raise ValueError("page_ids or search_terms required")
        out: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            payload = self._get(client, f"{GRAPH}/ads_archive", params)
            out.extend(payload.get("data", []))
            for _ in range(max_pages - 1):
                nxt = (payload.get("paging") or {}).get("next")
                if not nxt:
                    break
                payload = self._get(client, nxt, None)
                out.extend(payload.get("data", []))
        return out

    def check(self, page_id: str | None = None) -> dict[str, Any]:
        """One small call that proves the token and the Ad Library access: returns counts, never the token."""
        try:
            ads = self.search(
                page_ids=[page_id] if page_id else None,
                search_terms=None if page_id else "vitamin",
                countries=["DE"],
                limit=5,
                max_pages=1,
                fields=["id", "page_name", "ad_delivery_start_time", "eu_total_reach"],
            )
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "ads_returned": len(ads),
            "pages": sorted({str(a.get("page_name")) for a in ads}),
            "eu_reach_present": any(a.get("eu_total_reach") is not None for a in ads),
        }


def token_info(token: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
    """Expiry and scopes of the token via the debug endpoint (needs META_APP_ID / META_APP_SECRET)."""
    tok = clean_secret("META_ADLIB_TOKEN", token) if token else clean_secret("META_ADLIB_TOKEN")
    app_id, app_secret = clean_secret("META_APP_ID"), clean_secret("META_APP_SECRET")
    if not (tok and app_id and app_secret):
        return {"available": False, "reason": "META_APP_ID / META_APP_SECRET not set"}
    r = httpx.get(
        f"{GRAPH}/debug_token",
        params={"input_token": tok, "access_token": f"{app_id}|{app_secret}"},
        timeout=timeout,
    )
    if r.status_code >= 400:
        return {"available": False, "reason": redact(r.text[:200], tok, app_secret)}
    d = r.json().get("data", {})
    return {
        "available": True,
        "valid": d.get("is_valid"),
        "expires_at": d.get("expires_at"),
        "scopes": d.get("scopes"),
        "type": d.get("type"),
    }


def exchange_long_lived(token: str | None = None, timeout: float = 30.0) -> str | None:
    """Short-lived user token -> long-lived (60 days). Returns None when app id / secret are missing."""
    tok = clean_secret("META_ADLIB_TOKEN", token) if token else clean_secret("META_ADLIB_TOKEN")
    app_id, app_secret = clean_secret("META_APP_ID"), clean_secret("META_APP_SECRET")
    if not (tok and app_id and app_secret):
        return None
    r = httpx.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": tok,
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        log.warning("token exchange failed: %s", redact(r.text[:200], tok, app_secret))
        return None
    return str(r.json().get("access_token") or "") or None


def main() -> int:  # `python -m src.ingest.adlibrary [page_id]`
    import json
    import sys

    page = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADLIB_CHECK_PAGE_ID") or None
    try:
        client = AdLibraryClient()
    except RuntimeError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    res = client.check(page)
    res["token"] = token_info()
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
