"""Smoke-test every Streamlit page with AppTest on fixture data (no browser)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    sorted((ROOT / "app" / "pages").glob("*.py"))
    + [ROOT / "app" / "Home.py"]
    + sorted((ROOT / "app" / "creatives").glob("*.py"))
)


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_page_renders(page: Path):
    at = AppTest.from_file(str(page), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_creatives_entrypoint_renders():
    at = AppTest.from_file(str(ROOT / "creatives_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Paid creatives" in t.value for t in at.title)


def test_cloud_entrypoint_renders():
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Overview" in t.value for t in at.title)


def test_creatives_row_click_drives_detail():
    """A row selected in the asset table becomes the asset in the detail expander; the dropdown stays usable."""
    at = AppTest.from_file(str(ROOT / "app" / "creatives" / "Paid_creatives.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    first = at.selectbox(key="pick_prospecting").value
    at.session_state["tbl_prospecting"] = {"selection": {"rows": [2], "columns": []}}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    picked = at.selectbox(key="pick_prospecting").value
    assert picked != first and at.expander[0].proto.expanded
    # the dropdown can move away again while the same row stays selected
    at.selectbox(key="pick_prospecting").select(first).run()
    assert not at.exception and at.selectbox(key="pick_prospecting").value == first


def test_thumbnail_src_static_or_data_uri(tmp_path, monkeypatch):
    """Thumbnails are referenced by static URL when Streamlit serves static/, else embedded as a data URI."""
    from app import common
    from src.ingest import windsor as wz

    (tmp_path / "creatives").mkdir()
    (tmp_path / "creatives" / "42.jpg").write_bytes(b"\xff\xd8jpegbytes")
    monkeypatch.setattr(wz, "CREATIVES_DIR", tmp_path / "creatives")
    monkeypatch.setattr(common, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(common, "_STATIC_STATE", {"ready": None})
    monkeypatch.setattr(common.st.config, "get_option", lambda k: False)
    assert common.thumbnail_src("42, 43").startswith("data:image/jpeg;base64,")
    assert common.thumbnail_src("43") is None and common.thumbnail_src(float("nan")) is None
    assert common.thumbnail_file("43,42") == tmp_path / "creatives" / "42.jpg"
    monkeypatch.setattr(common, "_STATIC_STATE", {"ready": None})
    monkeypatch.setattr(common.st.config, "get_option", lambda k: k == "server.enableStaticServing")
    assert common.thumbnail_src("42") == "app/static/creatives/42.jpg"
    mirrored = tmp_path / "static" / "creatives" / "42.jpg"
    assert mirrored.is_file() and not mirrored.is_symlink()  # a real file: Streamlit rejects outside symlinks
    (tmp_path / "creatives" / "7.jpg").write_bytes(b"\xff\xd8new")  # cached after start-up
    assert common.thumbnail_src("7") == "app/static/creatives/7.jpg"


def test_fixture_retry_is_rate_limited(monkeypatch):
    """A fixture bundle with a token set rebuilds at most once per FIXTURE_RETRY_S, not once per session."""
    from app import common

    calls = {"n": 0}

    class _B:
        is_fixture = True

        def __getattr__(self, name):  # every Bundle field "exists"
            return None

    def fake(fields):
        calls["n"] += 1
        return _B()

    fake.clear = lambda: None
    monkeypatch.setattr(common, "_cached_bundle", fake)
    monkeypatch.setenv("DATA_REPO_TOKEN", "x")
    monkeypatch.setattr(common, "_FX_RETRY", {"at": float("-inf")})
    common.get_bundle()
    common.get_bundle()
    assert calls["n"] == 3  # first build + one retry, the second call reuses the cache
