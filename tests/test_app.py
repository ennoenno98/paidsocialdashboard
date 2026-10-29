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
