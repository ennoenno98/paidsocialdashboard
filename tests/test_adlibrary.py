"""Meta Ad Library client: paging, error reporting without the token, check() shape."""

from __future__ import annotations

import httpx
import pytest

from src.ingest import adlibrary as al


def _mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = httpx.Client

    class _Client(real):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(al.httpx, "Client", _Client)


def test_search_follows_paging_and_builds_eu_params(monkeypatch: pytest.MonkeyPatch):
    seen: list[httpx.URL] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        if "page2" in str(req.url):
            return httpx.Response(200, json={"data": [{"id": "3"}]})
        return httpx.Response(
            200,
            json={"data": [{"id": "1"}, {"id": "2"}], "paging": {"next": f"{al.GRAPH}/ads_archive?page2=1"}},
        )

    _mock(monkeypatch, handler)
    c = al.AdLibraryClient(token='META_ADLIB_TOKEN = "tok"')
    assert c.token == "tok"
    ads = c.search(page_ids=["42"], countries=["DE", "IT"])
    assert [a["id"] for a in ads] == ["1", "2", "3"]
    q = dict(seen[0].params)
    assert (
        q["search_page_ids"] == "42" and q["ad_reached_countries"] == '["DE","IT"]' and q["ad_type"] == "ALL"
    )
    with pytest.raises(ValueError):
        c.search()


def test_errors_are_reported_without_the_token(monkeypatch: pytest.MonkeyPatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Application does not have permission tok",
                    "code": 10,
                    "error_subcode": 2332002,
                }
            },
        )

    _mock(monkeypatch, handler)
    c = al.AdLibraryClient(token="tok")
    res = c.check("42")
    assert (
        res["ok"] is False
        and "subcode 2332002" in res["error"]
        and "tok" not in res["error"].replace("subcode", "")
    )


def test_check_reports_counts(monkeypatch: pytest.MonkeyPatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "1", "page_name": "Acme", "eu_total_reach": 1200},
                    {"id": "2", "page_name": "Acme"},
                ]
            },
        )

    _mock(monkeypatch, handler)
    res = al.AdLibraryClient(token="tok").check("42")
    assert res == {"ok": True, "ads_returned": 2, "pages": ["Acme"], "eu_reach_present": True}


def test_client_requires_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("META_ADLIB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="META_ADLIB_TOKEN"):
        al.AdLibraryClient()
