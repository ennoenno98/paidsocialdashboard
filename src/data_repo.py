"""Private data repository: the nightly refresh pushes ``data/processed`` + ``data/raw`` there, the deployed app
pulls them at start-up.

The code repo is public, so data never lands in it. ``DATA_REPO`` (``owner/name``, default
``ennoenno98/ennoenno98-paidsocialdashboard-data``) must be **private**; ``push`` refuses otherwise. Auth: ``DATA_REPO_TOKEN``,
a fine-grained personal access token scoped to that one repository (contents read for the app, read + write for the
refresh workflow). The app downloads the repository tarball through the GitHub API (no git binary needed) and
extracts ``processed/`` and ``raw/`` into ``data/``.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import httpx

from src.secret_env import clean_secret

log = logging.getLogger(__name__)

DEFAULT_REPO = "ennoenno98/ennoenno98-paidsocialdashboard-data"
API = "https://api.github.com"
SYNC_DIRS = ("processed", "raw")  # relative to data/ locally and to the data-repo root
IGNORE_PATTERNS = ("*.bak", "_*", "snapshot", "*.xlsx.b64")  # scratch files never pushed (basename patterns)
SYNC_FILES = ("refresh_status.json",)
SKIP_SUFFIXES = {".bak"}
MAX_AGE_H = float(os.environ.get("DATA_REPO_MAX_AGE_H", "6"))


def _cfg() -> tuple[str, str, str]:
    # an unset Actions variable arrives as an empty string, so empty falls back to the default too
    return (
        (os.environ.get("DATA_REPO") or "").strip() or DEFAULT_REPO,
        clean_secret("DATA_REPO_TOKEN"),
        (os.environ.get("DATA_REPO_REF") or "").strip() or "main",
    )


def fixture_sources(data_dir: Path | str = "data") -> list[str]:
    """Sources the last refresh filled from synthetic fixtures (missing secrets). Such a run must never be pushed."""
    st = status_json(data_dir)
    return sorted(k for k, v in st.items() if "FIXTURE" in str(v))


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def is_private(repo: str, token: str, timeout: float = 30.0) -> bool:
    r = httpx.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=timeout)
    r.raise_for_status()
    return bool(r.json().get("private"))


def _fresh(data_dir: Path) -> bool:
    marker = data_dir / "processed" / "refresh_status.json"
    if not marker.exists():
        return False
    age_h = (dt.datetime.now() - dt.datetime.fromtimestamp(marker.stat().st_mtime)).total_seconds() / 3600
    return age_h <= MAX_AGE_H


def extract_tarball(blob: bytes, data_dir: Path) -> list[str]:
    """GitHub tarballs wrap everything in ``<owner>-<repo>-<sha>/``; keep only the sync dirs/files below it."""
    written: list[str] = []
    seen: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if len(parts) < 2 or not m.isfile() or ".." in parts:
                continue
            rel = Path(*parts[1:])
            seen.append(str(rel))
            if rel.suffix.lower() == ".xlsx" and rel.parts[0] != "raw":
                rel = Path("raw") / "workbook" / rel.name  # a workbook uploaded anywhere in the repo
            elif not (rel.parts[0] in SYNC_DIRS or str(rel) in SYNC_FILES):
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            out = data_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read())
            written.append(str(rel))
    # refresh_status.json lives at the data-repo root; the app expects it under processed/
    root_status = data_dir / "refresh_status.json"
    if root_status.exists():
        (data_dir / "processed").mkdir(parents=True, exist_ok=True)
        shutil.move(str(root_status), str(data_dir / "processed" / "refresh_status.json"))
    if not written:
        log.warning(
            "data repo: nothing to restore; repository contains %s", ", ".join(seen[:20]) or "no files"
        )
    extract_tarball.last_seen = seen  # type: ignore[attr-defined]
    return written


def fetch(data_dir: Path | str = "data", force: bool = False, timeout: float = 120.0) -> str:
    """Pull the data repo into ``data_dir`` unless the local copy is younger than ``DATA_REPO_MAX_AGE_H``.
    Returns a status line; '' when not configured."""
    repo, token, ref = _cfg()
    if not token:
        return ""
    d = Path(data_dir)
    if not force and _fresh(d):
        return f"{repo}: local copy fresh (< {MAX_AGE_H:g}h)"
    with httpx.Client(headers=_headers(token), timeout=timeout, follow_redirects=True) as client:
        r = client.get(f"{API}/repos/{repo}/tarball/{ref}")
        r.raise_for_status()
        blob = r.content
    written = extract_tarball(blob, d)
    marker = d / "processed" / "refresh_status.json"
    if marker.exists():
        marker.touch()
    if not written:
        seen = getattr(extract_tarball, "last_seen", [])
        return f"{repo}@{ref}: 0 files restored; the repo contains {', '.join(seen[:12]) or 'nothing'}"
    return f"{repo}@{ref}: {len(written)} files"


def auth_header(token: str) -> str:
    """What git's smart-HTTP transport accepts for a token: Basic auth with the ``x-access-token`` user."""
    import base64

    return "Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()


def _git(*args: str, cwd: Path, token: str | None = None) -> str:
    cmd = ["git"]
    if token:  # token goes through a header, never into the remote URL or the log
        cmd += ["-c", f"http.https://github.com/.extraheader={auth_header(token)}"]
    cmd += list(args)
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        err = res.stderr.strip()
        if token:
            err = err.replace(token, "***").replace(auth_header(token), "***")
        raise RuntimeError(
            f"git {' '.join(a for a in args if not a.startswith('http.'))} failed: {err[-600:]}"
        )
    return res.stdout


def push(data_dir: Path | str = "data", message: str | None = None) -> str:
    """Refresh workflow: mirror ``data/processed`` + ``data/raw`` into the private data repo and push one commit
    (nothing pushed when nothing changed). Refuses when the repo is not private."""
    repo, token, ref = _cfg()
    if not token:
        return "not configured (DATA_REPO_TOKEN)"
    fx = fixture_sources(data_dir)
    if fx:
        raise RuntimeError(
            f"refusing to push: the refresh ran on fixture data for {', '.join(fx)} "
            "(set SOCIAL_XLSX_B64 / WINDSOR_API_KEY in the Actions secrets)"
        )
    if not is_private(repo, token):
        raise RuntimeError(f"{repo} is not private: refusing to push data")
    src = Path(data_dir)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        _git(
            "clone",
            "--depth",
            "1",
            "--branch",
            ref,
            f"https://github.com/{repo}.git",
            str(work),
            cwd=Path(tmp),
            token=token,
        )
        for sub in SYNC_DIRS:
            shutil.rmtree(work / sub, ignore_errors=True)
            s = src / sub
            if s.exists():
                shutil.copytree(s, work / sub, ignore=shutil.ignore_patterns(*IGNORE_PATTERNS))
        for name in SYNC_FILES:
            f = src / "processed" / name
            if f.exists():
                shutil.copy2(f, work / name)
        (work / "README.md").write_text(
            "# paidsocialdashboard-data\n\nPrivate data store written by the `refresh` workflow of "
            "ennoenno98/paidsocialdashboard. `processed/` = parquet the app reads, `raw/` = API caches, Klar sheet "
            "exports, input sheet. Do not edit by hand.\n",
            encoding="utf-8",
        )
        _git("add", "-A", cwd=work)
        if not _git("status", "--porcelain", cwd=work).strip():
            return f"{repo}: no changes"
        n = len(_git("status", "--porcelain", cwd=work).splitlines())
        _git(
            "-c",
            "user.name=refresh-bot",
            "-c",
            "user.email=refresh-bot@users.noreply.github.com",
            "commit",
            "-q",
            "-m",
            message or f"refresh {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC",
            cwd=work,
        )
        _git("push", "-q", "origin", f"HEAD:{ref}", cwd=work, token=token)
        return f"{repo}@{ref}: pushed {n} changed files"


def status_json(data_dir: Path | str = "data") -> dict[str, object]:
    p = Path(data_dir) / "processed" / "refresh_status.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
