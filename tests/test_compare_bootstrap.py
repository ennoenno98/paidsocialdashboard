"""Comparison periods ("vs"), compare_frame, the data snapshot round trip and the sheet-only Klar fallback."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from src import bootstrap as bs
from src.ingest import klar as klar_mod
from src.ingest import klar_sheet as ks
from src.transform import periods as pr

TODAY = dt.date(2026, 10, 27)


def test_comparison_previous_and_last_year_whole_periods():
    q3 = pr.resolve_period("Quarter", "specific", TODAY, year=2026, number=3)
    prev = pr.comparison(q3, "previous")
    assert (prev.start, prev.end, prev.label) == (dt.date(2026, 4, 1), dt.date(2026, 6, 30), "Q2 2026")
    ly = pr.comparison(q3, "last_year")
    assert (ly.start, ly.end, ly.label) == (dt.date(2025, 7, 1), dt.date(2025, 9, 30), "Q3 2025")
    w = pr.resolve_period("Week", "specific", TODAY, year=2026, number=1)
    assert pr.comparison(w, "previous").label == "CW 52/2025"
    assert pr.comparison(w, "last_year").label == "CW 01/2025"
    last3 = pr.resolve_period("Month", "last_n", TODAY)  # Jul–Sep 2026
    p3 = pr.comparison(last3, "previous")
    assert (p3.start, p3.end) == (dt.date(2026, 4, 1), dt.date(2026, 6, 30))
    assert p3.label == "Apr 2026 – Jun 2026"
    assert pr.comparison(q3, "none") is None


def test_comparison_custom_and_partial_ranges():
    cust = pr.resolve_period("Month", "custom", TODAY, custom=(dt.date(2026, 3, 10), dt.date(2026, 3, 19)))
    prev = pr.comparison(cust, "previous")
    assert (prev.start, prev.end) == (dt.date(2026, 2, 28), dt.date(2026, 3, 9))  # same length (10 days)
    ly = pr.comparison(cust, "last_year")
    assert (ly.start, ly.end) == (dt.date(2025, 3, 10), dt.date(2025, 3, 19))
    c = pr.comparison(cust, "custom", (dt.date(2026, 1, 1), dt.date(2026, 1, 31)))
    assert c.mode == "compare_custom" and c.days == 31
    assert pr._minus_year(dt.date(2024, 2, 29)) == dt.date(2023, 2, 28)


def _frame() -> pd.DataFrame:
    rows = []
    for m, reach, foll in (
        (4, 100, 10),
        (5, 200, 20),
        (6, 300, 30),
        (7, 400, 40),
        (8, 500, 50),
        (9, 600, 60),
    ):
        rows.append(
            {
                "account": "vegavero/instagram/DE",
                "year": 2026,
                "period_type": "month",
                "period": m,
                "reach": reach,
                "followers": foll,
            }
        )
    return pd.DataFrame(rows)


def test_compare_frame_sums_flows_and_takes_last_stock():
    q3 = pr.resolve_period("Quarter", "specific", TODAY, year=2026, number=3)
    sel = pr.PeriodSel(
        q3.granularity, q3.start, q3.end, q3.label, q3.mode, compare=pr.comparison(q3, "previous")
    )
    cf = pr.compare_frame(_frame(), sel, ["reach", "followers", "missing"])
    cf = cf.set_index("metric")
    assert cf.loc["reach", "current"] == 1500 and cf.loc["reach", "compare"] == 600
    assert cf.loc["reach", "delta_pct"] == pytest.approx(1.5)
    assert cf.loc["followers", "current"] == 60 and cf.loc["followers", "compare"] == 30
    assert "missing" not in cf.index
    assert pr.compare_frame(_frame(), q3, ["reach"]).empty  # no comparison set
    assert pr.delta_pct(10, 0) is None and pr.delta_pct(12, 10) == pytest.approx(0.2)


def test_snapshot_roundtrip(tmp_path: Path):
    src = tmp_path / "src" / "raw"
    (src / "klar").mkdir(parents=True)
    (src / "klar_sheets").mkdir()
    (src / "klar" / "2026-10-27__vegavero.json").write_text(json.dumps({"rows": []}))
    (src / "klar" / "_scratch.json.bak").write_text("x")
    (src / "klar_sheets" / "Influencer Vegavero.csv").write_text("a,b\n1,2\n")
    blob = bs.make_snapshot(tmp_path / "src")
    b64 = base64.b64encode(blob).decode()
    dst = tmp_path / "dst"
    written = bs.restore_snapshot(dst, b64)
    assert sorted(written) == [
        "raw/klar/2026-10-27__vegavero.json",
        "raw/klar_sheets/Influencer Vegavero.csv",
    ]
    assert (dst / "raw/klar_sheets/Influencer Vegavero.csv").read_text() == "a,b\n1,2\n"
    assert bs.restore_snapshot(dst, b64) == []  # cache present -> no-op
    assert bs.restore_snapshot(tmp_path / "other", "") == []
    res = bs.write_snapshot(tmp_path / "src", tmp_path / "out")
    assert (tmp_path / "out" / "secrets_snippet.toml").read_text().startswith('DATA_SNAPSHOT_B64 = "')
    assert len(res["files"]) == 2


def test_bootstrap_reports_bad_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_SNAPSHOT_B64", "not base64!!")
    monkeypatch.setattr(bs, "DATA_DIR", tmp_path)
    monkeypatch.delenv("SOCIAL_XLSX_B64", raising=False)
    status = bs.bootstrap()
    assert status["snapshot"].startswith("failed")


def test_klar_rows_from_sheet_make_a_klar_frame():
    sheet = ks.load_klar_sheets(Path(os.environ["KLAR_SHEETS_DIR"]))
    rows = ks.klar_rows_from_sheet(sheet)
    assert rows and all(r["costs"] >= 0 for r in rows)
    df = klar_mod.klar_frame(
        [{k: v for k, v in r.items() if k != "_brand"} for r in rows], brand=rows[0]["_brand"], source="sheet"
    )
    assert len(df) == len(rows) and df["source"].eq("sheet").all()
    assert df["net_revenue"].eq(0).all()
    summary = klar_mod.creator_summary(df, since=dt.date(2020, 1, 1), until=dt.date(2030, 1, 1))
    assert not summary.empty and summary["costs"].sum() == pytest.approx(sum(r["costs"] for r in rows))
