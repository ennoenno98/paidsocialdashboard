"""Secrets from the environment, tolerant to the way they get pasted.

A GitHub Actions or Streamlit secret is just the value, but a TOML-style line (``WINDSOR_API_KEY = "abc"``) or a
quoted value ends up in the box often enough. ``clean_secret`` strips a leading ``NAME =`` / ``NAME:`` prefix,
surrounding quotes and whitespace, so the key still works and nothing secret has to be typed twice.
"""

from __future__ import annotations

import os
import re

_PREFIX = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*")


def clean_secret(name: str, raw: str | None = None) -> str:
    """Env var ``name`` as the bare value ('' when unset)."""
    val = raw if raw is not None else os.environ.get(name, "")
    val = (val or "").strip()
    m = _PREFIX.match(val)
    if m and m.group(1).upper() == name.upper():
        val = val[m.end() :].strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1].strip()
    return val


def redact(text: str, *secrets: str) -> str:
    """Blank every given secret (raw and URL-encoded) out of ``text`` before it reaches a log."""
    from urllib.parse import quote_plus

    for s in secrets:
        if not s:
            continue
        for form in {s, quote_plus(s)}:
            text = text.replace(form, "***")
    return text
