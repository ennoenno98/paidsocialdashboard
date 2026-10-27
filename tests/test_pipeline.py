from __future__ import annotations

from src.pipeline import build_bundle, refresh


def test_build_bundle_on_fixtures():
    b = build_bundle()
    assert b.is_fixture and b.has_api
    assert (b.ig_posts["source"] == "windsor").all() and not b.boosted.empty
    assert {"boost_spend_meta", "delta_meta_minus_sheet"} <= set(b.spend_recon.columns)
    assert not b.weekly_wide.empty and not b.posts.empty and not b.influencers.empty
    assert set(b.influencers["reach_source"]) <= {"klar", "klar_sheet", "manual", "n/a"}
    assert (b.influencers.loc[b.influencers["reach_source"].eq("n/a"), "cpm"].isna()).all()
    assert not b.spend_recon.empty and "delta_susy_minus_sheet" in b.spend_recon
    iss = b.issues_df()
    assert (iss["source"] == "klar").any()  # unmatched Klar names surfaced


def test_refresh_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("KLAR_API_KEY", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("src.ingest.klar.RAW_DIR", tmp_path / "raw")
    status = refresh(out_dir=tmp_path / "processed", live=False)
    assert status["klar"].startswith("ok") and status["windsor"].startswith("windsor cache")
    assert status["windsor_frames"].startswith("media")
    assert (tmp_path / "processed" / "klar_influencer.parquet").exists()
    assert (tmp_path / "processed" / "ig_posts.parquet").exists()
    assert (tmp_path / "processed" / "xlsx_block_coverage.csv").exists()
