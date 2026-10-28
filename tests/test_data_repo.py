"""Private data repo: tarball extraction, fetch freshness, push guard, parquet-only workbook mode, login gate."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pandas as pd
import pytest

from src import data_repo as dr
from src.ingest import klar as klar_mod
from src.pipeline import PROCESSED, parse_result_from_parquet, refresh

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def _isolated_klar_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """refresh() with the fixture Klar client writes a cache; keep it out of tests/fixtures."""
    monkeypatch.setattr(klar_mod, "RAW_DIR", tmp_path / "klar_cache")


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_extract_tarball_keeps_only_sync_dirs(tmp_path: Path):
    blob = _tarball(
        {
            "owner-repo-abc123/processed/klar_influencer.parquet": b"pq",
            "owner-repo-abc123/raw/klar/2026-10-27__vegavero.json": b"{}",
            "owner-repo-abc123/refresh_status.json": b'{"windsor": "ok"}',
            "owner-repo-abc123/README.md": b"nope",
            "owner-repo-abc123/../../evil": b"nope",
        }
    )
    written = dr.extract_tarball(blob, tmp_path)
    assert sorted(written) == [
        "processed/klar_influencer.parquet",
        "raw/klar/2026-10-27__vegavero.json",
        "refresh_status.json",
    ]
    assert (tmp_path / "processed" / "refresh_status.json").exists()
    assert not (tmp_path / "README.md").exists() and not (tmp_path.parent / "evil").exists()
    assert dr.status_json(tmp_path) == {"windsor": "ok"}


def test_fetch_unconfigured_and_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("DATA_REPO_TOKEN", raising=False)
    assert dr.fetch(tmp_path) == ""
    monkeypatch.setenv("DATA_REPO_TOKEN", "x")
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "refresh_status.json").write_text("{}")
    assert "fresh" in dr.fetch(tmp_path)  # no network call: marker is younger than MAX_AGE_H


def test_cfg_empty_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_REPO", "")  # an unset Actions variable arrives as ""
    monkeypatch.setenv("DATA_REPO_REF", "")
    monkeypatch.setenv("DATA_REPO_TOKEN", " t ")
    assert dr._cfg() == (dr.DEFAULT_REPO, "t", "main")


def test_push_refuses_fixture_refresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_REPO_TOKEN", "x")
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "refresh_status.json").write_text(
        '{"workbook": "parsed fixture.xlsx (43 blocks) FIXTURE", "windsor": "FIXTURE (tests/fixtures/windsor)"}'
    )
    with pytest.raises(RuntimeError, match="fixture data for windsor, workbook"):
        dr.push(tmp_path)


def test_push_refuses_public_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_REPO_TOKEN", "x")
    monkeypatch.setattr(dr, "is_private", lambda repo, token: False)
    with pytest.raises(RuntimeError, match="not private"):
        dr.push(tmp_path)
    monkeypatch.delenv("DATA_REPO_TOKEN")
    assert dr.push(tmp_path).startswith("not configured")


@pytest.mark.usefixtures("_isolated_klar_cache")
def test_live_refresh_without_klar_api_keeps_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for k in ("KLAR_API_KEY", "KLAR_CSV_EXPORT", "WINDSOR_API_KEY", "META_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    st = refresh(out_dir=tmp_path, live=True)  # no API keys: nothing is pulled, no fixture written as a cache
    assert st["klar"].startswith("not configured") and not (klar_mod.RAW_DIR).exists()
    assert not (tmp_path / "klar_influencer.parquet").exists()


@pytest.mark.usefixtures("_isolated_klar_cache")
def test_parse_result_from_parquet_roundtrip(tmp_path: Path):
    assert parse_result_from_parquet(tmp_path) is None
    refresh(out_dir=tmp_path, live=False)  # fixtures only; writes xlsx_*.parquet + block coverage
    res = parse_result_from_parquet(tmp_path)
    assert res is not None and not res.weekly.empty and res.source.startswith("processed parquet")
    assert len(res.blocks) > 0 and not res.coverage().empty
    assert res.issues_df().empty
    assert tmp_path != PROCESSED


@pytest.mark.usefixtures("_isolated_klar_cache")
def test_bundle_uses_parquet_when_workbook_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from src import pipeline

    refresh(out_dir=tmp_path, live=False)
    monkeypatch.setattr(pipeline, "DEFAULT_XLSX", tmp_path / "missing.xlsx")
    b = pipeline.build_bundle(processed=tmp_path)
    assert not b.is_fixture and b.xlsx.source.startswith("processed parquet")
    assert isinstance(b.weekly_wide, pd.DataFrame) and not b.weekly_wide.empty


def test_login_gate_noop_without_password(monkeypatch: pytest.MonkeyPatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("APP_PASSWORD", raising=False)
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=120).run()
    assert not at.exception and not at.text_input
    monkeypatch.setenv("APP_PASSWORD", "secret")
    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=120).run()
    assert not at.exception and at.text_input[0].label == "Password"
    at.text_input[0].set_value("secret")
    at.button[0].click().run()
    assert at.session_state["_auth_ok"] is True
