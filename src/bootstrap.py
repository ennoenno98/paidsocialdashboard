"""Data bootstrap for deployments without a filesystem of their own (Streamlit Community Cloud, a fresh clone).

The repo is public, so no data is committed or published as a release asset. Instead the private inputs travel
as secrets / env vars and are materialised on start-up:

- ``SOCIAL_XLSX_B64``: the workbook, base64 -> ``SOCIAL_XLSX`` (default ``data/Social_Media.xlsx``).
- ``DATA_REPO`` + ``DATA_REPO_TOKEN``: the private data repository the nightly refresh pushes to; pulled first
  (``src/data_repo.py``), so the two secrets below are only fallbacks.
- ``DATA_SNAPSHOT_B64``: base64 of a gzip tar of ``data/raw`` (Klar caches, Klar sheet exports, input sheet),
  produced with ``make snapshot`` / ``python -m src.cli snapshot``. Windsor is pulled live (``WINDSOR_API_KEY``)
  and is not part of the snapshot.

Both are no-ops when the target already exists.
"""

from __future__ import annotations

import base64
import gzip
import io
import logging
import os
import tarfile
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path("data")
SNAPSHOT_DIRS = ("raw/klar", "raw/klar_sheets", "raw/input_sheet")
SNAPSHOT_SUFFIXES = {".json", ".csv", ".xlsx"}


def restore_workbook(xlsx: Path | None = None) -> Path | None:
    b64 = os.environ.get("SOCIAL_XLSX_B64", "").strip()
    target = Path(xlsx) if xlsx else Path(os.environ.get("SOCIAL_XLSX", "data/Social_Media.xlsx"))
    if not b64 or target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(b64))
    log.info("bootstrap: workbook restored to %s", target)
    return target


def restore_snapshot(data_dir: Path | str | None = None, b64: str | None = None) -> list[str]:
    """Extract ``DATA_SNAPSHOT_B64`` into ``data_dir`` unless the Klar cache is already there. Members are
    restricted to the snapshot folders (no absolute paths, no ``..``)."""
    raw = (b64 if b64 is not None else os.environ.get("DATA_SNAPSHOT_B64", "")).strip()
    d = Path(data_dir) if data_dir is not None else DATA_DIR
    if not raw or any((d / "raw" / "klar").glob("*.json")):
        return []
    blob = gzip.decompress(base64.b64decode(raw))
    written: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tar:
        for m in tar.getmembers():
            name = m.name.lstrip("./")
            if not m.isfile() or ".." in Path(name).parts or not name.startswith(SNAPSHOT_DIRS):
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            out = d / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read())
            written.append(name)
    log.info("bootstrap: snapshot restored (%d files)", len(written))
    return written


def make_snapshot(data_dir: Path | str | None = None) -> bytes:
    """gzip tar (bytes) of the snapshot folders under ``data_dir``; ``.bak`` and other scratch files excluded."""
    d = Path(data_dir) if data_dir is not None else DATA_DIR
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for sub in SNAPSHOT_DIRS:
            for p in sorted((d / sub).glob("*")):
                if p.is_file() and p.suffix in SNAPSHOT_SUFFIXES and not p.name.startswith("_"):
                    tar.add(p, arcname=str(p.relative_to(d)))
    return gzip.compress(buf.getvalue(), compresslevel=9)


def write_snapshot(
    data_dir: Path | str | None = None, out_dir: Path | str | None = None
) -> dict[str, object]:
    """Write ``data_snapshot.tar.gz`` and ``secrets_snippet.toml`` (the DATA_SNAPSHOT_B64 line to paste into
    Streamlit's Secrets or a GitHub Actions secret) into ``out_dir`` (default ``data/snapshot``)."""
    blob = make_snapshot(data_dir)
    b64 = base64.b64encode(blob).decode("ascii")
    out = Path(out_dir) if out_dir else (Path(data_dir) if data_dir is not None else DATA_DIR) / "snapshot"
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_snapshot.tar.gz").write_bytes(blob)
    (out / "secrets_snippet.toml").write_text(f'DATA_SNAPSHOT_B64 = "{b64}"\n', encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r:") as tar:
        names = tar.getnames()
    return {"files": names, "bytes": len(blob), "b64_chars": len(b64), "out": str(out)}


def bootstrap() -> dict[str, str]:
    """Run both restores; never raises (a bad secret is reported, the app still starts)."""
    from src import data_repo

    status: dict[str, str] = {}
    for name, fn in (
        ("data_repo", data_repo.fetch),
        ("workbook", restore_workbook),
        ("snapshot", restore_snapshot),
    ):
        try:
            res = fn()
            if res:
                status[name] = f"restored ({len(res)} files)" if isinstance(res, list) else f"restored {res}"
        except Exception as e:  # noqa: BLE001
            status[name] = f"failed: {type(e).__name__}: {e}"
            log.warning("bootstrap %s failed: %s", name, e)
    return status
