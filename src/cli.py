"""Command line entry points: ``parse`` (workbook -> tidy frames + coverage report), ``refresh``, ``report``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

DEFAULT_XLSX = Path(os.environ.get("SOCIAL_XLSX", "data/Social_Media.xlsx"))
FIXTURE_XLSX = Path("tests/fixtures/Social_Media_fixture.xlsx")


def resolve_xlsx(path: str | None) -> tuple[Path, bool]:
    """Return (path, is_fixture). Falls back to the fixture workbook when the real one is absent."""
    p = Path(path) if path else DEFAULT_XLSX
    if p.exists():
        return p, p.resolve() == FIXTURE_XLSX.resolve()
    return FIXTURE_XLSX, True


def cmd_parse(args: argparse.Namespace) -> int:
    from src.ingest.xlsx import parse_workbook, pivot_wide

    path, is_fixture = resolve_xlsx(args.xlsx)
    res = parse_workbook(path)
    pd.set_option("display.width", 220, "display.max_columns", 40, "display.max_rows", 400)
    print(
        f"== workbook: {path}{'  (FIXTURE - drop the real file at data/Social_Media.xlsx)' if is_fixture else ''}\n"
    )
    print("== block coverage report")
    cov = res.coverage()
    print(
        cov[
            [
                "sheet",
                "title",
                "row_start",
                "row_end",
                "account",
                "kind",
                "period_type",
                "n_periods",
                "n_metrics",
                "n_values",
                "status",
            ]
        ].to_string(index=False)
    )
    warn = cov[cov["warnings"].astype(bool)]
    if not warn.empty:
        print("\n== block warnings")
        for _, r in warn.iterrows():
            print(f"- [{r['sheet']}] {r['title']}: {r['warnings']}")
    print("\n== issues")
    print(res.issues_df().to_string(index=False) if res.issues else "none")
    for name, df in res.frames().items():
        print(f"\n== {name}: {len(df)} rows")
        if name in ("weekly", "monthly") and not df.empty:
            wide = pivot_wide(df)
            print(wide.head(args.head).to_string(index=False))
        else:
            print(df.head(args.head).to_string(index=False))
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, df in res.frames().items():
            df.to_parquet(out / f"xlsx_{name}.parquet", index=False)
        cov.to_csv(out / "xlsx_block_coverage.csv", index=False)
        res.issues_df().to_csv(out / "xlsx_issues.csv", index=False)
        print(f"\nwritten to {out}/")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    from src.pipeline import refresh

    status = refresh(xlsx=args.xlsx, out_dir=Path(args.out), klar_days=args.klar_days, live=not args.offline)
    for k, v in status.items():
        print(f"{k}: {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vanatari-social")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="parse the workbook and print tidy frames + block coverage")
    p.add_argument("--xlsx", default=None)
    p.add_argument("--head", type=int, default=12)
    p.add_argument("--out", default=None, help="write parquet/csv outputs to this directory")
    p.set_defaults(func=cmd_parse)
    r = sub.add_parser("refresh", help="run all ingests and write data/processed")
    r.add_argument("--xlsx", default=None)
    r.add_argument("--out", default="data/processed")
    r.add_argument("--klar-days", type=int, default=400)
    r.add_argument("--offline", action="store_true", help="fixtures/cache only, no API calls")
    r.set_defaults(func=cmd_refresh)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
